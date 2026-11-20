"""Test map for the points where Tinkerer_Red's surface research differs from ours (FORMATS.md / surfaces.py).

    python tools/surface_diff_test_map.py BASE_DAT BASE_ALR OUT_DIR [--map st03]

Main floor at y = 100 (surface 08). From the spawns (near end, facing +z):
  row 1  floor pads 00 | 02 | 03          walk on 00 (solid?), blast 02 and 03 (pits?)
  row 2  walls 08 | 12 | 14 | 1F          200 tall, gaps between them
  row 3  ramp to a floor at y = +30 (left), ramp to a floor at y = -50 (right): kill height 0?
"""
import argparse
import colorsys
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'addon', 'phantom_dust_stage'))
from pdstage import alr_build, collision_build, dat  # noqa: E402

Y = 100.0
WALL_T = 4.0
X0, X1, Z0, Z1 = -700.0, 700.0, -400.0, 1300.0
EDGE_H = 600.0

CELLS = ['FLOOR', 'WALL', '00', '02', '03', '08\nCONTROL', '12', '14', '1F', 'TO +30', 'TO -50', '+30', '-50',
         'START']
N = 4                                    # 4 x 4 atlas
SIZE = 1024


def atlas():
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new('RGBA', (SIZE, SIZE), (60, 60, 60, 255))
    d = ImageDraw.Draw(im)
    c = SIZE // N
    try:
        big = ImageFont.load_default(size=int(c * 0.30))
    except TypeError:
        big = ImageFont.load_default()
    for i, name in enumerate(CELLS):
        x, y = (i % N) * c, (i // N) * c
        if name == 'FLOOR':
            col = (150, 150, 150)
        elif name == 'WALL':
            col = (110, 110, 120)
        else:
            r, g, b = colorsys.hsv_to_rgb((i * 0.61803) % 1.0, 0.5, 0.9)
            col = (int(r * 255), int(g * 255), int(b * 255))
        d.rectangle([x, y, x + c - 1, y + c - 1], fill=col + (255,), outline=(20, 20, 20, 255), width=8)
        if name not in ('FLOOR', 'WALL'):
            bb = d.multiline_textbbox((0, 0), name, font=big, align='center')
            d.multiline_text((x + (c - bb[2]) / 2, y + (c - bb[3]) / 2), name, fill=(10, 10, 10, 255), font=big,
                             align='center')
    levels, cur, w = [], im, SIZE
    while True:
        r_, g_, b_, a_ = cur.split()
        levels.append(Image.merge('RGBA', (b_, g_, r_, a_)).tobytes())
        if w == 1:
            break
        w //= 2
        cur = im.resize((w, w), Image.BOX)
    return levels, im


def cell_uv(name):
    i = CELLS.index(name)
    u0, v0 = (i % N) / N, (i // N) / N
    return u0 + 0.004, v0 + 0.004, u0 + 1 / N - 0.004, v0 + 1 / N - 0.004


def _sub(a, b):
    return [a[k] - b[k] for k in range(3)]


def _cross(u, v):
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


class Map:
    def __init__(self):
        self.verts, self.tris, self.col = [], [], []

    def quad(self, p, out, cell, surface, visible=True, tile=None):
        """p: corners [bottom-left, top-left, top-right, bottom-right] as seen from the side `out` points to
        (for floors: near-left, far-left, far-right, near-right seen from above, facing +z)."""
        tris = [(0, 1, 3), (1, 2, 3)]
        n = _cross(_sub(p[1], p[0]), _sub(p[3], p[0]))
        if sum(n[k] * out[k] for k in range(3)) < 0:
            tris = [(0, 3, 1), (1, 3, 2)]
        if surface is not None:
            for a, b, c in tris:
                self.col.append((p[a], p[b], p[c], surface))
        if visible:
            u0, v0, u1, v1 = cell_uv(cell)
            uvs = [(u0, v1), (u0, v0), (u1, v0), (u1, v1)]
            k = len(self.verts)
            self.verts += [(p[i], out, uvs[i], (255, 255, 255, 255)) for i in range(4)]
            self.tris += [(k + a, k + b, k + c) for a, b, c in tris]

    def floor(self, xa, xb, za, zb, y, cell, surface):
        self.quad([(xa, y, za), (xa, y, zb), (xb, y, zb), (xb, y, za)], (0.0, 1.0, 0.0), cell, surface)

    def floor_tiled(self, xa, xb, za, zb, y, cell, surface, step=200.0):
        x = xa
        while x < xb - 1e-3:
            z = za
            while z < zb - 1e-3:
                self.floor(x, min(x + step, xb), z, min(z + step, zb), y, cell, surface)
                z += step
            x += step

    def wall_box(self, xa, xb, z, y0, y1, cell, surface):
        """A thin two-sided wall across x at depth z: label on the side facing the spawns (-z)."""
        za, zb = z - WALL_T / 2, z + WALL_T / 2
        self.quad([(xa, y0, za), (xa, y1, za), (xb, y1, za), (xb, y0, za)], (0.0, 0.0, -1.0), cell, surface)
        self.quad([(xb, y0, zb), (xb, y1, zb), (xa, y1, zb), (xa, y0, zb)], (0.0, 0.0, 1.0), cell, surface)
        self.quad([(xa, y0, zb), (xa, y1, zb), (xa, y1, za), (xa, y0, za)], (-1.0, 0.0, 0.0), 'WALL', surface)
        self.quad([(xb, y0, za), (xb, y1, za), (xb, y1, zb), (xb, y0, zb)], (1.0, 0.0, 0.0), 'WALL', surface)
        self.quad([(xa, y1, za), (xa, y1, zb), (xb, y1, zb), (xb, y1, za)], (0.0, 1.0, 0.0), 'WALL', surface)

    def side(self, x, za, zb, ya, yb, out, cell='WALL', surface=0x08):
        """Vertical wall along z at x, from y ya up to yb, facing `out`."""
        if out[0] > 0:
            p = [(x, ya, zb), (x, yb, zb), (x, yb, za), (x, ya, za)]
        else:
            p = [(x, ya, za), (x, yb, za), (x, yb, zb), (x, ya, zb)]
        self.quad(p, out, cell, surface)


def build(base_dat, base_alr):
    m = Map()
    # --- near area: z -400..400, floor at Y with pads 00 / 02 / 03 at z 0..200
    pads = {(-500.0, -300.0): ('00', 0x00), (-100.0, 100.0): ('02', 0x02), (300.0, 500.0): ('03', 0x03)}
    x = X0
    while x < X1 - 1e-3:
        z = Z0
        while z < 400.0 - 1e-3:
            m.floor(x, x + 200.0, z, z + 200.0, Y, 'START' if z == Z0 else 'FLOOR', 0x08)
            z += 200.0
        x += 200.0
    # pads replace the floor cells they sit on: rebuild those cells
    m.col = [t for t in m.col if not _in_pad(t, pads)]
    m.verts, m.tris = _drop_visual(m, pads)
    for (xa, xb), (cell, s) in pads.items():
        m.floor(xa, xb, 0.0, 200.0, Y, cell, s)
    # --- wall row at z 500: 08 | 12 | 14 | 1F, 200 tall, 150 gaps
    m.floor_tiled(X0, X1, 400.0, 800.0, Y, 'FLOOR', 0x08)
    for xa, cell, s in ((-550.0, '08\nCONTROL', 0x08), (-250.0, '12', 0x12), (50.0, '14', 0x14),
                        (350.0, '1F', 0x1F)):
        m.wall_box(xa, xa + 200.0, 600.0, Y, Y + 200.0, cell, s)
    # --- back: z 800..1300. Left: ramp 800..1000 down to +30, floor 1000..1300. Right: same down to -50.
    m.floor_tiled(X0, -500.0, 800.0, Z1, Y, 'FLOOR', 0x08)
    m.floor_tiled(-100.0, 100.0, 800.0, Z1, Y, 'FLOOR', 0x08)
    m.floor_tiled(500.0, X1, 800.0, Z1, Y, 'FLOOR', 0x08)
    for xa, xb, low, rc, fc in ((-500.0, -100.0, 30.0, 'TO +30', '+30'), (100.0, 500.0, -50.0, 'TO -50', '-50')):
        m.quad([(xa, Y, 800.0), (xa, low, 1000.0), (xb, low, 1000.0), (xb, Y, 800.0)], (0.0, 1.0, 0.0), rc, 0x08)
        m.floor_tiled(xa, xb, 1000.0, Z1, low, fc, 0x08)
        # side walls of the sunken lane (from its floor up to the main floor)
        m.side(xa, 800.0, Z1, low, Y, (1.0, 0.0, 0.0))
        m.side(xb, 800.0, Z1, low, Y, (-1.0, 0.0, 0.0))
    # invisible edge walls (10), facing inwards
    for p, out in (([(X0, Y - 200, Z0), (X0, EDGE_H, Z0), (X1, EDGE_H, Z0), (X1, Y - 200, Z0)], (0, 0, 1)),
                   ([(X1, Y - 200, Z1), (X1, EDGE_H, Z1), (X0, EDGE_H, Z1), (X0, Y - 200, Z1)], (0, 0, -1)),
                   ([(X0, Y - 200, Z1), (X0, EDGE_H, Z1), (X0, EDGE_H, Z0), (X0, Y - 200, Z0)], (1, 0, 0)),
                   ([(X1, Y - 200, Z0), (X1, EDGE_H, Z0), (X1, EDGE_H, Z1), (X1, Y - 200, Z1)], (-1, 0, 0))):
        m.quad(p, tuple(float(v) for v in out), 'WALL', 0x10, visible=False)

    levels, preview = atlas()
    b = open(base_alr, 'rb').read()
    stage = [dict(verts=m.verts, tris=m.tris,
                  material=dict(diffuse=('new', 0), normal=None, reflection=None, specular=(0, 0, 0, 0)))]
    new_alr, _ = alr_build.rebuild(b, replace={0: stage}, clear=(1,), shadows_for=(0,),
                                   textures=[dict(name='pd_difftest', width=SIZE, height=SIZE, levels=levels)])
    d = bytearray(open(base_dat, 'rb').read())
    block, stats = collision_build.build_block(m.col)
    d = bytearray(collision_build.append_collision(bytes(d), block))
    dat.clear_placements(d)
    dat.clear_effects(d)
    for layout in dat.spawn_layouts(bytes(d)):
        n = len(layout)
        for i, s in enumerate(layout):
            x = -500.0 + 1000.0 * (i + 0.5) / n
            z = -300.0
            s.pos, s.yaw = (x, Y, z), 0.0
            s.orbs = [(x - 40.0, Y, z + 60.0), (x, Y, z + 80.0), (x + 40.0, Y, z + 60.0)]
            dat.write_spawn(d, s)
    return bytes(d), new_alr, stats, preview


def _in_pad(t, pads):
    cx = sum(p[0] for p in t[:3]) / 3
    cz = sum(p[2] for p in t[:3]) / 3
    return 0.0 < cz < 200.0 and any(xa < cx < xb for xa, xb in pads)


def _drop_visual(m, pads):
    verts, tris = [], []
    for k in range(0, len(m.verts), 4):
        q = m.verts[k:k + 4]
        cx = sum(v[0][0] for v in q) / 4
        cz = sum(v[0][2] for v in q) / 4
        if 0.0 < cz < 200.0 and any(xa < cx < xb for xa, xb in pads):
            continue
        base = len(verts)
        verts += q
        tris += [(base + a - k, base + b - k, base + c - k) for a, b, c in m.tris[k // 2:k // 2 + 2]]
    return verts, tris


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('base_dat')
    ap.add_argument('base_alr')
    ap.add_argument('out_dir')
    ap.add_argument('--map', default='st03')
    a = ap.parse_args()
    d, m, stats, preview = build(a.base_dat, a.base_alr)
    os.makedirs(a.out_dir, exist_ok=True)
    open(os.path.join(a.out_dir, a.map + '.dat'), 'wb').write(d)
    open(os.path.join(a.out_dir, a.map + '.alr'), 'wb').write(m)
    preview.save(os.path.join(a.out_dir, a.map + '_labels.png'))
    print('%d collision triangles, %d bytes dat, %d bytes alr' % (stats['triangles'], len(d), len(m)))


if __name__ == '__main__':
    main()
