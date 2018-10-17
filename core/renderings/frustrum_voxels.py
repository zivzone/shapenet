from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import numpy as np
import h5py
from .hdf5 import get_camera_positions
from ..voxels.datasets import get_manager

from util3d.transform.frustrum import voxel_values_to_frustrum
from util3d.transform.nonhom import get_eye_to_world_transform
from util3d.voxel.binvox import DenseVoxels, RleVoxels


compression = 'lzf'
f = 32 / 35

GROUP_KEY = 'rle-pad-lzf_data'


def _make_dir(filename):
    folder = os.path.dirname(filename)
    if not os.path.isdir(folder):
        os.makedirs(folder)


def convert(vox, eye, ray_shape):
    dense_data = vox.dense_data()
    dense_data = dense_data[:, -1::-1]
    n = np.linalg.norm(eye)
    R, t = get_eye_to_world_transform(eye)
    z_near = n - 0.5
    z_far = z_near + 1

    frust, inside = voxel_values_to_frustrum(
        dense_data, R, t, f, z_near, z_far, ray_shape,
        include_corners=False)
    frust[np.logical_not(inside)] = 0
    frust = frust[:, -1::-1]
    return DenseVoxels(frust)


def _get_frustrum_voxels_path(
        manager_dir, voxel_config, out_dim, cat_id, code=None):
    fn = ('%s.hdf5' % cat_id) if code is None else (
        '%s_%s.hdf5' % (code, cat_id))
    return os.path.join(
        manager_dir, 'frustrum_voxels', voxel_config.voxel_id,
        'v%03d' % out_dim, fn)


def get_frustrum_voxels_path(
        manager_dir, voxel_config, out_dim, cat_id):
    return _get_frustrum_voxels_path(
        manager_dir, voxel_config, out_dim, cat_id)


def get_frustrum_voxels_data(manager_dir, voxel_config, out_dim, cat_id):
    return h5py.File(get_frustrum_voxels_path(
        manager_dir, voxel_config, out_dim, cat_id))


def create_temp_frustrum_voxels(
        render_manager, voxel_config, out_dim, cat_id):
    from progress.bar import IncrementalBar
    n_renderings = render_manager.get_render_params()['n_renderings']
    in_dims = (voxel_config.voxel_dim,) * 3
    ray_shape = (out_dim,) * 3
    with get_camera_positions(render_manager) as camera_pos:
        eye_group = camera_pos[cat_id]
        n0 = len(eye_group)
        temp_path = _get_frustrum_voxels_path(
                render_manager.root_dir, voxel_config, out_dim, cat_id,
                code='temp')
        _make_dir(temp_path)
        with h5py.File(temp_path, 'a') as vox_dst:
            attrs = vox_dst.attrs
            prog = attrs.get('prog', 0)
            if prog == n0:
                return temp_path

            attrs.setdefault('n_renderings', n_renderings)
            max_len = attrs.setdefault('max_len', 0)

            vox_manager = get_manager(
                voxel_config, cat_id, key='rle',
                compression=compression, shape_key='pad')
            if not vox_manager.has_dataset():
                raise RuntimeError('No dataset')
            with h5py.File(vox_manager.path, 'r') as vox_src:
                rle_src = vox_src['rle-pad-lzf_data']

                n, m = rle_src.shape
                max_max_len = m * 3
                assert(n == n0)

                print(
                    'Creating temp rle frustrum voxel data at %s' % temp_path)
                rle_dst = vox_dst.require_dataset(
                    GROUP_KEY, shape=(n, n_renderings, max_max_len),
                    dtype=np.uint8, compression=compression)
                bar = IncrementalBar(max=n-prog)
                for i in range(prog, n):
                    bar.next()
                    vox = RleVoxels(np.array(rle_src[i]), in_dims)
                    eye = eye_group[i]
                    for j in range(n_renderings):
                        out = convert(vox, eye[j], ray_shape)
                        data = out.rle_data()
                        dlen = len(data)
                        if dlen > max_len:
                            attrs['max_len'] = dlen
                            max_len = dlen
                            if dlen > max_max_len:
                                raise ValueError(
                                    'max_max_len exceeded. %d > %d'
                                    % (dlen, max_max_len))
                        rle_dst[i, j, :dlen] = data
                    attrs['prog'] = i+1
                bar.finish()
    return temp_path


def _shrink_data(temp_path, dst_path, chunk_size=100):
    from progress.bar import IncrementalBar
    print('Shrinking data to fit.')
    with h5py.File(temp_path, 'r') as src:
        max_len = src.attrs['max_len']
        src_group = src[GROUP_KEY]
        _make_dir(dst_path)
        with h5py.File(dst_path, 'w') as dst:
            n_examples, n_renderings = src_group.shape[:2]
            dst_dataset = dst.create_dataset(
                GROUP_KEY, shape=(n_examples, n_renderings, max_len),
                dtype=np.uint8, compression=compression)
            bar = IncrementalBar(max=n_examples // chunk_size)
            for i in range(0, n_examples, chunk_size):
                stop = min(i + chunk_size, n_examples)
                dst_dataset[i:stop] = src_group[i:stop, :, :max_len]
                bar.next()
            bar.finish()


def _concat_data(temp_path, dst_path):
    from progress.bar import IncrementalBar
    from util3d.voxel import rle
    print('Concatenating data')
    with h5py.File(temp_path, 'r') as src:
        src_group = src[GROUP_KEY]
        _make_dir(dst_path)
        with h5py.File(dst_path, 'w') as dst:
            n_examples, n_renderings = src_group.shape[:2]
            n_total = n_examples * n_renderings
            starts = np.empty(dtype=np.int64, shape=(n_total+1,))
            print('Computing starts...')
            k = 1
            start = 0
            starts[0] = start
            bar = IncrementalBar(max=n_examples)
            for i in range(n_examples):
                bar.next()
                example_data = np.array(src_group[i])
                for j in range(n_renderings):
                    data = rle.remove_length_padding(example_data[j])
                    start += len(data)
                    starts[k] = start
                    k += 1
            bar.finish()
            assert(k == n_total+1)
            dst.create_dataset('starts', data=starts)
            values = dst.create_dataset(
                'values', dtype=np.uint8, shape=(starts[-1],))

            k = 0
            print('Transfering data...')
            bar = IncrementalBar(max=n_examples)
            for i in range(n_examples):
                example_data = np.array(src_group[i])
                bar.next()
                for j in range(n_renderings):
                    values[starts[k]: starts[k+1]] = rle.remove_length_padding(
                        example_data[j])
                    k += 1
            bar.finish()
            assert(k == n_total)


def create_frustrum_voxels(
        render_manager, voxel_config, out_dim, cat_id):
    kwargs = dict(
        voxel_config=voxel_config,
        out_dim=out_dim, cat_id=cat_id)
    # dst_path = _get_frustrum_voxels_path(
    #     manager_dir=render_manager.root_dir, code='cat', **kwargs)
    dst_path = _get_frustrum_voxels_path(
        manager_dir=render_manager.root_dir, code=None, **kwargs)
    if os.path.isfile(dst_path):
        print('Already present.')
        return
    temp_path = create_temp_frustrum_voxels(
        render_manager=render_manager, **kwargs)
    _shrink_data(temp_path, dst_path)
    # _concat_data(temp_path, dst_path)
