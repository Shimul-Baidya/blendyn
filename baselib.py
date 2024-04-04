# --------------------------------------------------------------------------
# Blendyn -- file baselib.py
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
#    Blendyn  is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with Blendyn.  If not, see <http://www.gnu.org/licenses/>.
#
# ***** END GPL LICENCE BLOCK *****
# --------------------------------------------------------------------------

from mathutils import *
from math import *

import bpy
from bpy.props import *

import logging

import numpy as np

import os, csv, atexit, re

from .nodelib import *
from .elementlib import *
from .rfmlib import *
from .componentlib import DEFORMABLE_ELEMENTS
from .logwatcher import *
from .stresslib import *


HAVE_PSUTIL = False
try:
    import psutil
    HAVE_PSUTIL = True
except ImportError:
    pass

try:
    from netCDF4 import Dataset
except ImportError:
    message = "BLENDYN: could not find netCDF4 module. NetCDF import "\
            + "will be disabled."
    print(message)
    logging.warning(message)
    pass

def parse_input_file(context):
    mbs = context.scene.mbdyn

    out_file = mbs.input_path

    with open(out_file) as of:
        reader = csv.reader(of, delimiter=' ', skipinitialspace=True)

        while True:
            rw = next(reader)
            print(rw)
            if rw:
                first = rw[0].strip()

            if first == 'final':
                time = rw[2]

                try:
                    time = float(time[:-1])

                except ValueError:
                    mbs.final_time = mbs.ui_time
                    break

                mbs.final_time = time
                mbs.ui_time = time

                break

if HAVE_PSUTIL:
    def kill_mbdyn():
        mbdynProc = [var for var in psutil.process_iter() if var.name() == 'mbdyn']

        if mbdynProc:
            mbdynProc[0].kill()

def get_plot_vars_glob(context):
    mbs = context.scene.mbdyn
    if mbs.use_netcdf:
        ncfile = os.path.join(os.path.dirname(mbs.file_path), \
                mbs.file_basename + '.nc')
        nc = Dataset(ncfile, 'r')
        N = len(nc.variables["time"])

        var_list = list()
        for var in nc.variables:
            m = nc.variables[var].shape
            if (m[0] == N) and (var not in mbs.plot_vars.keys()):
                plotvar = mbs.plot_vars.add()
                plotvar.name = var

def get_plot_engine():
    HAVE_MATPLOTLIB = True
    HAVE_PYGAL = True
    HAVE_BOKEH = True
    try:
        import matplotlib
    except ImportError:
        HAVE_MATPLOTLIB = False
    try:
        import pygal
    except ImportError:
        HAVE_PYGAL = False
    try:
        import bokeh
    except ImportError:
        HAVE_BOKEH = False
    is_have_engine = [HAVE_PYGAL, HAVE_MATPLOTLIB, HAVE_BOKEH]
    plot_engines = [("PYGAL", "Pygal", "Pygal", '', 2), \
                    ("MATPLOTLIB", "Matplotlib", "Matplotlib", '', 1), \
                    ("BOKEH", "Bokeh", "bokeh", '', 3)]
    return [plot_engines[i] for i in range(len(is_have_engine)) if is_have_engine[i]]



def update_driver_variables(self, context):
    mbs = bpy.context.scene.mbdyn
    pvar = mbs.plot_vars[mbs.plot_var_index]

    if pvar.as_driver:
        dvar = mbs.driver_vars.add()
        dvar.name = pvar.name
        dvar.variable = pvar.name
        dvar.components = pvar.plot_comps
    else:
        idx = [idx for idx in range(len(mbs.driver_vars)) if mbs.driver_vars[idx].name == pvar.name]
        mbs.driver_vars.remove(idx[0])

## Function that sets up the data for the import process
def setup_import(filepath, context):
    mbs = context.scene.mbdyn
    mbs.file_path, mbs.file_basename = path_leaf(filepath)
    if filepath[-2:] == 'nc':
        nc = Dataset(filepath, "r")
        mbs.use_netcdf = True
        mbs.num_rows = 0
        mbs.num_nodes = nc.dimensions['struct_node_labels_dim'].size
        mbs.num_timesteps = nc.dimensions['time'].size
        try:
            NVecs = [dim for dim in nc.dimensions if 'iNVec_out' in dim]
            for ii in range(0, len(NVecs)):
                eigsol = mbs.eigensolutions.add()
                eigsol.index = int(NVecs[ii][4:-10])
                eigsol.step = nc.variables['eig.' + str(ii) + '.step'][0]
                eigsol.time = nc.variables['eig.' + str(ii) + '.time'][0]
                eigsol.dCoef = nc.variables['eig.' + str(ii) + '.dCoef'][0]
                eigsol.iNVec = nc.dimensions[NVecs[ii]].size
                eigsol.curr_eigmode = 1
        except KeyError as err:
            message = 'BLENDYN::setup_import(): ' + \
                    'no valid eigenanalysis results found'
            print(message)
            logging.info(message)
            pass
        # by default, we remove the log files on exit
        atexit.register(delete_log)
        get_plot_vars_glob(context)
    else:
        mbs.use_netcdf = False
        mbs.num_rows = file_len(filepath)
        if mbs.num_rows < 0:
            return {'FILE_ERROR'}
    return {'FINISHED'}

# -----------------------------------------------------------
# end of setup_import() function

def number_modal_modes(context):
    """Check for total modal modes in .mod file"""
    mbs = context.scene.mbdyn
    if os.path.isfile(os.path.join(os.path.dirname(mbs.file_path), mbs.file_basename + '.mod')):
        mod_file = os.path.join(os.path.dirname(mbs.file_path), mbs.file_basename + '.mod')
        with open(mod_file) as mdf:
            reader_mod = csv.reader(mdf, delimiter = ' ', skipinitialspace = True)
            rw_mod = next(reader_mod)
            first_mode = rw_mod[0]
            num_modal_modes = 0
            while True:
                num_modal_modes += 1
                try:
                    rw_mod = next(reader_mod)
                except StopIteration:
                    break
                mode = rw_mod[0]
                if mode == first_mode:
                    break
        mbs.num_modal_modes = num_modal_modes
    else:
        mbs.num_modal_modes = 0
        pass
#---------------------------------------------------------------
# end of number_modal_modes() function

def no_output(context):
    """Check for nodes with no output"""
    mbs = context.scene.mbdyn
    nd = mbs.nodes

    if mbs.use_netcdf:
        ncfile = os.path.join(os.path.dirname(mbs.file_path), \
                mbs.file_basename + '.nc')
        nc = Dataset(ncfile, "r")
        log_nodes = list(map(lambda x: int(x[5:]), nd.keys()))
        for node in log_nodes:
            try:
                X = nc.variables['node.struct.' + str(node) + '.X']
                nd['node_' + str(node)].output = True
            except KeyError:
                # output disabled for this node
                pass
    else:
        # .mov filename
        mov_file = os.path.join(os.path.dirname(mbs.file_path), \
                mbs.file_basename + '.mov')
        try:
            with open(mov_file) as mf:
                reader = csv.reader(mf, delimiter = ' ', skipinitialspace = True)
                rw = next(reader)
                first_node = int(rw[0])
                num_nodes = 0
                while True:
                    node = [node for node in nd if node.int_label == int(rw[0])]
                    num_nodes += 1
                    if node:
                        node[0].output = True
                    rw = next(reader)
                    if int(rw[0]) == first_node:
                        break
                mbs.num_nodes = num_nodes
        except StopIteration: # EOF
            pass

# -----------------------------------------------------------
# end of no_output() function

