# --------------------------------------------------------------------------
# Blendyn -- file eigenlib.py
# Copyright (C) 2015 -- 2021 Andrea Zanoni -- andrea.zanoni@polimi.it
# --------------------------------------------------------------------------
# ***** BEGIN GPL LICENSE BLOCK *****
#
#    This file is part of Blendyn, add-on script for Blender.
#
#    Blendyn is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    Blendyn is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with Blendyn.  If not, see <http://www.gnu.org/licenses/>.
#
# ***** END GPL LICENCE BLOCK *****
# -------------------------------------------------------------------------- 

import bpy
from mathutils import Euler, Vector, Matrix
import math
import numpy as np
from bpy.props import IntProperty, FloatProperty

import logging

from .nodelib import axes

import os
from sys import float_info

try: 
    from netCDF4 import Dataset
except ImportError as ierr:
    print("BLENDYN::eigenlib.py: could not find netCDF4 module. NetCDF import "\
        + "will be disabled. The reported error was:")
    print("${0}".format(ierr))

def update_curr_eigmode(self, context):
    mbs = context.scene.mbdyn
    nc = Dataset(os.path.join(os.path.dirname(mbs.file_path), \
            mbs.file_basename + '.nc'), 'r')
    eigsol_idx = context.scene.mbdyn.curr_eigsol
    if self.curr_eigmode < 1:
        self.curr_eigmode = 1
        alpha_r = nc.variables['eig.' + str(eigsol_idx) + '.alpha'][0, 0]
        alpha_i = nc.variables['eig.' + str(eigsol_idx) + '.alpha'][0, 1]
        beta = nc.variables['eig.' + str(eigsol_idx) + '.alpha'][0, 2]
        det = (alpha_r + beta)**2 + alpha_i**2
    elif self.curr_eigmode > self.iNVec:
        self.curr_eigmode = self.iNVec
        alpha_r = nc.variables['eig.' + str(eigsol_idx) + '.alpha'][self.iNVec - 1, 0]
        alpha_i = nc.variables['eig.' + str(eigsol_idx) + '.alpha'][self.iNVec - 1, 1]
        beta = nc.variables['eig.' + str(eigsol_idx) + '.alpha'][self.iNVec - 1, 2]
        det = (alpha_r + beta)**2 + alpha_i**2
    else:
        alpha_r = nc.variables['eig.' + str(eigsol_idx) + '.alpha'][self.curr_eigmode - 1 , 0]
        alpha_i = nc.variables['eig.' + str(eigsol_idx) + '.alpha'][self.curr_eigmode - 1, 1]
        beta = nc.variables['eig.' + str(eigsol_idx) + '.alpha'][self.curr_eigmode - 1, 2]
        det = (alpha_r + beta)**2 + alpha_i**2
    
    lambda_real = (1./self.dCoef)*(alpha_r**2 + alpha_i**2 - beta**2)/det
    lambda_imag = (1./self.dCoef)*(2*alpha_i*beta)/det
    if alpha_i*beta < 0:
        lambda_imag = -lambda_imag

    if lambda_imag <= 2.*float_info.epsilon:
        self.lambda_freq = 0.
        self.lambda_damp = 100
    else:
        self.lambda_freq = 1/2/math.pi*(lambda_real**2 + lambda_imag**2)**.5
        self.lambda_damp = int(-lambda_real/(self.lambda_freq*2*math.pi)*100)
    return
# -----------------------------------------------------------
# end of update_curr_eigmode() function

def update_curr_eigsol(self, context):
    if self.curr_eigsol < 0:
        self.curr_eigsol = 0
    elif self.curr_eigsol > (len(self.eigensolutions) - 1):
        self.curr_eigsol = (len(self.eigensolutions) - 1)
# -----------------------------------------------------------
# end of update_curr_eigsol() function

class BLENDYN_PG_eigenanalysis(bpy.types.PropertyGroup):
    """ Holds the properties of the eigensolutions found in the MBDyn output """

    index: IntProperty(
            name = "index",
            description = "Index of the eigenanalysis"
            )

    step: IntProperty(
            name = "step",
            description = "Step number at which the eigenanalysis was performed"
            )

    time: FloatProperty(
            name = "time",
            description = "the time in seconds at which the eigenanalysis was performed",
            precision = 6
            )

    dCoef: FloatProperty(
            name = "dCoef",
            description = "the coefficient used to build the problem matrices"
            )

    iNVec: IntProperty(
            name = "eigenvalues",
            description = "number of eigenvalues calculated"
            )
    
    curr_eigmode: IntProperty(
            name = "eigenmode",
            description = "index of the current selected eigenmode",
            update = update_curr_eigmode,
            default = 0
            )

    lambda_damp: IntProperty(
            subtype = 'PERCENTAGE',
            name = "damping [%]",
            description = "damping factor of current eigenvalue [%]",
            min = 0,
            max = 100
            )

    lambda_freq: FloatProperty(
            name = "frequency [Hz]",
            description = "natural frequency of current eigenvalue [Hz]"
            )

    anim_scale: FloatProperty(
            name = "Scale factor",
            description = "scale factor for eigenmode visualization",
            default = 1.0
            )
    
    anim_frames: IntProperty(
            name = "Frames",
            description = "number of frames for eigenmode visualization",
            default = 48,
            min = 4
            )

