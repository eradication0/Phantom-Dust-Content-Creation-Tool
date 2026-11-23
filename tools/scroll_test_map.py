"""Scrolling-texture test (shader sbtscloud3, the sky's cloud shader) on an empty map.

    python tools/scroll_test_map.py BASE_DAT BASE_ALR OUT_DIR [--map st03]

Flat floor at y = 100 (surface 08), invisible edge walls, the map's own sky. From the spawns (near end, facing
+z), each panel has its number on a label below it:
  row 1 (z = -100), left to right
     1  arrows,  colour X  +600                     solid
     2  arrows,  colour Y  +600                     solid
     3  arrows,  colour  -600 / -600                solid (negative speeds)
     4  arrows,  colour X +2000                     solid (fast)
     5  water,   colour 150/75, A 400/0, B 0/-300   solid, bumps
     6  lava,    colour 60/0, A 200/100, B -150/50  solid, bumps
     7  energy,  colour 0/1200                      ADD (glow on top)
     8  water,   50 % alpha, as 5                   ALPHA (see-through)
     9  holes,   the two shape layers cut holes     ALPHA (cut out, as clouds)
    10  the map's own sky clouds and speeds         ADD (as the sky)
  row 2 (z = 200)
    11  arrows, still colour, normal map A 600/0    solid (only the bumps move)
    12  arrows, still colour, normal map B 0/600    solid
    13  a water pool on the floor (ALPHA, as 8)
    14  a lava floor (solid, as 6)
Standalone test, not part of the add-on.
"""
import argparse
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'addon', 'phantom_dust_stage'))
from pdstage import alr, alr_build, collision_build, dat, dxt  # noqa: E402
import surface_diff_test_map as sdt  # noqa: E402

Y = sdt.Y
S = 128


