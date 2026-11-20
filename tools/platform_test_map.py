"""Build a moving-platform test map: numbered pads, each with a platform object that has an animation, to find
out which object types play an animation and when (from the start, or only once broken), and whether players
can ride them.

    python tools/platform_test_map.py BASE_DAT BASE_ALR OUT_DIR [--map st03]

The game's moving objects (Storm Refinery's container, type 2-6; Spiral Highway's iron roads, 2-26) play their
animation once broken. Each platform here has the same looping motion in its intact state, its broken state or
both, so one run shows which slots the game uses. Platforms hover 3 m above their pad.
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'addon', 'phantom_dust_stage'))
import surface_test_map as stm  # noqa: E402
from effect_test_map import label_atlas_for  # noqa: E402
from pdstage import alr_build, anim_build, collision_build, dat, objects_build  # noqa: E402

FRAMES = 180               # one loop
HEIGHT = 30.0              # platform bottom above the floor (game units)
SIZE, THICK = 120.0, 15.0

# (label, (category, type), motion, states with the animation: 0 intact, 1 broken)
PLATFORMS = [
    ('2-26 up/down intact', (2, 26), 'updown', (0,)),
    ('2-26 slide intact', (2, 26), 'slide', (0,)),
    ('2-26 spin intact', (2, 26), 'spin', (0,)),
    ('2-26 up/down hit', (2, 26), 'updown', (1,)),
    ('2-26 slide hit', (2, 26), 'slide', (1,)),
    ('2-26 both', (2, 26), 'circle', (0, 1)),
    ('2-6 up/down intact', (2, 6), 'updown', (0,)),
    ('2-6 slide hit', (2, 6), 'slide', (1,)),
    ('2-6 both', (2, 6), 'circle', (0, 1)),
]


def motion(kind):
    """Keys for one loop: T=[(frame, x, y, z)], R=[(frame, x, y, z, w)] in the object's game space."""
    T, R = [], []
    for f in range(0, FRAMES + 1, 2):
        a = 2 * math.pi * f / FRAMES
        pos, ang = (0.0, 0.0, 0.0), 0.0
        if kind == 'updown':
            pos = (0.0, 60.0 * (1 - math.cos(a)) / 2, 0.0)
        elif kind == 'slide':
            pos = (70.0 * math.sin(a), 0.0, 0.0)
        elif kind == 'circle':
            pos = (60.0 * math.sin(a), 0.0, 60.0 * (1 - math.cos(a)))
        elif kind == 'spin':
            ang = a
        T.append((float(f), *pos))
        R.append((f, 0.0, math.sin(ang / 2), 0.0, math.cos(ang / 2)))          # about the up axis (y)
    return [dict(node=0, last=float(FRAMES), T=T, R=R)]


def box(lo, hi, mat):
    """A box mesh (game space, y up) with outward faces: (b - a) x (c - a) pointing out, as the floors."""
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    faces = [((0, 1, 0), [(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)]),
             ((0, -1, 0), [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)]),
             ((1, 0, 0), [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]),
             ((-1, 0, 0), [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)]),
             ((0, 0, 1), [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]),
             ((0, 0, -1), [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)])]
    verts, tris, col = [], [], []
    for n, q in faces:
        k = len(verts)
        for j, p in enumerate(q):
            verts.append((p, n, ((0, 0), (0, 1), (1, 1), (1, 0))[j], (255, 255, 255, 255)))
        tris += [(k, k + 1, k + 3), (k + 1, k + 2, k + 3)]
        col += [(q[0], q[1], q[3], 0x08), (q[1], q[2], q[3], 0x08)]
    return dict(verts=verts, tris=tris, material=mat), col


def stripes(size=64):
    out = bytearray()
    for y in range(size):
        for x in range(size):
            on = ((x + y) * 6 // size) % 2
            out += bytes((20, 190, 230, 255)) if on else bytes((25, 25, 25, 255))     # BGRA: yellow / black
    levels, w, cur = [bytes(out)], size, bytes(out)
    while w > 1:
        nw = w // 2
        nxt = bytearray()
        for y in range(nw):
            for x in range(nw):
                px = [cur[4 * ((2 * y + dy) * w + 2 * x + dx):][:4] for dy in (0, 1) for dx in (0, 1)]
                nxt += bytes(sum(p[c] for p in px) // 4 for c in range(4))
        levels.append(bytes(nxt))
        cur, w = bytes(nxt), nw
    return levels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('base_dat')
    ap.add_argument('base_alr')
    ap.add_argument('out_dir')
    ap.add_argument('--map', default='st03')
    a = ap.parse_args()
    labels = [str(i + 1) + ' ' + p[0] for i, p in enumerate(PLATFORMS)]
    stm.label_atlas = label_atlas_for([p[0].replace('/', ' / ') for p in PLATFORMS])
    old_pad = stm.PAD
    stm.PAD = 300.0                                        # room for the motions
    d, m, _stats, _preview = stm.build(a.base_dat, a.base_alr, [0x08] * len(PLATFORMS))

    # platform models (intact = broken = the same box, one root node), added to the floor's model file
    mat = dict(diffuse=('new', 0), normal=None, reflection=None, specular=(0, 0, 0, 0))
    mesh, col = box((-SIZE / 2, 0.0, -SIZE / 2), (SIZE / 2, THICK, SIZE / 2), mat)
    model = dict(meshes=[mesh], nodes=[dict(flags=0x0004, values=(0, 0, 0, 0))])
    new_alr, stats = alr_build.rebuild(m, add_models=[model, model],
                                       textures=[dict(name='pd_platform', width=64, height=64, levels=stripes())])
    intact_root, broken_root = stats['added_roots'][:2]

    cols = stm.COLS
    rows = (len(PLATFORMS) + cols - 1) // cols
    x0, z_far = -cols * stm.PAD / 2, rows * stm.PAD / 2
    objects, placements = [], []
    for i, (label, (cat, typ), kind, states) in enumerate(PLATFORMS):
        anim = anim_build.write(motion(kind))
        objects.append(dict(name='pd_platform_%d' % (i + 1), roots=(intact_root, broken_root, None),
                            collisions=[col, col, None], anims=[anim if s in states else None for s in range(3)]))
        c, r = i % cols, i // cols
        placements.append(dict(object=i, category=cat, type=typ,
                               pos=(x0 + (c + 0.5) * stm.PAD, HEIGHT, z_far - (r + 0.5) * stm.PAD), rot=(0, 0, 0)))
    d = objects_build.add_objects(d, objects, placements)
    stm.PAD = old_pad
    os.makedirs(a.out_dir, exist_ok=True)
    open(os.path.join(a.out_dir, a.map + '.dat'), 'wb').write(d)
    open(os.path.join(a.out_dir, a.map + '.alr'), 'wb').write(new_alr)
    for t in labels:
        print(t)



if __name__ == '__main__':
    main()