# -----------------------------------------------------------
# end of BLENDYN_PG_eigenanalysis class
bpy.utils.register_class(BLENDYN_PG_eigenanalysis)

class BLENDYN_OT_eigen_geometry(bpy.types.Operator):
    """ Visualizes the reference geometry for the current eigensolution  """ 
    bl_idname = "blendyn._eigen_geometry"
    bl_label = "Visualize reference geometry for current eigensolution"

    def execute(self, context):
        mbs = context.scene.mbdyn
        nd = mbs.nodes
        ed = mbs.elems
        
        ncfile = os.path.join(os.path.dirname(mbs.file_path), \
                mbs.file_basename + '.nc')
        nc = Dataset(ncfile, "r")
        nctime = nc.variables["time"]
        eigsol = mbs.eigensolutions[mbs.curr_eigsol]

        anim_nodes = list()
        for node in nd:
            if node.blender_object != 'none':
                anim_nodes.append(node.name)

        if not(anim_nodes):
            message = "BLENDYN_OT_eigen_geometry::execute(): "\
                    + "Nodes not imported yet."
            self.report({'ERROR'}, message)
            logging.error(message)
            return {'CANCELLED'}
    
        for ndx in anim_nodes:
            dictobj = nd[ndx]
            obj = bpy.data.objects[dictobj.blender_object]
            obj.select_set(state = True)
            node_var = 'node.struct.' + str(nd[ndx].int_label) + '.'
           
            try:
                obj.location = Vector(( nc.variables[node_var + 'X'][eigsol.step - 1, :] ))
            except KeyError:
                message = "BLENDYN_OT_eigen_geometry::execute(): "\
                        + "Output for node " + str(nd[ndx].int_label) + " not found. "\
                        + "It will not be animated"
                self.report({'WARNING'}, message)
                logging.error(message)
                pass
            else:
                obj.keyframe_insert(data_path = "location")
   
                par = dictobj.parametrization 
                if par == 'PHI':
                    obj.rotation_mode = 'AXIS_ANGLE'
                    rotvec = Vector(( nc.variables[node_var + 'Phi'][eigsol.step - 1, :] ))
                    rotvec_norm = rotvec.normalized()
                    obj.rotation_axis_angle = Vector (( rotvec.magnitude, \
                            rotvec_norm[0], rotvec_norm[1], rotvec_norm[2] ))
                    obj.keyframe_insert(data_path = "rotation_axis_angle")
                elif par.startswith('EULER'):
                    eu_seq = axes[par[7]] +\
                             axes[par[6]] +\
                             axes[par[5]]
                    obj.rotation_mode = eu_seq
                    angles = math.radians(1.0)*(nc.variables[node_var + 'E'][eigsol.step - 1, :])
                    obj.rotation_euler = Euler(Vector ((\
                                         angles[int(par[5]) - 1],\
                                         angles[int(par[6]) - 1],\
                                         angles[int(par[7]) - 1],\
                                    )), eu_seq)
                    obj.keyframe_insert(data_path = "rotation_euler")
                elif par == 'MATRIX':
                    obj.rotation_mode = 'QUATERNION'
                    q = Matrix(( nc.variables[node_var + 'R'][eigsol.step - 1])).transposed().to_quaternion()
                    obj.rotation_quaternion = q
                    obj.keyframe_insert(data_path = "rotation_quaternion")
                else:
                    # Should not be reached
                    message = "BLENDYN_OT_eigen_geometry::execute(): "\
                            + "Unrecognised rotation parametrization"
                    self.report({'ERROR'}, message)
                    logging.error(message)
            
            obj.select_set(state = False)

        # Triggers the updte of deformable elements
        frame = bpy.context.scene.frame_current
        bpy.context.scene.frame_current = frame + 1
        bpy.context.scene.frame_current = frame
        return {'FINISHED'}
# -----------------------------------------------------------
# end of BLENDYN_OT__eigen_geometry class

