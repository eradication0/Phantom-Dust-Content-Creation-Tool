"""Glow (Emission Map) test: does the light map's alpha glow work the way the add-on's export writes it?

    python tools/emission_test_map.py BASE_DAT BASE_ALR HUB_ALR OUT_DIR [--map st02]

Same pads as tools/lightmap_test_map.py (checker texture tiling on UV0, light map on UV1, shader lbts), over the
map being replaced (Spiral Highway, st02). Light maps are encoded exactly as the add-on exports a glow: where
something glows the light map gets at least the glow colour and its alpha = glow / light map.
  1  dim light map (grey 0.25) with three glowing squares: orange, cyan, white
  2  the same dim light map without any glow (alpha 0), to compare with pad 1
  3  nearly dark light map (0.05) with glowing stripes: glow in the dark
  4  sd, the normal stage shader (for comparison)
Expected if it works: on pad 1 and 3 the squares and stripes shine in their colour on top of the checker, brighter
than the light alone; pad 2 shows no squares. Standalone test, not part of the add-on.
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'addon', 'phantom_dust_stage'))
import lightmap_test_map as lmt  # noqa: E402
from pdstage import alr_build  # noqa: E402

SIZE = 64


def encode(light, glow):
    """light, glow: (h, w, 3) floats 0-1 -> BGRA mip levels, as visuals_export.image_levels does."""
    peak = glow.max(axis=-1)
    on = peak > 1.0 / 255
    lit = np.where(on[..., None], np.maximum(light, glow), light)
    alpha = np.where(on, np.clip(peak / np.maximum(lit.max(axis=-1), 1e-4), 0, 1), 0.0)
    px = np.concatenate([lit, alpha[..., None]], -1)
    levels, cur = [], px
    while True:
        levels.append(np.clip(np.round(cur * 255), 0, 255).astype(np.uint8)[..., [2, 1, 0, 3]].tobytes())
        h, w = cur.shape[:2]
        if h == 1:
            return levels
        cur = cur.reshape(h // 2, 2, w // 2, 2, 4).mean(axis=(1, 3))


def maps():
    yy, xx = np.mgrid[0:SIZE, 0:SIZE] / SIZE
    dim = np.full((SIZE, SIZE, 3), 0.25)
    squares = np.zeros((SIZE, SIZE, 3))
    for (x0, y0, c) in ((0.1, 0.1, (1.0, 0.55, 0.1)), (0.55, 0.1, (0.1, 0.9, 1.0)), (0.3, 0.55, (1.0, 1.0, 1.0))):
        squares[(xx >= x0) & (xx < x0 + 0.3) & (yy >= y0) & (yy < y0 + 0.3)] = c
    stripes = np.zeros((SIZE, SIZE, 3))
    stripes[(np.floor(xx * 8) % 2 == 0) & (yy > 0.2) & (yy < 0.8)] = (1.0, 0.2, 0.6)
    return [encode(dim, squares), encode(dim, np.zeros_like(dim)), encode(np.full_like(dim, 0.05), stripes)]


def build(base_dat, base_alr, hub_alr):
    hub = open(hub_alr, 'rb').read()
    alr_build.VERTEX_MASK[lmt.LBTS_FORMAT] = lmt.LBTS_MASK
    material = lmt.lbts_material(hub)
    glow_maps = maps()
    textures = [dict(name='pd_lmcheck', width=64, height=64, levels=lmt.mips(lmt.checker, 64)),
                dict(name='pd_lmflat', width=4, height=4, levels=lmt.mips(lmt.flat, 4))]
    for i, lv in enumerate(glow_maps):
        textures.append(dict(name='pd_glow%d' % i, width=SIZE, height=SIZE, levels=lv))
    diffuse, normal = ('new', 0), ('new', 1)
    n = 4
    x_start = -(n * lmt.PAD + (n - 1) * lmt.GAP) / 2
    z0 = -lmt.PAD / 2
    stage = [lmt.pad_lbts(x_start + i * (lmt.PAD + lmt.GAP), z0, material, ('new', 2 + i), diffuse, normal)
             for i in range(3)]
    x4 = x_start + 3 * (lmt.PAD + lmt.GAP)
    up, white = (0.0, 1.0, 0.0), (255, 255, 255, 255)
    sd_v = [((x4, 0.0, z0), up, (0, 0), white), ((x4, 0.0, z0 + lmt.PAD), up, (0, 8), white),
            ((x4 + lmt.PAD, 0.0, z0 + lmt.PAD), up, (8, 8), white), ((x4 + lmt.PAD, 0.0, z0), up, (8, 0), white)]
    stage.append(dict(verts=sd_v, tris=[(0, 1, 3), (1, 2, 3)],
                      material=dict(diffuse=diffuse, normal=None, reflection=None, specular=(0, 0, 0, 0))))
    # the floor, walls and spawns of the light map test, then this stage
    d, _ = lmt.build(base_dat, base_alr, hub_alr)
    b = open(base_alr, 'rb').read()
    new_alr, _ = alr_build.rebuild(b, replace={0: stage}, clear=(1,), shadows_for=(0,), textures=textures)
    return d, new_alr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('base_dat')
    ap.add_argument('base_alr')
    ap.add_argument('hub_alr')
    ap.add_argument('out_dir')
    ap.add_argument('--map', default='st02')
    a = ap.parse_args()
    d, m = build(a.base_dat, a.base_alr, a.hub_alr)
    os.makedirs(a.out_dir, exist_ok=True)
    open(os.path.join(a.out_dir, a.map + '.dat'), 'wb').write(d)
    open(os.path.join(a.out_dir, a.map + '.alr'), 'wb').write(m)
    print('.alr %.1f MB, .dat %d bytes' % (len(m) / 1e6, len(d)))


if __name__ == '__main__':
    main()