def levels(rgba):
    out, fmt = [], None
    img = rgba
    while True:
        f, data = dxt.encode(img, alpha=True)
        fmt = f
        out.append(data)
        if img.shape[0] <= 4 or len(out) >= 6:
            break
        img = img.reshape(img.shape[0] // 2, 2, img.shape[1] // 2, 2, 4).mean((1, 3)).astype(np.uint8)
    return fmt, out


def tex(name, rgba):
    fmt, lv = levels(rgba)
    return dict(name=name, width=rgba.shape[1], height=rgba.shape[0], levels=lv, mips=len(lv), format=fmt)


yy, xx = np.mgrid[0:S, 0:S].astype(np.float32) / S


def rgba(r, g, b, a=255):
    out = np.zeros((S, S, 4), np.uint8)
    for k, c in enumerate((r, g, b, a)):
        out[..., k] = np.clip(c if np.ndim(c) else np.full((S, S), c), 0, 255)
    return out


def arrows():
    """Two right-pointing arrows (towards +u) over a grid; a dot marks the top (-v)."""
    base = 40 + 20 * (((xx * 8).astype(int) + (yy * 8).astype(int)) % 2)
    u, v = (xx * 2) % 1, (yy * 2) % 1
    shaft = (abs(v - 0.5) < 0.08) & (u > 0.15) & (u < 0.65)
    head = (u >= 0.6) & (u < 0.85) & (abs(v - 0.5) < (0.85 - u) * 1.2)
    dot = ((u - 0.3) ** 2 + (v - 0.2) ** 2) < 0.004
    r = np.where(shaft | head, 255, np.where(dot, 60, base))
    g = np.where(shaft | head, 220, np.where(dot, 200, base))
    b = np.where(shaft | head, 40, np.where(dot, 255, base + 30))
    return rgba(r, g, b)


def noise(seed, octaves=4):
    rng = np.random.default_rng(seed)
    out = np.zeros((S, S), np.float32)
    for o in range(octaves):
        n = 4 * 2 ** o
        g = rng.random((n, n)).astype(np.float32)
        g = np.kron(g, np.ones((S // n, S // n), np.float32))
        k = max(1, S // n // 2)
        for ax in (0, 1):                                  # cheap wrap-around blur
            g = sum(np.roll(g, s, ax) for s in range(-k, k + 1)) / (2 * k + 1)
        out += g / 2 ** o
    out -= out.min()
    return out / out.max()


def normal_map(height, strength, alpha=127):
    dx = (np.roll(height, -1, 1) - np.roll(height, 1, 1)) * strength
    dy = (np.roll(height, -1, 0) - np.roll(height, 1, 0)) * strength
    n = np.stack([-dx, -dy, np.ones_like(dx)], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    c = ((n * 0.5 + 0.5) * 255).astype(np.uint8)
    a = alpha if np.ndim(alpha) else np.full((S, S), alpha)
    return rgba(c[..., 0], c[..., 1], c[..., 2], a)


waves = (np.sin(xx * 2 * math.pi * 3) * 0.5 + 0.5) * 0.6 + noise(1) * 0.4
waves2 = (np.sin((xx + yy) * 2 * math.pi * 2) * 0.5 + 0.5) * 0.5 + noise(2) * 0.5
lava_h = noise(3)
water_c = rgba(30 + 40 * noise(4), 90 + 60 * noise(4), 170 + 70 * noise(5))
water_half = rgba(30 + 40 * noise(4), 90 + 60 * noise(4), 170 + 70 * noise(5), 128)
veins = np.clip(1 - abs(noise(6) - 0.5) * 6, 0, 1)
lava_c = rgba(120 + 135 * veins, 25 + 170 * veins ** 2, 10 + 40 * veins ** 3)
stripes = np.clip(np.sin(yy * 2 * math.pi * 4) * 1.5, 0, 1) * (0.6 + 0.4 * noise(7))
energy_c = rgba(40 * stripes, 160 * stripes, 255 * stripes)
holes_c = rgba(230, 230, 240, 255)
holes_a = (np.clip((noise(8) - 0.35) * 4, 0, 1) * 255).astype(np.uint8)
holes_b = (np.clip((noise(9) - 0.35) * 4, 0, 1) * 255).astype(np.uint8)

new = [tex('scr_arrows', arrows()), tex('scr_flatn', normal_map(np.zeros((S, S), np.float32), 0)),
       tex('scr_wave_n', normal_map(waves, 6)), tex('scr_wave2_n', normal_map(waves2, 6)),
       tex('scr_water', water_c), tex('scr_lava', lava_c), tex('scr_lava_n', normal_map(lava_h, 10)),
       tex('scr_energy', energy_c), tex('scr_water50', water_half), tex('scr_cloud', holes_c),
       tex('scr_hole_a', normal_map(noise(8), 4, holes_a)), tex('scr_hole_b', normal_map(noise(9), 4, holes_b))]
T = {t['name']: ('new', i) for i, t in enumerate(new)}
FLAT = T['scr_flatn']


WHITE = (255, 255, 255, 255)


def label_atlas():
    """16 cells: FLOOR, WALL, then 1..14 for the labels."""
    from PIL import Image, ImageDraw, ImageFont
    size, n = 512, 4
    names = ['FLOOR', 'WALL'] + [str(k) for k in range(1, 15)]
    im = Image.new('RGBA', (size, size), (60, 60, 60, 255))
    d = ImageDraw.Draw(im)
    c = size // n
    try:
        font = ImageFont.load_default(size=int(c * 0.45))
    except TypeError:
        font = ImageFont.load_default()
    cells = {}
    for i, name in enumerate(names[:n * n]):
        x, y = (i % n) * c, (i // n) * c
        col = {'FLOOR': (150, 150, 150), 'WALL': (110, 110, 120), 'START': (120, 170, 120)}.get(name, (235, 235, 235))
        d.rectangle([x, y, x + c - 1, y + c - 1], fill=col + (255,), outline=(20, 20, 20, 255), width=6)
        if name not in ('FLOOR', 'WALL'):
            bb = d.textbbox((0, 0), name, font=font)
            d.text((x + (c - bb[2]) / 2, y + (c - bb[3]) / 2), name, fill=(10, 10, 10, 255), font=font)
        cells[name] = ((i % n) / n + 0.004, (i // n) / n + 0.004, (i % n + 1) / n - 0.004, (i // n + 1) / n - 0.004)
    px = np.asarray(im)
    return tex('scr_labels', px), cells


def quad(p, n, uvs, mat, t=None, bn=None):
    """p: 4 corners (any winding); n facing; UVs per corner. Both triangle windings faced to n."""
    if t is None:
        vs = [(p[i], n, uvs[i], WHITE) for i in range(4)]
    else:
        vs = [(p[i], n, uvs[i], WHITE, t, bn) for i in range(4)]
    a = [p[1][k] - p[0][k] for k in range(3)]
    b = [p[3][k] - p[0][k] for k in range(3)]
    c = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    tris = [(0, 1, 3), (1, 2, 3)] if sum(c[k] * n[k] for k in range(3)) > 0 else [(0, 3, 1), (1, 3, 2)]
    return dict(verts=vs, tris=tris, material=mat)


def panel(cx, y0, z, w, hgt, mat, tiles=2.0):
    """Standing quad facing -z (the spawns); u along +x, v downwards."""
    x0, x1 = cx - w / 2, cx + w / 2
    p = [(x0, y0, z), (x0, y0 + hgt, z), (x1, y0 + hgt, z), (x1, y0, z)]
    uvs = [(0, tiles), (0, 0), (tiles, 0), (tiles, tiles)]
    return quad(p, (0.0, 0.0, -1.0), uvs, mat, (1.0, 0.0, 0.0), (0.0, -1.0, 0.0))


def flat(cx, cz, size, y, mat, tiles=3.0):
    s = size / 2
    p = [(cx - s, y, cz - s), (cx - s, y, cz + s), (cx + s, y, cz + s), (cx + s, y, cz - s)]
    uvs = [(0, tiles), (0, 0), (tiles, 0), (tiles, tiles)]
    return quad(p, (0.0, 1.0, 0.0), uvs, mat, (1.0, 0.0, 0.0), (0.0, 0.0, -1.0))


def scroll(d, a, bb, speeds, blend='OPAQUE'):
    return dict(diffuse=d, scroll=dict(normal_a=a, normal_b=bb, speeds=speeds, blend=blend))


def build(base_dat, base_alr):
    b = open(base_alr, 'rb').read()
    sky_clouds = {}
    h = alr.header(b)
    for m in alr.meshes(b, h['roots'][2]):
        e = m['materials'][m['material']]
        if e['shader'] == 'sbtscloud3' and not sky_clouds:
            import struct
            sky_clouds = dict(tex=e['textures'][:3], speeds=struct.unpack_from('<6h', e['raw'], 0x3C))
    labels, cells = label_atlas()
    textures = new + [labels]
    T = {t['name']: ('new', i) for i, t in enumerate(textures)}
    FLAT, ARW = T['scr_flatn'], T['scr_arrows']
    sd = dict(diffuse=T['scr_labels'], normal=None, reflection=None, specular=(0, 0, 0, 0))
    if sky_clouds:
        c3 = [('base', i) for i in sky_clouds['tex']]
        sky = scroll(c3[0], c3[1], c3[2], sky_clouds['speeds'], 'ADD')
    else:
        sky = scroll(ARW, FLAT, FLAT, (130, -72, 118, -131, 80, -68), 'ADD')
    row1 = [
        scroll(ARW, FLAT, FLAT, (600, 0, 0, 0, 0, 0)),
        scroll(ARW, FLAT, FLAT, (0, 600, 0, 0, 0, 0)),
        scroll(ARW, FLAT, FLAT, (-600, -600, 0, 0, 0, 0)),
        scroll(ARW, FLAT, FLAT, (2000, 0, 0, 0, 0, 0)),
        scroll(T['scr_water'], T['scr_wave_n'], T['scr_wave2_n'], (150, 75, 400, 0, 0, -300)),
        scroll(T['scr_lava'], T['scr_lava_n'], T['scr_wave2_n'], (60, 0, 200, 100, -150, 50)),
        scroll(T['scr_energy'], FLAT, FLAT, (0, 1200, 0, 0, 0, 0), 'ADD'),
        scroll(T['scr_water50'], T['scr_wave_n'], T['scr_wave2_n'], (150, 75, 400, 0, 0, -300), 'ALPHA'),
        scroll(T['scr_cloud'], T['scr_hole_a'], T['scr_hole_b'], (0, 0, 300, 0, -200, 100), 'ALPHA'),
        sky,
    ]
    meshes = []
    W, GAP = 60.0, 20.0
    for k, mat in enumerate(row1):
        cx = -(len(row1) - 1) / 2 * (W + GAP) + k * (W + GAP)
        meshes.append(panel(cx, Y + 12, -100.0, W, W, mat))
        meshes.append(label(cx, -100.0, str(k + 1), cells, sd))
    for k, speeds in enumerate([(0, 0, 600, 0, 0, 0), (0, 0, 0, 0, 0, 600)]):
        cx = -300.0 + k * (W + GAP)
        meshes.append(panel(cx, Y + 12, 200.0, W, W, scroll(ARW, T['scr_wave_n'], T['scr_wave2_n'], speeds)))
        meshes.append(label(cx, 200.0, str(11 + k), cells, sd))
    meshes.append(flat(100.0, 200.0, 120.0, Y + 0.5, scroll(T['scr_water50'], T['scr_wave_n'], T['scr_wave2_n'],
                                                          (150, 75, 400, 0, 0, -300), 'ALPHA')))
    meshes.append(label(100.0, 130.0, '13', cells, sd))
    meshes.append(flat(300.0, 200.0, 120.0, Y + 0.5, scroll(T['scr_lava'], T['scr_lava_n'], T['scr_wave2_n'],
                                                          (60, 0, 200, 100, -150, 50))))
    meshes.append(label(300.0, 130.0, '14', cells, sd))

    # floor, edge walls and spawns: the surface test's empty map (floor at y = 100, spawns at z = -300)
    m = sdt.Map()
    sdt.cell_uv = lambda name: cells.get(name.split('\n')[0], cells['FLOOR'])
    m.floor_tiled(sdt.X0, sdt.X1, sdt.Z0, sdt.Z1, Y, 'FLOOR', 0x08)
    X0, X1, Z0, Z1, EH = sdt.X0, sdt.X1, sdt.Z0, sdt.Z1, sdt.EDGE_H
    for p, out in (([(X0, Y - 200, Z0), (X0, EH, Z0), (X1, EH, Z0), (X1, Y - 200, Z0)], (0, 0, 1)),
                   ([(X1, Y - 200, Z1), (X1, EH, Z1), (X0, EH, Z1), (X0, Y - 200, Z1)], (0, 0, -1)),
                   ([(X0, Y - 200, Z1), (X0, EH, Z1), (X0, EH, Z0), (X0, Y - 200, Z0)], (1, 0, 0)),
                   ([(X1, Y - 200, Z0), (X1, EH, Z0), (X1, EH, Z1), (X1, Y - 200, Z1)], (-1, 0, 0))):
        m.quad(p, tuple(float(v) for v in out), 'WALL', 0x10, visible=False)
    stage = [dict(verts=m.verts, tris=m.tris, material=sd)] + meshes
    new_alr, _ = alr_build.rebuild(b, replace={0: stage}, clear=(1,), shadows_for=(0,), textures=textures)
    d = bytearray(open(base_dat, 'rb').read())
    block, stats = collision_build.build_block(m.col)
    d = bytearray(collision_build.append_collision(bytes(d), block))
    dat.clear_placements(d)
    dat.clear_effects(d)
    for layout in dat.spawn_layouts(bytes(d)):
        n = len(layout)
        for i, s in enumerate(layout):
            x = -400.0 + 800.0 * (i + 0.5) / n
            z = -300.0
            s.pos, s.yaw = (x, Y, z), 0.0
            s.orbs = [(x - 30.0, Y, z + 50.0), (x, Y, z + 60.0), (x + 30.0, Y, z + 50.0)]
            dat.write_spawn(d, s)
    return bytes(d), new_alr


def label(cx, z, name, cells, sd):
    """A number plate standing below a panel (y 101-111), facing the spawns."""
    u0, v0, u1, v1 = cells[name]
    p = [(cx - 6, Y + 0.5, z - 1), (cx - 6, Y + 10.5, z - 1), (cx + 6, Y + 10.5, z - 1), (cx + 6, Y + 0.5, z - 1)]
    return quad(p, (0.0, 0.0, -1.0), [(u0, v1), (u0, v0), (u1, v0), (u1, v1)], sd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('base_dat')
    ap.add_argument('base_alr')
    ap.add_argument('out_dir')
    ap.add_argument('--map', default='st03')
    a = ap.parse_args()
    d, m = build(a.base_dat, a.base_alr)
    os.makedirs(a.out_dir, exist_ok=True)
    open(os.path.join(a.out_dir, a.map + '.dat'), 'wb').write(d)
    open(os.path.join(a.out_dir, a.map + '.alr'), 'wb').write(m)
    print('.alr %.1f MB (resources %.1f MiB), .dat %d bytes' % (len(m) / 1e6, alr.header(m)['resource_size'] / 2 ** 20,
                                                                 len(d)))


if __name__ == '__main__':
    main()