class BLENDYN_OT_animate_eigenmode(bpy.types.Operator):
    """ Animates the model to show the currently selected eigenmode """
    bl_idname = "blendyn.animate_eigenmode"
    bl_label = "Visualize the currently selected eigenmode"

    def execute(self, context):
        mbs = context.scene.mbdyn
        nd = mbs.nodes
        ed = mbs.elems
        wm = context.window_manager
        
        ncfile = os.path.join(os.path.dirname(mbs.file_path), \
                mbs.file_basename + '.nc')
        nc = Dataset(ncfile, "r")
        nctime = nc.variables["time"]
        eigsol = mbs.eigensolutions[mbs.curr_eigsol]
        cem = mbs.eigensolutions[mbs.curr_eigsol].curr_eigmode
        
        message = "BLENDYN_OT_mbdyn_animate_eigenmode:execute(): "\
                + " animating mode " + str(cem)
        print(message)
        logging.info(message)

        if nc.variables["eig.idx"].ndim == 1:
            idx = nc.variables["eig.idx"][:]
            MAX_IDX = max(idx.data)
        elif nc.variables["eig.idx"].ndim == 2:
            # Legacy MBDyn NetCDF eigenanalysis output
            idx = nc.variables["eig.idx"][mbs.curr_eigsol, :]
            MAX_IDX = max(idx)
        else:
            raise TypeError("Blendyn::BLENDYN_OT_animate_eigenmode::execute() ERROR unsupported dimensions of eig.idx in NetCDF output")
        if all(idx < 0) or not(len(idx[~idx.mask])):
            message = "BLENDYN_OT_animate_eigenmode::execute(): eig.idx is empty."\
                    + " Activate \"output geometry\" in eigenanalysis card."
            self.report({'ERROR'}, message)
            logging.error(message)
            return {'CANCELLED'}
   
        try:
            eigvec_re = nc.variables["eig." + str(mbs.curr_eigsol) + ".VR"][0, cem - 1, :]
            eigvec_im = nc.variables["eig." + str(mbs.curr_eigsol) + ".VR"][1, cem - 1, :]
            eigvec_abs = (eigvec_re**2 + eigvec_im**2)**.5
            eigvec_abs = eigvec_abs/max(eigvec_abs[0:(MAX_IDX + 12)])
        except KeyError:
            message = "BLENDYN_OT_mbdyn_animate_eigenmode:execute(): "\
                    + "The eigenanalysis output is incomplete. Aborting."
            self.report({'ERROR'}, message)
            logging.error(message)
            return {'CANCELLED'}
        
        eigvec_phase = np.arctan2(eigvec_im, eigvec_re)
        
        scale = eigsol.anim_scale

        nodes = np.array(nc.variables["node.struct"])

        anim_nodes = list()
        for node in nd:
            if node.blender_object != 'none':
                anim_nodes.append(node.name)

        if not(anim_nodes):
            message = "BLENDYN_OT_mbdyn_animate_eigenmode:execute(): "\
                    + "Nodes not imported yet."
            self.report({'ERROR'}, message)
            logging.error(message)
            return {'CANCELLED'}
    
        wm.progress_begin(1, len(anim_nodes))
        init_frame = context.scene.frame_current

        kk = 0
        for ndx in anim_nodes:
            obj = bpy.data.objects[nd[ndx].blender_object]
            obj.select_set(state = True)
            obj.rotation_mode = 'AXIS_ANGLE'

            node_var = 'node.struct.' + str(nd[ndx].int_label) + '.'
            node_idx = idx[np.where(nodes == nd[ndx].int_label)[0][0]]

            if node_idx < 0:
                message = "BLENDYN_OT_mbdyn_animate_eigenmode:execute(): "\
                        + " skipped Object " + nd[ndx].blender_object \
                        + " with (dummy) node_idx = " + str(node_idx)
                logging.warning(message)
                print(message)
            else:
                message = "BLENDYN_OT_mbdyn_animate_eigenmode:execute(): "\
                        + " animating Object with node_idx = " + str(node_idx)
                logging.info(message)
                print(message)

                ref_pos = obj.location.copy()
                phi_tmp = Vector(( obj.rotation_axis_angle[0], \
                                obj.rotation_axis_angle[1], \
                                obj.rotation_axis_angle[2], \
                                obj.rotation_axis_angle[3] ))

                ref_phi = Vector(( phi_tmp[1:4] ))*phi_tmp[0]

                for frame in range(eigsol.anim_frames):
                    context.scene.frame_current = init_frame + frame
                    t = frame/eigsol.anim_frames
                
                    obj.location = ref_pos + \
                            Vector((
                                scale*eigvec_abs[node_idx]*math.cos(2*math.pi*t + \
                                        eigvec_phase[node_idx]),
                                scale*eigvec_abs[node_idx + 1]*math.cos(2*math.pi*t + \
                                        eigvec_phase[node_idx + 1]),
                                scale*eigvec_abs[node_idx + 2]*math.cos(2*math.pi*t + \
                                        eigvec_phase[node_idx + 2])
                                ))

                    obj.keyframe_insert(data_path = "location")

                    new_phi = ref_phi + \
                            Vector((
                                scale*eigvec_abs[node_idx + 3]*math.cos(2*math.pi*t + \
                                        eigvec_phase[node_idx + 3]),
                                scale*eigvec_abs[node_idx + 4]*math.cos(2*math.pi*t + \
                                        eigvec_phase[node_idx + 4]),
                                scale*eigvec_abs[node_idx + 5]*math.cos(2*math.pi*t + \
                                        eigvec_phase[node_idx + 5])
                                ))


                    new_phi_axis = new_phi.normalized()
                    obj.rotation_axis_angle = \
                        Vector(( 
                            new_phi.magnitude, \
                            new_phi_axis[0],
                            new_phi_axis[1],
                            new_phi_axis[2]
                            ))

                    obj.keyframe_insert(data_path = "rotation_axis_angle")
           
                obj.select_set(state = False)
                kk = kk + 1
                wm.progress_update(kk)
        wm.progress_end()
        return {'FINISHED'}
# -----------------------------------------------------------
# end of BLENDYN_OT_animate_eigenmode class