def parse_log_file(context):
    """ Parses the .log file and calls parse_elements() to add elements 
        to the elements dictionary and parse_node() to add nodes to 
        the nodes dictionary """
    # utility rename
    mbs = context.scene.mbdyn
    nd = mbs.nodes
    ed = mbs.elems
    rd = mbs.references

    is_init_nd = len(nd) == 0
    is_init_ed = len(ed) == 0

    for node_name in nd.keys():
        nd[node_name].is_imported = False

    for elem_name in ed.keys():
        ed[elem_name].is_imported = False

    log_file = os.path.join(os.path.dirname(mbs.file_path), \
            mbs.file_basename + '.log')

    out_file = os.path.join(os.path.dirname(mbs.file_path), \
            mbs.file_basename + '.out')

    rfm_file = os.path.join(os.path.dirname(mbs.file_path), \
            mbs.file_basename + '.rfm')

    # Debug message to console
    print("Blendyn::parse_log_file(): Trying to read nodes and elements from file: "\
            + log_file)

    ret_val = {''}

    # Check if collections are already present (not the first import).
    # if not, create them

    try:
        ncol = bpy.data.collections['mbdyn.nodes']
    except KeyError:
        ncol = bpy.data.collections.new(name = 'mbdyn.nodes')
        bpy.context.scene.collection.children.link(ncol)

    try:
        ecol = bpy.data.collections['mbdyn.elements']
    except KeyError:
        ecol = bpy.data.collections.new(name = 'mbdyn.elements')
        bpy.context.scene.collection.children.link(ecol)

    # create elements children collections if they are not already there
    try:
        aecol = ecol.children['aerodynamic']
    except KeyError:
        aecol = bpy.data.collections.new(name = 'aerodynamic')
        ecol.children.link(aecol)

    try:
        becol = ecol.children['beams']
    except KeyError:
        becol = bpy.data.collections.new(name = 'beams')
        ecol.children.link(becol)

    # elements sections sub-collection
    try:
        scol = ecol.children['sections']
    except KeyError:
        scol = bpy.data.collections.new(name = 'sections')
        ecol.children.link(scol)

    try:
        bocol = ecol.children['bodies']
    except KeyError:
        bocol = bpy.data.collections.new(name = 'bodies')
        ecol.children.link(bocol)

    try:
        fcol = ecol.children['forces']
    except KeyError:
        fcol = bpy.data.collections.new(name = 'forces')
        ecol.children.link(fcol)

    try:
        jcol = ecol.children['joints']
    except KeyError:
        jcol = bpy.data.collections.new(name = 'joints')
        ecol.children.link(jcol)

    try:
        pcol = ecol.children['plates']
    except KeyError:
        pcol = bpy.data.collections.new(name = 'plates')
        ecol.children.link(pcol)

    try:
        with open(log_file) as lf:
            # open the reader, skipping initial whitespaces
            b_nodes_consistent = True
            b_elems_consistent = True
            reader = csv.reader(lf, delimiter=' ', skipinitialspace=True)

            entry = ""
            while entry[:-1] != "Symbol table":
                # get the next row
                rw = next(reader)

                entry = rw[0]
                ii = 0

                while (rw[ii][-1] != ':') and (ii < min(3, (len(rw) - 1))):
                    ii = ii + 1
                    entry = entry + " " + rw[ii]

                if ii == min(3, (len(rw) - 1)):
                    print("Blendyn::parse_log_file(): row does not contain an element definition. Skipping...")
                elif entry == "structural node:":
                    print("Blendyn::parse_log_file(): Found a structural node.")
                    b_nodes_consistent = b_nodes_consistent * (parse_node(context, rw))
                else:
                    print("Blendyn::parse_log_file(): Found " + entry[:-1] + " element.")
                    b_elems_consistent = b_elems_consistent * parse_elements(context, entry[:-1], rw)


            if (is_init_nd and is_init_ed) or (b_nodes_consistent*b_elems_consistent):
                ret_val = {'FINISHED'}
            elif (not(b_nodes_consistent) and not(is_init_nd)) and (not(b_elems_consistent) and not(is_init_ed)):
                ret_val = {'MODEL_INCONSISTENT'}
            elif (not(b_nodes_consistent) and not(is_init_nd)) and (b_elems_consistent):
                ret_val = {'NODES_INCONSISTENT'}
            elif (b_nodes_consistent) and (not(b_elems_consistent) and not(is_init_ed)):
                ret_val = {'ELEMS_INCONSISTENT'}
            else:
                ret_val = {'FINISHED'}

    except IOError:
        print("Blendyn::parse_log_file(): Could not locate the file " + log_file + ".")
        ret_val = {'LOG_NOT_FOUND'}
        pass
    except StopIteration:
        print("Blendyn::parse_log_file() Reached the end of .log file")
        pass
    except TypeError:       
        # TypeError will be thrown if parse node exits with a {}, indicating an
        # unsupported rotation parametrization (e.g. euler313)
        ret_val = {'ROTATION_ERROR'}
        pass


    del_nodes = [var for var in nd.keys() if nd[var].is_imported == False]
    del_elems = [var for var in ed.keys() if ed[var].is_imported == False]

    obj_names = [nd[var].blender_object for var in del_nodes]
    obj_names += [ed[var].blender_object for var in del_elems]

    obj_names = list(filter(None, obj_names))

    nn = len(nd)

    # Account for nodes with no output
    if nn:
        no_output(context)
        mbs.min_node_import = nd[0].int_label
        mbs.max_node_import = nd[0].int_label

        for ndx in range(1, len(nd)):
            if nd[ndx].int_label < mbs.min_node_import:
                mbs.min_node_import = nd[ndx].int_label
            elif nd[ndx].int_label > mbs.max_node_import:
                mbs.max_node_import = nd[ndx].int_label

        if mbs.use_netcdf:
            ncfile = os.path.join(os.path.dirname(mbs.file_path), \
                    mbs.file_basename + '.nc')
            nc = Dataset(ncfile, "r")
            mbs.num_timesteps = len(nc.variables["time"])
        else:
            mbs.num_nodes = nn
            mbs.num_timesteps = int(mbs.num_rows/mbs.num_nodes)
        
        mbs.is_ready = True
        ret_val = {'FINISHED'}
    else:
        ret_val = {'NODES_NOT_FOUND'}
    pass

    en = len(ed)
    if en:
        mbs.min_elem_import = ed[0].int_label
        mbs.max_elem_import = ed[0].int_label
        for edx in range(1, len(ed)):
            if ed[edx].int_label < mbs.min_elem_import:
                mbs.min_elem_import = ed[edx].int_label
            elif ed[edx].int_label > mbs.max_elem_import:
                mbs.max_elem_import = ed[edx].int_label

    try:
        with open(out_file) as of:
            reader = csv.reader(of, delimiter = ' ', skipinitialspace = True)
            while True:
                if next(reader)[0] == 'Step':
                  mbs.time_step = float(next(reader)[3])
                  if (mbs.use_netcdf):
                      mbs.end_time = nc.variables["time"][-1]
                      mbs.start_time = nc.variables["time"][0]
                  break
    except FileNotFoundError:
        print("Blendyn::parse_log_file(): Could not locate the file " + out_file)
        ret_val = {'OUT_NOT_FOUND'}
        pass
    except StopIteration:
        print("Blendyn::parse_log_file(): Reached the end of .out file")
        pass
    except IOError:
        print("Blendyn::parse_log_file(): Could not read the file " + out_file)
        pass

    try:
        with open(rfm_file) as rfm:
            reader = csv.reader(rfm, delimiter = ' ', skipinitialspace = True)
            for rfm_row in reader:
                if len(rfm_row) and rfm_row[0].strip() != '#':
                        parse_reference_frame(rfm_row, rd)

        # create the reference frames collection if it is not already there
        try:
            rcol = bpy.data.collections['mbdyn.references']
        except KeyError:
            rcol = bpy.data.collections.new(name = 'mbdyn.references')
            bpy.context.scene.collection.children.link(rcol)

    except StopIteration:
        pass
    except FileNotFoundError:
        print("Blendyn::parse_out_file(): Could not locate the file " + rfm_file)
        pass
    except IOError:
        print("Blendyn::parse_out_file(): Could not read the file " + rfm_file)
        pass

    if not(mbs.use_netcdf):
        mbs.end_time = (mbs.num_timesteps - 1) * mbs.time_step

    return ret_val, obj_names
