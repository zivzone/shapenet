from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
import os

_root_dir = os.path.realpath(os.path.dirname(__file__))
fixed_obj_data_dir = os.path.join(_root_dir, '_fixed_meshes')

_bad_ids = {'02958343': ('f9c1d7748c15499c6f2bd1c4e9adb41')}


def get_fixed_obj_dir(cat_id, example_id=None):
    if example_id is None:
        return os.path.join(fixed_obj_data_dir, cat_id)
    else:
        return os.path.join(fixed_obj_data_dir, cat_id, example_id)


def get_fixed_obj_path(cat_id, example_id):
    return os.path.join(get_fixed_obj_dir(cat_id, example_id), 'model.obj')


def get_bad_model_ids(cat_id=None):
    if cat_id is None:
        return _bad_ids.copy()
    else:
        return _bad_ids.get(cat_id, ())


def is_bad_obj(cat_id, example_id):
    return example_id in get_bad_model_ids(cat_id)