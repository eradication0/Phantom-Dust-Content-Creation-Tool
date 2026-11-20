"""Build a surface-type test map: a flat grid of square pads, one per collision surface type, each labelled with
its number, so footsteps / landing / impact effects can be compared in game.

    python tools/surface_test_map.py BASE_DAT BASE_ALR OUT_DIR [--values 01,02,...] [--map st03]

BASE_DAT / BASE_ALR: the game's own files of the map being replaced (Lost Palace, st03, is the test map).
Writes OUT_DIR/<map>.dat and .alr. The map's own objects and effects are removed, its background is cleared, the
sky and lighting stay. Pads are in game space (y up, left-handed); labels read upright when facing +z, the way
every spawn faces.
"""
import argparse
import io
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'addon', 'phantom_dust_stage'))
from pdstage import alr, alr_build, collision_build, dat  # noqa: E402

# Every surface type the battle maps use (see addon/phantom_dust_stage/surfaces.py)
ALL_USED = [0x01, 0x02, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0D, 0x10, 0x12, 0x14, 0x16, 0x18,
            0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x20]

PAD = 200.0          # pad size in game units (a player is about 30 wide)
COLS = 6
WALL_H = 300.0
EDGE = 0x10          # invisible edge walls, as the game's maps use


def label_atlas(values, cols, rows, size=512, tested=(), start=False):
    """One texture: a cell per pad with its number on a colour of its own (white text and outline = already
    tested), plus a START cell for the spawn strip when `start`. Returns (w, h, levels, image)."""
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new('RGBA', (size, size), (40, 40, 40, 255))
    d = ImageDraw.Draw(im)
    cw, ch = size // cols, size // rows
    try:
        font = ImageFont.load_default(size=int(ch * 0.42))
        small = ImageFont.load_default(size=int(ch * 0.14))
    except TypeError:
        font = small = ImageFont.load_default()
    cells = list(values) + (['START'] if start else [])
    for i, v in enumerate(cells):
        cx, cy = (i % cols) * cw, (i // cols) * ch
        if v == 'START':
            d.rectangle([cx, cy, cx + cw - 1, cy + ch - 1], fill=(90, 90, 90, 255), outline=(20, 20, 20, 255), width=3)
            tw, th = d.textbbox((0, 0), 'START', font=small)[2:]
            d.text((cx + (cw - tw) / 2, cy + (ch - th) / 2), 'START', fill=(230, 230, 230, 255), font=small)
            continue
        ink = (255, 255, 255, 255) if v in tested else (15, 15, 15, 255)
        hue = (i * 0.61803) % 1.0
        import colorsys
        r, g, b = (int(255 * c) for c in colorsys.hsv_to_rgb(hue, 0.45, 0.85))
        d.rectangle([cx, cy, cx + cw - 1, cy + ch - 1], fill=(r, g, b, 255),
                    outline=(255, 255, 255, 255) if v in tested else (20, 20, 20, 255), width=6 if v in tested else 3)
        text = '%02X' % v
        tw, th = d.textbbox((0, 0), text, font=font)[2:]
        d.text((cx + (cw - tw) / 2, cy + (ch - th) / 2 - ch * 0.08), text, fill=ink, font=font,
               stroke_width=0 if v in tested else 0)
        sub = 'tested' if v in tested else 'NEW'
        sw = d.textbbox((0, 0), sub, font=small)[2]
        d.text((cx + (cw - sw) / 2, cy + ch * 0.72), sub, fill=ink, font=small)
    levels = []
    w = size
    cur = im
    while True:
        r_, g_, b_, a_ = cur.split()
        levels.append(Image.merge('RGBA', (b_, g_, r_, a_)).tobytes())       # BGRA, top row first
        if w == 1:
            break
        w //= 2
        cur = im.resize((w, w), Image.BOX)
    return size, size, levels, im


def build(base_dat, base_alr, values, tested=(), start_strip=False, edge=EDGE):
    """start_strip: players spawn on a separate plain strip (surface 08) in front of the pads instead of on them
    (safer when some pads may be fall-out surfaces)."""
    cols = COLS
    rows = (len(values) + (1 if start_strip else 0) + cols - 1) // cols
    w, h, levels, preview = label_atlas(values, cols, rows, tested=tested, start=start_strip)
    # grid centred on the origin; row 0 is the far end (+z), so labels read from the spawns at the near end
    x0 = -cols * PAD / 2
    z_far = rows * PAD / 2
    up = (0.0, 1.0, 0.0)
    verts, tris, col_tris = [], [], []
    for i, v in enumerate(values):
        c, r = i % cols, i // cols
        xa, xb = x0 + c * PAD, x0 + (c + 1) * PAD
        za, zb = z_far - (r + 1) * PAD, z_far - r * PAD        # zb = far edge of this pad
        u0, u1 = c / cols, (c + 1) / cols
        v0, v1 = r / rows, (r + 1) / rows                         # texture v runs down = towards -z
        k = len(verts)
        # corners: near-left, far-left, far-right, near-right (left = -x when facing +z)
        verts += [((xa, 0.0, za), up, (u0, v1)), ((xa, 0.0, zb), up, (u0, v0)),
                  ((xb, 0.0, zb), up, (u1, v0)), ((xb, 0.0, za), up, (u1, v1))]
        # winding: (b - a) x (c - a) points up (+y), as in the game's own floors
        tris += [(k, k + 1, k + 3), (k + 1, k + 2, k + 3)]
        p = [q[0] for q in verts[k:k + 4]]
        col_tris += [(p[0], p[1], p[3], v), (p[1], p[2], p[3], v)]
    if start_strip:                                  # a START strip in front of the grid (texture: the START cell)
        i = len(values)
        u0, u1 = (i % cols) / cols, (i % cols + 1) / cols
        v0, v1 = (i // cols) / rows, (i // cols + 1) / rows
        for j in range(len(values), rows * cols):    # fill the grid's empty cells: plain floor, no holes
            c, r = j % cols, j // cols
            fxa, fxb = x0 + c * PAD, x0 + (c + 1) * PAD
            fza, fzb = z_far - (r + 1) * PAD, z_far - r * PAD
            k = len(verts)
            verts += [((fxa, 0.0, fza), up, (u0, v1)), ((fxa, 0.0, fzb), up, (u0, v0)),
                      ((fxb, 0.0, fzb), up, (u1, v0)), ((fxb, 0.0, fza), up, (u1, v1))]
            tris += [(k, k + 1, k + 3), (k + 1, k + 2, k + 3)]
            q = [x[0] for x in verts[k:k + 4]]
            col_tris += [(q[0], q[1], q[3], 0x08), (q[1], q[2], q[3], 0x08)]
        za, zb = -z_far - PAD, -z_far
        xa, xb = x0, -x0
        k = len(verts)
        verts += [((xa, 0.0, za), up, (u0, v1)), ((xa, 0.0, zb), up, (u0, v0)),
                  ((xb, 0.0, zb), up, (u1, v0)), ((xb, 0.0, za), up, (u1, v1))]
        tris += [(k, k + 1, k + 3), (k + 1, k + 2, k + 3)]
        p = [q[0] for q in verts[k:k + 4]]
        col_tris += [(p[0], p[1], p[3], 0x08), (p[1], p[2], p[3], 0x08)]
    # invisible edge walls, facing inwards
    xa, xb, za, zb = x0, -x0, -z_far - (PAD if start_strip else 0.0), z_far
    corners = [(xa, za), (xa, zb), (xb, zb), (xb, za)]
    for (ax, az), (bx, bz) in zip(corners, corners[1:] + corners[:1]):
        a0, a1 = (ax, 0.0, az), (ax, WALL_H, az)
        b0, b1 = (bx, 0.0, bz), (bx, WALL_H, bz)
        for t in ((a0, a1, b0), (a1, b1, b0)):
            n = _normal(*t)
            zc = (za + zb) / 2
            inward = (-(t[0][0] + t[2][0]) / 2, 0.0, zc - (t[0][2] + t[2][2]) / 2)
            if sum(n[k] * inward[k] for k in range(3)) < 0:
                t = (t[0], t[2], t[1])
            col_tris.append(t + (edge,))

    # .alr: the stage model (root 0) replaced, background (root 1) cleared
    b = open(base_alr, 'rb').read()
    stage = [dict(verts=[(p, n, uv, (255, 255, 255, 255)) for p, n, uv in verts], tris=tris,
                  material=dict(diffuse=('new', 0), normal=None, reflection=None, specular=(0, 0, 0, 0)))]
    new_alr, _ = alr_build.rebuild(b, replace={0: stage}, clear=(1,), shadows_for=(0,),
                                   textures=[dict(name='pd_surftest', width=w, height=h, levels=levels)])

    # .dat: collision, clean slate, spawns on the near row facing +z
    d = bytearray(open(base_dat, 'rb').read())
    block, stats = collision_build.build_block(col_tris)
    d = bytearray(collision_build.append_collision(bytes(d), block))
    dat.clear_placements(d)
    dat.clear_effects(d)
    for layout in dat.spawn_layouts(bytes(d)):
        n = len(layout)
        for i, s in enumerate(layout):
            x = x0 + cols * PAD * (i + 0.5) / n                 # spread along the near row
            z = -z_far - PAD / 2 if start_strip else -z_far + PAD / 2
            s.pos, s.yaw = (x, 0.0, z), 0.0
            s.orbs = [(x - 40.0, 0.0, z + 60.0), (x, 0.0, z + 80.0), (x + 40.0, 0.0, z + 60.0)]
            dat.write_spawn(d, s)
    return bytes(d), new_alr, stats, preview


def _normal(a, b, c):
    u = [b[k] - a[k] for k in range(3)]
    v = [c[k] - a[k] for k in range(3)]
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('base_dat')
    ap.add_argument('base_alr')
    ap.add_argument('out_dir')
    ap.add_argument('--map', default='st03')
    ap.add_argument('--values', default='', help='hex list, or "all" (00-20, the whole range the game reads); '
                                                 'default: every surface type the maps use')
    ap.add_argument('--tested', default='', help='hex list of values already tested: white text and outline')
    ap.add_argument('--start-strip', action='store_true', help='spawn on a plain strip in front of the pads')
    ap.add_argument('--edge', default='10', help='surface of the invisible edge walls (hex)')
    a = ap.parse_args()
    values = list(range(0x21)) if a.values == 'all' else \
        [int(x, 16) for x in a.values.split(',')] if a.values else ALL_USED
    tested = {int(x, 16) for x in a.tested.split(',')} if a.tested else set()
    d, m, stats, preview = build(a.base_dat, a.base_alr, values, tested, a.start_strip, int(a.edge, 16))
    os.makedirs(a.out_dir, exist_ok=True)
    open(os.path.join(a.out_dir, a.map + '.dat'), 'wb').write(d)
    open(os.path.join(a.out_dir, a.map + '.alr'), 'wb').write(m)
    preview.save(os.path.join(a.out_dir, a.map + '_surface_labels.png'))
    print('%d pads (%s), %d collision triangles' % (len(values), ' '.join('%02X' % v for v in values),
                                                     stats['triangles']))


if __name__ == '__main__':
    main()