# -----------------------------------------------------------
# end of parse_log_file() function

def path_leaf(path, keep_extension = False):
    """ Helper function to strip filename of path """
    head, tail = ntpath.split(path)
    tail1 = (tail or ntpath.basename(head))
    if keep_extension:
        return path.replace(tail1, ''), tail1
    else:
        return path.replace(tail1, ''), os.path.splitext(tail1)[0]
# -----------------------------------------------------------
# end of path_leaf() function

def file_len(filepath):
    """ Function to count the number of rows in a file """
    try:
        with open(filepath) as f:
            for kk, ll in enumerate(f):
                pass
        return kk + 1
    except UnboundLocalError:
        return 0
    except IsADirectoryError:
        return 0
# -----------------------------------------------------------
# end of file_len() function

def assign_labels(context):
    """ Function that parses the .log file and assigns \
        the string labels it can find to the respective MBDyn objects
        -- 
         'standard' labels: assigns only the labels that match a
                            specific pattern
         'free' labels: assigns the labels directly.
                        contributed by Louis Gagnon 
                        -- see Github Issue #39
        --
    """

    mbs = context.scene.mbdyn
    nd = mbs.nodes
    ed = mbs.elems
    rd = mbs.references

    labels_changed = False

    log_file = os.path.join(os.path.dirname(mbs.file_path), \
            mbs.file_basename + '.log')

    if mbs.free_labels:
        obj_list = [nd, ed, rd]
        set_strings_any = ["  const integer", \
                           "  integer"]
    else:
        set_strings_node = ["  const integer Node_", \
                            "  integer Node_", \
                            "  const integer node_", \
                            "  integer node_", \
                            "  const integer NODE_", \
                            "  integer NODE_"]
    
        set_strings_joint = ["  const integer Joint_", \
                             "  integer Joint_"
                             "  const integer joint_", \
                             "  integer joint_", \
                             "  const integer JOINT_", \
                             "  integer JOINT_"]
    
        set_strings_beam = ["  const integer Beam_", \
                            "  integer Beam_", \
                            "  const integer beam_", \
                            "  integer beam_", \
                            "  const integer BEAM_", \
                            "  integer BEAM_"]
    
        set_strings_refs = ["  const integer Ref_", \
                            "  integer Ref_", \
                            "  const integer ref_", \
                            "  integer ref_", \
                            "  const integer REF_", \
                            "  integer REF_", \
                            "  const integer Reference_", \
                            "  integer Reference_", \
                            "  const integer reference_", \
                            "  integer reference_", \
                            "  const integer REFERENCE_", \
                            "  integer REFERENCE_"]

    def assign_label(line, entity_type, set_string, the_dict):
        line_str = line.rstrip()
        eq_idx = line_str.find('=') + 1
        label_int = int(line_str[eq_idx:].strip())
        if mbs.free_labels:
            label_str = line_str[len(set_string):(eq_idx -1)].strip()
        else:
            label_str = line_str[(len(set_string) - len(entity_type) - 1):(eq_idx-1)].strip()
         
        for item in the_dict:
            if item.int_label == label_int:
                if item.string_label != label_str:
                    item.string_label = label_str
                    message = "BLENDYN::assign_label(): \nset_string:{}\nline_str:{}\nlabel_str:{}".format(set_string, line_str, label_str)
                    print(message)
                    baseLogger.info(message)
                    return True
                break
        return False

    try:
        if mbs.free_labels:
            with open(log_file) as lf:
                for line in lf:
                    found = False
                    for set_string in set_strings_any:
                        if set_string in line:
                            for the_obj in obj_list:
                                labels_changed += (assign_label(line, '', set_string, the_obj))
                            found = True
                            break
        else:
            with open(log_file) as lf:
                for line in lf:
                    found = False
                    for set_string in set_strings_node:
                        if set_string in line:
                            labels_changed += (assign_label(line, 'node', set_string, nd))
                            found = True
                            break
                    if not(found):
                        for set_string in set_strings_joint:
                            if set_string in line:
                                labels_changed += (assign_label(line, 'joint', set_string, ed))
                                found = True
                                break
                    if not(found):
                        for set_string in set_strings_beam:
                            if set_string in line:
                                labels_changed += (assign_label(line, 'beam', set_string, ed))
                                found = True
                                break
                    if not (found):
                        for set_string in set_strings_refs:
                            if set_string in line:
                                labels_changed += (assign_label(line, 'ref', set_string, rd))
                                found = True
                                break
    except IOError:
        print("Blendyn::assign_labels(): can't read from file {}, \
                sticking with default labeling...".format(log_file))
        return {'FILE_NOT_FOUND'}

    if labels_changed:
        return {'LABELS_UPDATED'}
    else:
        return {'NOTHING_DONE'}
# -----------------------------------------------------------
# end of assign_labels() function


def update_label(self, context):
    # utility renaming
    obj = context.view_layer.objects.active
    nd = context.scene.mbdyn.nodes

    # Search for int label and assign corresponding string label, if found.
    # If not, signal it by assign the "not found" label
    node_string_label = "not_found"
    obj.mbdyn.is_assigned = False
    if obj.mbdyn.type == 'node.struct':
        try:
            key = 'node_' + str(obj.mbdyn.int_label)
            node_string_label = nd[key].string_label
            nd[key].blender_object = obj.name
            obj.mbdyn.is_assigned = True
            obj.mbdyn.string_label = node_string_label

            ret_val = {}
            if obj.mbdyn.is_assigned:
                ret_val = update_parametrization(obj)

            if ret_val == 'ROT_NOT_SUPPORTED':
                message = type(self).__name__ + "::update_label(): "\
                        + "Rotation parametrization not supported, node " \
                        + obj.mbdyn.string_label
                self.report({'ERROR'}, message)
                logging.error(message)

            elif ret_val == 'LOG_NOT_FOUND':
                message = type(self).__name__ + "::update_label(): "\
                        + "MBDyn .log file not found"
                self.report({'ERROR'}, message)
                logging.error(message)

        except KeyError:
            message = type(self).__name__ + "::update_label(): "\
                    + "Node not found"
            self.report({'ERROR'}, message)
            logging.error(message)
            pass
    return
# -----------------------------------------------------------
# end of update_label() function

def update_end_time(self, context):
    mbs = context.scene.mbdyn

    if mbs.use_netcdf:
        ncfile = os.path.join(os.path.dirname(mbs.file_path), \
                    mbs.file_basename + '.nc')
        nc = Dataset(ncfile, "r")
        if (mbs.end_time - nc.variables["time"][-1]) > mbs.time_step:
            mbs.end_time = nc.variables["time"][-1]
    elif mbs.end_time > mbs.num_timesteps * mbs.time_step:
        mbs.end_time = mbs.num_timesteps * mbs.time_step
# -----------------------------------------------------------
# end of update_end_time() function

def update_start_time(self, context):
    mbs = context.scene.mbdyn

    if mbs.use_netcdf:
        ncfile = os.path.join(os.path.dirname(mbs.file_path), \
                    mbs.file_basename + '.nc')
        nc = Dataset(ncfile, "r")
        if mbs.start_time < nc.variables["time"][0]:
            mbs.start_time = nc.variables["time"][0]
    elif mbs.start_time >= mbs.num_timesteps * mbs.time_step:
        mbs.start_time = (mbs.num_timesteps - 1) * mbs.time_step
# -----------------------------------------------------------
# end of update_start_time() function

def remove_oldframes(context):
    """ Clears the scene of keyframes of current simulation """
    mbs = context.scene.mbdyn

    node_names = mbs.nodes.keys()
    obj_names = [bpy.context.scene.mbdyn.nodes[var].blender_object for var in node_names]

    obj_names = list(filter(lambda v: v != 'none', obj_names))
    obj_names = list(filter(lambda v: v in bpy.data.objects.keys(), obj_names))

    if len(obj_names) > 0:
       obj_list = [bpy.data.objects[var] for var in obj_names]
       for obj in obj_list:
           obj.animation_data_clear()
# -----------------------------------------------------------
# end of remove_oldframes() function

def hide_or_delete(obj_names, missing):
    obj_names = list(filter(lambda v: v != 'none', obj_names))
    obj_list = [bpy.data.objects[var] for var in obj_names]

    if missing == "HIDE":
        obj_list = [bpy.data.objects[var] for var in obj_names]

        for obj in obj_list:
            obj.hide_set(state = True)

    if missing == "DELETE":
        bpy.ops.object.select_all(action='DESELECT')
        for obj in obj_list:
            obj.select_set(state = True)
            bpy.ops.object.delete()

def set_motion_paths_mov(context):
    """ Parses the .mov file and .mod file then sets the nodes motion paths """
    # Debug message
    print("Blendyn::set_motion_paths_mov(): Setting Motion Paths using .mov output...")

    # utility renaming
    scene = context.scene
    mbs = scene.mbdyn
    nd = mbs.nodes
    ed = mbs.elems

    wm = context.window_manager

    if not(mbs.is_ready):
        return {'CANCELLED'}

    # .mov filename
    mov_file = os.path.join(os.path.dirname(mbs.file_path), \
            mbs.file_basename + '.mov')

    have_mod_file = True
    if os.path.isfile(os.path.join(os.path.dirname(mbs.file_path), \
                            mbs.file_basename + '.mod')):
        mod_file = os.path.join(os.path.dirname(mbs.file_path), \
                                mbs.file_basename + '.mod')
    else:
        have_mod_file = False

    # Debug message
    if have_mod_file:
        print("Blendyn::set_motion_paths_mov(): Reading from file: {0} and {1}".format(mov_file, mod_file))
    else:
        print("Blendyn::set_motion_paths_mov(): Reading from file: {0}".format(mov_file))

    # total number of frames to be animated
    scene.frame_start = int(mbs.start_time/(mbs.time_step * mbs.load_frequency))
    scene.frame_end = int(mbs.end_time/(mbs.time_step * mbs.load_frequency)) + 1

    loop_start = int(scene.frame_start * mbs.load_frequency)
    loop_end = int(scene.frame_end * mbs.load_frequency)

    # list of animatable Blender object types
    anim_types = ['MESH', 'ARMATURE', 'EMPTY']

    # Cycle to establish which objects to animate
    anim_objs = dict()
    wm.progress_begin(scene.frame_start, scene.frame_end)
    if have_mod_file:
        try:
            with open(mod_file) as mdf:
                with open(mov_file) as mvf :
                    reader_mov = csv.reader(mvf, delimiter=' ', skipinitialspace=True)
                    reader_mod = csv.reader(mdf, delimiter=' ', skipinitialspace=True)
                    # first loop: we establish which object to animate
                    scene.frame_current = scene.frame_start

                    # skip to the first timestep to import
                    for ndx in range(int(mbs.start_time * mbs.num_nodes / mbs.time_step)):
                        next(reader_mov)

                    for ndx in range(int(mbs.start_time * mbs.num_modal_modes / mbs.time_step)):
                        next(reader_mod)

                    first_mov = []
                    second_mov = []
                    for ndx in range(mbs.num_nodes):
                        rw_mov = np.array(next(reader_mov)).astype(np.float)
                        first_mov.append(rw_mov)
                        second_mov.append(rw_mov)

                        try:
                            obj_name = nd['node_' + str(int(rw_mov[0]))].blender_object

                            if obj_name != 'none' and nd['node_' + str(int(rw_mov[0]))].output:
                                anim_objs[rw_mov[0]] = obj_name
                                obj = bpy.data.objects[obj_name]
                                obj.select_set(state = True)
                                set_obj_locrot_mov(obj, rw_mov)
                        except KeyError:
                            pass
                    dg = bpy.context.evaluated_depsgraph_get()
                    dg.update()

                    # Initial position of modal nodes
                    first_mod = []
                    second_mod = []
                    flag = False  # Whether we set up the node positions in the space
                    mode_counter = 0

                    for mdx in range(mbs.num_modal_modes):
                        mode_counter += 1
                        rw_mod = np.array(next(reader_mod)).astype(np.float)
                        first_mod.append(rw_mod)
                        second_mod.append(rw_mod)
                        elem_int_label, mode_int_label = str(rw_mod[0]).split('.')
                        elem = ed['modal_'+ elem_int_label]
                        elem_node = nd['node_'+ str(elem.nodes[0].int_label)]
                        elem_nodeOJB = bpy.data.objects[elem_node.blender_object]
                        for node in elem.modal_node:
                            try:
                                obj_name = node.blender_object
                                if obj_name != 'none':
                                    obj = bpy.data.objects[obj_name]
                                    obj.select_set(state=True)
                                    if not flag:
                                        obj.location = elem_nodeOJB.matrix_world @ Vector(
                                            (node.relative_pos[0] + rw_mod[1] * node.mode[mode_int_label].mode_shape[0],
                                             node.relative_pos[1] + rw_mod[1] * node.mode[mode_int_label].mode_shape[1],
                                             node.relative_pos[2] + rw_mod[1] * node.mode[mode_int_label].mode_shape[2],
                                             1)).to_3d()
                                    else:
                                        obj.location += elem_nodeOJB.matrix_world @ Vector(
                                            (rw_mod[1] * node.mode[mode_int_label].mode_shape[0],
                                             rw_mod[1] * node.mode[mode_int_label].mode_shape[1],
                                             rw_mod[1] * node.mode[mode_int_label].mode_shape[2],
                                             1)).to_3d() - elem_nodeOJB.location
                                    try:
                                        if mode_counter == len(elem.modal_node[0].mode):
                                            obj.keyframe_insert(data_path="location")
                                        obj.rotation_euler = elem_nodeOJB.rotation_euler
                                        obj.keyframe_insert(data_path="rotation_euler")
                                    except KeyError:
                                        pass
                            except KeyError:
                                pass
                        if not flag:
                            flag = True
                        try:
                            if mode_counter == len(elem.modal_node[0].mode):
                                mode_counter = 0
                                flag = False
                        except KeyError:
                            pass
                    # main for loop, from second frame to last
                    freq = mbs.load_frequency
                    Nskip_mov = 0
                    Nskip_mod = 0

                    for idx, frame in enumerate(np.arange(loop_start + freq, loop_end, freq)):
                        scene.frame_current += 1
                        message = "BLENDYN::set_motion_paths_mov(): Animating frame {}".format(scene.frame_current)
                        print(message)
                        logging.info(message)

                        # skip (freq - 1)*N lines
                        if freq > 1:
                            Nskip_mov = (int(frame) - int(frame - freq) - 2) * mbs.num_nodes
                            Nskip_mod = (int(frame) - int(frame - freq) - 2) * mbs.num_modal_modes

                        if Nskip_mov >= 0:
                            for ii in range(Nskip_mov):
                                next(reader_mov)
                            for ndx in range(mbs.num_nodes):
                                first_mov[ndx] = np.array(next(reader_mov)).astype(np.float)
                        if Nskip_mod >= 0:
                            for ii in range(Nskip_mod):
                                next(reader_mod)
                            for ndx in range(mbs.num_modal_modes):
                                first_mod[ndx] = np.array(next(reader_mod)).astype(np.float)

                        if freq > 1:
                            frac = np.ceil(frame) - frame
                            for ndx in range(mbs.num_nodes):
                                second_mov[ndx] = np.array(next(reader_mov)).astype(np.float)
                            for ndx in range(mbs.num_modal_modes):
                                second_mod[ndx] = np.array(next(reader_mod)).astype(np.float)

                            for ndx in range(mbs.num_nodes):
                                try:
                                    answer = frac*first_mov[ndx] + (1 - frac)*second_mov[ndx]
                                    obj = bpy.data.objects[anim_objs[round(answer[0])]]
                                    obj.select_set(state = True)
                                    set_obj_locrot_mov(obj, answer)
                                except KeyError:
                                    pass
                            dg = bpy.context.evaluated_depsgraph_get()
                            dg.update()

                            flag = False  # Whether we set up the node positions in the space
                            mode_counter = 0
                            for mdx in range(mbs.num_modal_modes):
                                mode_counter += 1
                                elem_int_label, mode_int_label = str(first_mod[mdx][0]).split('.')
                                elem = ed['modal_' + elem_int_label]
                                elem_node = nd['node_' + str(elem.nodes[0].int_label)]
                                elem_nodeOJB =  bpy.data.objects[elem_node.blender_object]
                                answer = frac * first_mod[mdx] + (1 - frac) * second_mod[mdx]
                                for node in elem.modal_node:
                                    try:
                                        obj_name = node.blender_object
                                        if obj_name != 'none':
                                            obj = bpy.data.objects[obj_name]
                                            obj.select_set(state=True)
                                            if not flag:
                                                obj.location = elem_nodeOJB.matrix_world @ Vector(
                                                    (node.relative_pos[0] + answer[1] *
                                                     node.mode[mode_int_label].mode_shape[0],
                                                     node.relative_pos[1] + answer[1] *
                                                     node.mode[mode_int_label].mode_shape[1],
                                                     node.relative_pos[2] + answer[1] *
                                                     node.mode[mode_int_label].mode_shape[2], 1)).to_3d()
                                            else:
                                                obj.location += elem_nodeOJB.matrix_world @ Vector(
                                                    (answer[1] * node.mode[mode_int_label].mode_shape[0],
                                                     answer[1] * node.mode[mode_int_label].mode_shape[1],
                                                     answer[1] * node.mode[mode_int_label].mode_shape[2],
                                                     1)).to_3d() - elem_nodeOJB.location
                                            try:
                                                if mode_counter == len(elem.modal_node[0].mode):
                                                    obj.keyframe_insert(data_path="location")
                                                obj.rotation_euler = elem_nodeOJB.rotation_euler
                                                obj.keyframe_insert(data_path="rotation_euler")
                                            except KeyError:
                                                pass
                                    except KeyError:
                                        pass
                                if not flag:
                                    flag = True
                                try:
                                    if mode_counter == len(elem.modal_node[0].mode):
                                        mode_counter = 0
                                        flag = False
                                except KeyError:
                                    pass

                            first_mod = second_mod
                            first_mov = second_mov
                        else:
                            for ndx in range(mbs.num_nodes):
                                rw_mov = first_mov[ndx]
                                obj = bpy.data.objects[anim_objs[round(rw_mov[0])]]
                                obj.select_set(state = True)
                                set_obj_locrot_mov(obj, rw_mov)
                            dg = bpy.context.evaluated_depsgraph_get()
                            dg.update()

                            flag = False  # Whether we set up the node positions in the space
                            mode_counter = 0
                            for mdx in range(mbs.num_modal_modes):
                                mode_counter += 1
                                rw_mod = first_mod[mdx]
                                elem_int_label, mode_int_label = str(rw_mod[0]).split('.')
                                elem = ed['modal_' + elem_int_label]
                                elem_node = nd['node_' + str(elem.nodes[0].int_label)]
                                elem_nodeOJB = bpy.data.objects[elem_node.blender_object]
                                for node in elem.modal_node:
                                    try:
                                        obj_name = node.blender_object
                                        if obj_name != 'none':
                                            obj = bpy.data.objects[obj_name]
                                            obj.select_set(state=True)
                                            if not flag:
                                                obj.location = elem_nodeOJB.matrix_world @ Vector(
                                                    (node.relative_pos[0] + rw_mod[1] *
                                                     node.mode[mode_int_label].mode_shape[0],
                                                     node.relative_pos[1] + rw_mod[1] *
                                                     node.mode[mode_int_label].mode_shape[1],
                                                     node.relative_pos[2] + rw_mod[1] *
                                                     node.mode[mode_int_label].mode_shape[2], 1)).to_3d()
                                            else:
                                                obj.location += elem_nodeOJB.matrix_world @ Vector(
                                                    (rw_mod[1] * node.mode[mode_int_label].mode_shape[0],
                                                     rw_mod[1] * node.mode[mode_int_label].mode_shape[1],
                                                     rw_mod[1] * node.mode[mode_int_label].mode_shape[2],
                                                     1)).to_3d() - elem_nodeOJB.location
                                            try:
                                                if mode_counter == len(elem.modal_node[0].mode):
                                                    obj.keyframe_insert(data_path="location")
                                                obj.rotation_euler = elem_nodeOJB.rotation_euler
                                                obj.keyframe_insert(data_path="rotation_euler")
                                            except KeyError:
                                                pass
                                    except KeyError:
                                        pass
                                if not flag:
                                    flag = True
                                try:
                                    if mode_counter == len(elem.modal_node[0].mode):
                                        mode_counter = 0
                                        flag = False
                                except KeyError:
                                    pass
                        wm.progress_update(scene.frame_current)

        except IOError:
            pass
    else:
        try:
            with open(mov_file) as mvf:
                reader_mov = csv.reader(mvf, delimiter=' ', skipinitialspace=True)
                # first loop: we establish which object to animate
                scene.frame_current = scene.frame_start

                # skip to the first timestep to import
                for ndx in range(int(mbs.start_time * mbs.num_nodes / mbs.time_step)):
                    next(reader_mov)

                first_mov = []
                second_mov = []
                for ndx in range(mbs.num_nodes):
                    rw_mov = np.array(next(reader_mov)).astype(np.float)
                    first_mov.append(rw_mov)
                    second_mov.append(rw_mov)
                    try:
                        obj_name = nd['node_' + str(int(rw_mov[0]))].blender_object

                        if obj_name != 'none' and nd['node_' + str(int(rw_mov[0]))].output:
                            anim_objs[rw_mov[0]] = obj_name
                            obj = bpy.data.objects[obj_name]
                            obj.select_set(state=True)
                            set_obj_locrot_mov(obj, rw_mov)
                    except KeyError:
                        pass
                # main for loop, from second frame to last
                freq = mbs.load_frequency
                Nskip_mov = 0

                for idx, frame in enumerate(np.arange(loop_start + freq, loop_end, freq)):
                    scene.frame_current += 1
                    message = "BLENDYN::set_motion_paths_mov(): Animating frame {}".format(scene.frame_current)
                    print(message)
                    logging.info(message)

                    # skip (freq - 1)*N lines
                    if freq > 1:
                        Nskip_mov = (int(frame) - int(frame - freq) - 2) * mbs.num_nodes

                    if Nskip_mov >= 0:
                        for ii in range(Nskip_mov):
                            next(reader_mov)
                        for ndx in range(mbs.num_nodes):
                            first_mov[ndx] = np.array(next(reader_mov)).astype(np.float)

                    if freq > 1:
                        frac = np.ceil(frame) - frame
                        for ndx in range(mbs.num_nodes):
                            second_mov[ndx] = np.array(next(reader_mov)).astype(np.float)
                        for ndx in range(mbs.num_nodes):
                            try:
                                answer = frac * first_mov[ndx] + (1 - frac) * second_mov[ndx]
                                obj = bpy.data.objects[anim_objs[round(answer[0])]]
                                obj.select_set(state=True)
                                set_obj_locrot_mov(obj, answer)
                            except KeyError:
                                pass
                        first_mov = second_mov
                    else:
                        for ndx in range(mbs.num_nodes):
                            rw_mov = first_mov[ndx]
                            obj = bpy.data.objects[anim_objs[round(rw_mov[0])]]
                            obj.select_set(state=True)
                            set_obj_locrot_mov(obj, rw_mov)
                    wm.progress_update(scene.frame_current)
        except IOError:
            pass
    wm.progress_end()
    # Update deformable elements
    # Gets simulation time (FIXME: not the most clean and efficient way, for sure...)
    if mbs.simtime:
        mbs.simtime.clear()

    for ii in np.arange(0, loop_start, mbs.load_frequency):
        mbs.simtime.add()

    for ii in np.arange(loop_start, loop_end, mbs.load_frequency):
        st = mbs.simtime.add()
        st.time = mbs.time_step * ii
    return {'FINISHED'}
# -----------------------------------------------------------
# end of set_motion_paths_mov() function


def active_object_rel(bool1, bool2):
    if not bool1:
        return True
    if bool1:
        if bool2:
            return True
        else:
            return False

def get_render_vars(self, context):
    mbs = context.scene.mbdyn
    ed = mbs.elems
    ncfile = os.path.join(os.path.dirname(mbs.file_path), \
            mbs.file_basename + '.nc')
    nc = Dataset(ncfile, "r")
    units = ['m/s', 's', 'm', 'N', 'Nm']
    render_vars = list(filter( lambda x: hasattr(nc.variables[x], 'units'), nc.variables.keys() ))
    render_vars = list(filter( lambda x: nc.variables[x].units in units, render_vars ))

    scene_objs = [ str(var.int_label) for var in ed if bpy.data.objects[var.blender_object].select ]
    render_vars = list(filter( lambda x: active_object_rel('elem' in x, \
                   any(i in scene_objs for i in x.split('.'))), render_vars))
    return [(var, var, "") for var in render_vars]
# -----------------------------------------------------------
# end of get_render_vars() function

def get_deformable_elems(self, context):
    mbs = context.scene.mbdyn
    elems = mbs.elems
    def_elems = [elem for elem in elems \
            if (elem.type in DEFORMABLE_ELEMENTS) and (elem.blender_object != 'none')]
    return [(elem.name, elem.name, "") for elem in def_elems]

def get_display_group(self, context):
    mbs = context.scene.mbdyn

    dg = mbs.display_vars_group

    return [(group_name, group_name, "") for group_name in dg.keys()]

def netcdf_helper(nc, scene, key):
    mbs = scene.mbdyn
    freq = mbs.load_frequency
    tdx = scene.frame_current*freq
    frac = np.ceil(tdx) - tdx

    first = Vector((nc.variables[key][int(tdx)]))
    second = Vector((nc.variables[key][int(np.ceil(tdx))]))
    # return = first*frac + second*(1 - frac)
    return  first.lerp(second, 1 - frac)

def netcdf_helper_phi(nc, scene, key):
    mbs = scene.mbdyn
    freq = mbs.load_frequency
    tdx = scene.frame_current*freq
    frac = np.ceil(tdx) - tdx

    first = Vector((nc.variables[key][int(tdx)]))
    second = Vector((nc.variables[key][int(np.ceil(tdx))]))
    return first.lerp(second, 1 - frac)

def netcdf_helper_rmat(nc, scene, var):
    mbs = scene.mbdyn
    freq = mbs.load_frequency
    tdx = scene.frame_current*freq
    frac = np.ceil(tdx) - tdx
    
    first = Matrix((nc.variables[var.variable][int(tdx)]))
    second = Matrix((nc.variables[var.variable][int(np.ceil(tdx))]))
    return first.lerp(second, 1 - frac) 

def netcdf_helper_euler(nc, scene, key, par):
    mbs = scene.mbdyn
    freq = mbs.load_frequency
    tdx = scene.frame_current*freq
    frac = np.ceil(tdx) - tdx

    v1 = math.radians(1.0)*nc.variables[key][int(tdx)]
    v2 = math.radians(1.0)*nc.variables[key][int(np.ceil(tdx))]
    order = axes[par[7]] + axes[par[6]] + axes[par[5]]
    E1 = Euler( Vector((v1[int(par[5]) - 1], \
                        v1[int(par[6]) - 1], \
                        v1[int(par[7]) - 1], )),\
                        order)
    E2 = Euler( Vector((v2[int(par[5]) - 1], \
                        v2[int(par[6]) - 1], \
                        v2[int(par[7]) - 1], )),\
                        order)
    q1 = E1.to_quaternion()
    q2 = E2.to_quaternion()
    return (q1.slerp(q2, 1 - frac)).to_euler(order, E1)

# def netcdf_helper_rvars(nc, scene, var):
#     mbs = scene.mbdyn
#     freq = mbs.load_frequency
#     tdx = scene.frame_current*freq
#     frac = np.ceil(tdx) - tdx
# 
#     first = nc.variables[var.variable][int(tdx)]
#     second = nc.variables[var.variable][int(np.ceil(tdx))]
#     answer = first*frac + second*(1 - frac)
# 
#     dims = len(answer.shape)
# 
#     if (dims == 1):
#         for ii in range(len(answer)):
#             if (var.components[ii]):
#                 var.value[ii] = answer[ii]
#     elif (dims == 2):
#         for ii in range(3):
#             for jj in range(3):
#                 if var.components[ii + jj]:
#                     var.value[ii + jj] = answer[ii,jj]
# 
#     return answer

def netcdf_helper_quat(nc, scene, key):
    mbs = scene.mbdyn
    freq = mbs.load_frequency
    tdx = scene.frame_current * freq
    frac = np.ceil(tdx) - tdx

    q_first = Matrix((nc.variables[key][int(tdx)])).transposed().to_quaternion()
    q_second = Matrix((nc.variables[key][int(np.ceil(tdx))])).transposed().to_quaternion()
    return q_first.slerp(q_second, 1 - frac)

def parse_render_string(var, components):
    if hasattr(var, '__iter__'):
        return ', '.join(['{:.2f}'.format(item) if components[idx] else ' ' for idx, item in enumerate(var)])

    else:
        return '{:.2f}'.format(var)

def comp_repr(components, variable, context):
    mbs = context.scene.mbdyn
    ncfile = os.path.join(os.path.dirname(mbs.file_path), \
            mbs.file_basename + '.nc')
    nc = Dataset(ncfile, "r")
    var = nc.variables[variable]
    dim = len(var.shape)

    comps = ''

    if dim == 2:
        n,m = var.shape
        comps = [str(mdx + 1) for mdx in range(m) if components[mdx] is True]
        comps = ','.join(comps)

    elif dim == 3:
        n,m,k = var.shape
        if mbs.plot_var[-1] == 'R':
            dims_names = ["(1,1)", "(1,2)", "(1,3)", "(2,2)", "(2,3)", "(3,3)"]

        else:
            dims_names = ["(1,1)", "(1,2)", "(1,3)",\
                          "(2,1)", "(2,2)", "(2,3)",\
                          "(3,1)", "(3,2)", "(3,3)"]

        comps = [ dims_names[mdx] for mdx in range(len(dims_names)) if components[mdx] is True]

    else:
        pass

    comps = '[' + comps+']' if comps else comps

    return comps

def set_motion_modal_nodes(context, reader_mod, first_mod, second_mod, nctime, frame):
    scene = context.scene
    mbs = context.scene.mbdyn
    ed = mbs.elems
    nd = mbs.nodes
    if scene.frame_current == scene.frame_start:
        # Initial position of modal nodes
        flag = False  # Whether we set up the node positions in the space
        mode_counter = 0
        for mdx in range(mbs.num_modal_modes):
            mode_counter += 1
            rw_mod = np.array(next(reader_mod)).astype(np.float)
            first_mod.append(rw_mod)
            second_mod.append(rw_mod)
            elem_int_label, mode_int_label = str(rw_mod[0]).split('.')
            elem = ed['modal_' + str(elem_int_label)]
            elem_node = nd['node_' + str(elem.nodes[0].int_label)]
            elem_nodeOJB = bpy.data.objects[elem_node.blender_object]
            for node in elem.modal_node:
                try:
                    obj_name = node.blender_object
                    if obj_name != 'none':
                        obj = bpy.data.objects[obj_name]
                        obj.select_set(state=True)
                        if not flag:
                            obj.location = elem_nodeOJB.matrix_world @ Vector(
                                (node.relative_pos[0] + rw_mod[1] * node.mode[mode_int_label].mode_shape[0],
                                 node.relative_pos[1] + rw_mod[1] * node.mode[mode_int_label].mode_shape[1],
                                 node.relative_pos[2] + rw_mod[1] * node.mode[mode_int_label].mode_shape[2], 1)).to_3d()
                        else:
                            obj.location += elem_nodeOJB.matrix_world @ Vector(
                                (rw_mod[1] * node.mode[mode_int_label].mode_shape[0],
                                 rw_mod[1] * node.mode[mode_int_label].mode_shape[1],
                                 rw_mod[1] * node.mode[mode_int_label].mode_shape[2],
                                 1)).to_3d() - elem_nodeOJB.location
                        try:
                            if mode_counter == len(elem.modal_node[0].mode):
                                obj.keyframe_insert(data_path="location")
                            obj.rotation_euler = elem_nodeOJB.rotation_euler
                            obj.keyframe_insert(data_path="rotation_euler")
                        except KeyError:
                            pass
                except KeyError:
                    pass
            if not flag:
                flag = True
            try:
                if mode_counter == len(elem.modal_node[0].mode):
                    mode_counter = 0
                    flag = False
            except KeyError:
                pass
    else:
        freq = mbs.load_frequency
        Nskip_mod = 0
        if freq > 1:
            Nskip_mod = (int(scene.frame_current * freq + nctime[0] / mbs.time_step) - int(
                (scene.frame_current - 1) * freq + nctime[0] / mbs.time_step) - 2) * mbs.num_modal_modes
        if Nskip_mod >= 0:
            for ii in range(Nskip_mod):
                next(reader_mod)
            for ndx in range(mbs.num_modal_modes):
                first_mod[ndx] = np.array(next(reader_mod)).astype(np.float)

        if freq > 1:
            frac = np.ceil(frame) - frame
            for ndx in range(mbs.num_modal_modes):
                second_mod[ndx] = np.array(next(reader_mod)).astype(np.float)

            flag = False  # Whether we set up the node positions in the space
            mode_counter = 0
            for mdx in range(mbs.num_modal_modes):
                mode_counter += 1
                rw_mod = first_mod[mdx]
                elem_int_label, mode_int_label = str(rw_mod[0]).split('.')
                elem = ed['modal_' + str(elem_int_label)]
                elem_node = nd['node_' + str(elem.nodes[0].int_label)]
                elem_nodeOJB = bpy.data.objects[elem_node.blender_object]
                for node in elem.modal_node:
                    try:
                        obj_name = node.blender_object
                        if obj_name != 'none':
                            answer = frac * first_mod[mdx] + (1 - frac) * second_mod[mdx]
                            obj = bpy.data.objects[obj_name]
                            obj.select_set(state=True)
                            if not flag:
                                obj.location = elem_nodeOJB.matrix_world @ Vector(
                                    (node.relative_pos[0] + answer[1] * node.mode[mode_int_label].mode_shape[0],
                                     node.relative_pos[1] + answer[1] * node.mode[mode_int_label].mode_shape[1],
                                     node.relative_pos[2] + answer[1] * node.mode[mode_int_label].mode_shape[2],
                                     1)).to_3d()
                            else:
                                obj.location += elem_nodeOJB.matrix_world @ Vector(
                                    (answer[1] * node.mode[mode_int_label].mode_shape[0],
                                     answer[1] * node.mode[mode_int_label].mode_shape[1],
                                     answer[1] * node.mode[mode_int_label].mode_shape[2],
                                     1)).to_3d() - elem_nodeOJB.location

                            try:
                                if mode_counter == len(elem.modal_node[0].mode):
                                    obj.keyframe_insert(data_path="location")
                                obj.rotation_euler = elem_nodeOJB.rotation_euler
                                obj.keyframe_insert(data_path="rotation_euler")
                            except KeyError:
                                pass

                    except KeyError:
                        pass
                if not flag:
                    flag = True
                try:
                    if mode_counter == len(elem.modal_node[0].mode):
                        mode_counter = 0
                        flag = False
                except KeyError:
                    pass
            first_mod = second_mod
        else:
            flag = False  # Whether we set up the node positions in the space
            mode_counter = 0
            for mdx in range(mbs.num_modal_modes):
                mode_counter += 1
                rw_mod = first_mod[mdx]
                elem_int_label, mode_int_label = str(rw_mod[0]).split('.')
                elem = ed['modal_' + elem_int_label]
                elem_node = nd['node_' + str(elem.nodes[0].int_label)]
                elem_nodeOJB = bpy.data.objects[elem_node.blender_object]
                for node in elem.modal_node:
                    try:
                        obj_name = node.blender_object
                        if obj_name != 'none':
                            obj = bpy.data.objects[obj_name]
                            obj.select_set(state=True)
                            if not flag:
                                obj.location = elem_nodeOJB.matrix_world @ Vector(
                                    (node.relative_pos[0] + float(rw_mod[1]) * node.mode[mode_int_label].mode_shape[0],
                                     node.relative_pos[1] + float(rw_mod[1]) * node.mode[mode_int_label].mode_shape[1],
                                     node.relative_pos[2] + float(rw_mod[1]) * node.mode[mode_int_label].mode_shape[2],
                                     1)).to_3d()

                            else:
                                obj.location += elem_nodeOJB.matrix_world @ Vector(
                                    (float(rw_mod[1]) * node.mode[mode_int_label].mode_shape[0],
                                     float(rw_mod[1]) * node.mode[mode_int_label].mode_shape[1],
                                     float(rw_mod[1]) * node.mode[mode_int_label].mode_shape[2],
                                     1)).to_3d() - elem_nodeOJB.location
                            try:
                                if mode_counter == len(elem.modal_node[0].mode):
                                    obj.keyframe_insert(data_path="location")
                                obj.rotation_euler = elem_nodeOJB.rotation_euler
                                obj.keyframe_insert(data_path="rotation_euler")
                            except KeyError:
                                pass
                    except KeyError:
                        pass
                if not flag:
                    flag = False
                try:
                    if mode_counter == len(elem.modal_node[0].mode):
                        mode_counter = 0
                        flag = False
                except KeyError:
                    pass
    return first_mod, second_mod
#---------------------------------------------------------------
# end of set_motion_modal_nodes() function


def set_motion_paths_netcdf(context):
    scene = context.scene
    mbs = scene.mbdyn
    nd = mbs.nodes
    ed = mbs.elems
    wm = context.window_manager

    have_mod_file = True
    ncfile = os.path.join(os.path.dirname(mbs.file_path), \
            mbs.file_basename + '.nc')
    if os.path.isfile(os.path.join(os.path.dirname(mbs.file_path), \
            mbs.file_basename + '.mod')):
        mod_file =  os.path.join(os.path.dirname(mbs.file_path), \
            mbs.file_basename + '.mod')
    else:
        have_mod_file = False

    nc = Dataset(ncfile, "r")
    freq = mbs.load_frequency
    nctime = nc.variables["time"]
    mbs.time_step = nctime[1] - nctime[0]
    if nctime[0] == 0.0:
        scene.frame_start = int(mbs.start_time/(mbs.time_step*mbs.load_frequency))
        scene.frame_end = int(mbs.end_time/(mbs.time_step*mbs.load_frequency)) + 1
    else:
        scene.frame_start = int((mbs.start_time - nctime[0])/(mbs.time_step*mbs.load_frequency))
        scene.frame_end = int((mbs.end_time - nctime[0])/(mbs.time_step*mbs.load_frequency)) + 1

    anim_nodes = list()
    for node in nd:
        if node.blender_object != 'none':
            anim_nodes.append(node.name)

    scene.frame_current = scene.frame_start

    loop_start = int(scene.frame_start * mbs.load_frequency)
    loop_end = int(scene.frame_end * mbs.load_frequency)

    if mbs.simtime:
        mbs.simtime.clear()

    for ii in np.arange(0, loop_start, mbs.load_frequency):
        mbs.simtime.add()

    for ii in np.arange(loop_start, loop_end, mbs.load_frequency):
        st = mbs.simtime.add()
        st.time = mbs.time_step * ii

    # set objects location and rotation
    wm.progress_begin(scene.frame_start, scene.frame_end)
    if have_mod_file:
        with open(mod_file) as mdf:
            reader_mod = csv.reader(mdf, delimiter=' ', skipinitialspace=True)
            for ndx in range(int(mbs.start_time * mbs.num_modal_modes / mbs.time_step)):
                next(reader_mod)
            first_mod = []
            second_mod = []
            for frame in range(scene.frame_start, scene.frame_end):
                scene.frame_current = frame
                for ndx in anim_nodes:
                    dictobj = nd[ndx]
                    if not(dictobj.output):
                        continue

                    obj = bpy.data.objects[dictobj.blender_object]
                    obj.select_set(state = True)
                    node_var = 'node.struct.' + str(dictobj.int_label) + '.'
                    par = dictobj.parametrization
                    if par == 'PHI':
                            answer = netcdf_helper(nc, scene, node_var + 'X')
                            obj.location = Vector((answer))
                            obj.keyframe_insert(data_path = "location")

                            answer = netcdf_helper_phi(nc, scene, node_var + 'Phi')
                            rotvec = Vector((answer))
                            rotvec_norm = rotvec.normalized()
                            obj.rotation_axis_angle = Vector (( rotvec.magnitude, \
                                    rotvec_norm[0], rotvec_norm[1], rotvec_norm[2] ))
                            obj.keyframe_insert(data_path = "rotation_axis_angle")
                    elif par[0:5] == 'EULER':
                            loc = netcdf_helper(nc, scene, node_var + 'X')
                            obj.location = Vector((loc))
                            obj.keyframe_insert(data_path = "location")

                            angles = math.radians(1.0)*netcdf_helper(nc, scene, node_var + 'E')
                            obj.rotation_euler = Euler( Vector((\
                                                 angles[int(par[5]) - 1],\
                                                 angles[int(par[6]) - 1],\
                                                 angles[int(par[7]) - 1],\
                                                 )),\
                                                 axes[par[7]] + axes[par[6]] + axes[par[5]] )
                            obj.keyframe_insert(data_path = "rotation_euler")
                    elif par == 'MATRIX':
                            answer = netcdf_helper(nc, scene, node_var + 'X')
                            obj.location = Vector((answer))
                            obj.keyframe_insert(data_path = "location")

                            obj.rotation_quaternion = netcdf_helper_quat(nc, scene, node_var + 'R')

                            obj.keyframe_insert(data_path = "rotation_quaternion")
                    else:
                        # Should not be reached
                        print("BLENDYN::set_motion_paths_netcdf() Error: unrecognised rotation parametrization")
                        return {'CANCELLED'}
                    obj.select_set(state = False)
                dg = bpy.context.evaluated_depsgraph_get()
                dg.update()
                first_mod, second_mod = set_motion_modal_nodes(context, reader_mod, first_mod, second_mod, nctime, frame)
                if mbs.sim_stress:
                    update_stress(context)
                wm.progress_update(scene.frame_current)
    else:
        for frame in range(scene.frame_start, scene.frame_end):
            scene.frame_current = frame
            for ndx in anim_nodes:
                dictobj = nd[ndx]
                if not (dictobj.output):
                    continue

                obj = bpy.data.objects[dictobj.blender_object]
                obj.select_set(state=True)
                node_var = 'node.struct.' + str(dictobj.int_label) + '.'
                par = dictobj.parametrization
                if par == 'PHI':
                    answer = netcdf_helper(nc, scene, node_var + 'X')
                    obj.location = Vector((answer))
                    obj.keyframe_insert(data_path="location")

                    answer = netcdf_helper_phi(nc, scene, node_var + 'Phi')
                    rotvec = Vector((answer))
                    rotvec_norm = rotvec.normalized()
                    obj.rotation_axis_angle = Vector((rotvec.magnitude, \
                                                      rotvec_norm[0], rotvec_norm[1], rotvec_norm[2]))
                    obj.keyframe_insert(data_path="rotation_axis_angle")
                elif par[0:5] == 'EULER':
                    loc = netcdf_helper(nc, scene, node_var + 'X')
                    obj.location = Vector((loc))
                    obj.keyframe_insert(data_path="location")

                    angles = math.radians(1.0) * netcdf_helper(nc, scene, node_var + 'E')
                    obj.rotation_euler = Euler(Vector((
                                                angles[int(par[5]) - 1], \
                                                angles[int(par[6]) - 1], \
                                                angles[int(par[7]) - 1],)), \
                                            axes[par[7]] + axes[par[6]] + axes[par[5]])
                    obj.keyframe_insert(data_path="rotation_euler")
                elif par == 'MATRIX':
                    answer = netcdf_helper(nc, scene, node_var + 'X')
                    obj.location = Vector((answer))
                    obj.keyframe_insert(data_path="location")

                    obj.rotation_quaternion = netcdf_helper_quat(nc, scene, node_var + 'R')

                    obj.keyframe_insert(data_path="rotation_quaternion")
                else:
                    # Should not be reached
                    print("BLENDYN::set_motion_paths_netcdf() Error: unrecognised rotation parametrization")
                    return {'CANCELLED'}
                obj.select_set(state=False)
            if mbs.sim_stress:
                update_stress(context)
            wm.progress_update(scene.frame_current)
    wm.progress_end()
    return {'FINISHED'}
# -----------------------------------------------------------
# end of set_motion_paths_netcdf() function

class BlenderHandler(logging.Handler):
    def emit(self, record):
        MAXKEYLEN = 2**6 - 1    # FIXME: Is this universal?
        log_entry = self.format(record)
        try:
            editor = bpy.data.texts[os.path.basename(logFile)]
            editor.write(log_entry + '\n')
        except KeyError:
            logtext = os.path.basename(logFile)
            editor = bpy.data.texts[logtext[0:MAXKEYLEN]]

def log_messages(mbs, baseLogger, saved_blend):
        try:
	        blendFile = os.path.basename(bpy.data.filepath) if bpy.data.is_saved \
	                    else 'untitled.blend'
	        blendFile = os.path.splitext(blendFile)[0]

	        formatter = '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
	        datefmt = '%m/%d/%Y %I:%M:%S %p'
	        global logFile
	        logFile = ('{0}_{1}.bylog').format(mbs.file_path + blendFile, mbs.file_basename)

	        fh = logging.FileHandler(logFile)
	        fh.setFormatter(logging.Formatter(formatter, datefmt))

	        custom = BlenderHandler()
	        custom.setFormatter(logging.Formatter(formatter, datefmt))

	        baseLogger.addHandler(fh)
	        baseLogger.addHandler(custom)

	        if not saved_blend:
	            bpy.data.texts.new(os.path.basename(logFile))
        except PermissionError as ex:
            print("Blendyn::BlenderHandler::log_messages(): " +\
                    "caught PermissionError exception {0}".format(ex))

def delete_log():
    try:
        print("BLENDYN::logging_shutdown()::INFO: deleting log files.")
        if os.path.exists(logFile):
            os.remove(logFile)
            print("Blendyn::delete_log(): removed file" + logFile)
    except NameError as ex:
        print("Blendyn::delete_log(): NameError:" + str(e))
        pass

def donot_delete_log():
    mbs = bpy.context.scene.mbdyn
    if not(mbs.del_log):
        atexit.unregister(delete_log)

def logging_shutdown():
    print("BLENDYN::logging_shutdown()::INFO: shutting down logs.")
    print("BLENDYN::logging_shutdown()::INFO: removing handlers.")
    logger = logging.getLogger()
    for handler in logger.handlers:
        try:
            handler.acquire()
            handler.flush()
            handler.close()
        except (OSError, ValueError):
            pass
        finally:
            handler.release()
        logger.removeHandler(handler)
    print("BLENDYN::logging_shutdown()::INFO: done.")

def update_del_log(self, context):
    mbs = context.scene.mbdyn
    if mbs.del_log:
        atexit.register(delete_log)
    else:
        atexit.unregister(delete_log)

bpy.app.handlers.save_post.append(donot_delete_log)
atexit.register(logging_shutdown)
