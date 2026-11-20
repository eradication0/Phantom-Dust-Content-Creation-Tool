"""Build a triangle-count stress test map: a flat floor and a grid of dense UV spheres, to find how many stage
triangles the game handles.

    python tools/poly_test_map.py BASE_DAT BASE_ALR OUT_DIR [--count 20] [--tris 50000] [--map st03]

BASE_DAT / BASE_ALR: the game's own files of the map being replaced (Lost Palace, st03). Writes OUT_DIR/<map>.dat
and .alr: the stage model is the floor plus the spheres (background cleared, sky and lighting kept), collision is
the floor with invisible edge walls, the map's objects and effects are removed, spawns face the spheres.
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'addon', 'phantom_dust_stage'))
import surface_test_map as stm  # noqa: E402
from pdstage import alr_build, collision_build, dat  # noqa: E402

RADIUS = 50.0        # game units (5 m in Blender)
GAP = 150.0          # sphere spacing


def checker(size=64, cells=8):
    """BGRA mip levels of a grey checker."""
    def level(w):
        out = bytearray()
        for y in range(w):
            for x in range(w):
                on = ((x * cells // w) + (y * cells // w)) % 2
                v = 170 if on else 120
                out += bytes((v, v, v, 255))
        return bytes(out)
    levels, w = [], size
    while True:
        levels.append(level(w))
        if w == 1:
            return levels
        w //= 2


def sphere(centre, radius, tris):
    """A UV sphere with about `tris` triangles: (verts, tris) with (pos, normal, uv, colour) vertices."""
    # tris = 2 * seg * (rings - 2) + 2 * seg, rings ~ seg / 2  ->  seg ~ sqrt(tris)
    seg = max(8, int(round(math.sqrt(tris))))
    rings = max(4, (tris // (2 * seg)) + 1)
    verts, faces = [], []
    for r in range(rings + 1):
        th = math.pi * r / rings
        for s in range(seg + 1):                        # seam column duplicated for the UVs
            ph = 2 * math.pi * s / seg
            n = (math.sin(th) * math.cos(ph), math.cos(th), math.sin(th) * math.sin(ph))
            p = tuple(centre[k] + radius * n[k] for k in range(3))
            verts.append((p, n, (s / seg * 4, r / rings * 2), (255, 255, 255, 255)))
    row = seg + 1
    for r in range(rings):
        for s in range(seg):
            a, b = r * row + s, r * row + s + 1
            c, d = a + row, b + row
            if r != 0:
                faces.append((a, b, c))       # (b - a) x (c - a) outwards, like the floor
            if r != rings - 1:
                faces.append((b, d, c))
    return verts, faces


def build(base_dat, base_alr, count, tris_each, shadows=True):
    cols = math.ceil(math.sqrt(count))
    rows = math.ceil(count / cols)
    half_x, half_z = cols * GAP / 2 + 150, rows * GAP / 2 + 300
    up = (0.0, 1.0, 0.0)
    mat = dict(diffuse=('new', 0), normal=None, reflection=None, specular=(0, 0, 0, 0))
    white = (255, 255, 255, 255)
    floor_v = [((-half_x, 0.0, -half_z), up, (0, half_z / 50), white), ((-half_x, 0.0, half_z), up, (0, -half_z / 50), white),
               ((half_x, 0.0, half_z), up, (half_x / 25, -half_z / 50), white),
               ((half_x, 0.0, -half_z), up, (half_x / 25, half_z / 50), white)]
    stage = [dict(verts=floor_v, tris=[(0, 1, 3), (1, 2, 3)], material=mat)]
    total = 2
    for i in range(count):
        c, r = i % cols, i // cols
        centre = (-cols * GAP / 2 + (c + 0.5) * GAP, RADIUS, -rows * GAP / 2 + (r + 0.5) * GAP + 150)
        v, f = sphere(centre, RADIUS, tris_each)
        stage.append(dict(verts=v, tris=f, material=mat))
        total += len(f)

    b = open(base_alr, 'rb').read()
    new_alr, _ = alr_build.rebuild(b, replace={0: stage}, clear=(1,), shadows_for=(0,) if shadows else (),   # as the add-on exports
                                   textures=[dict(name='pd_polytest', width=64, height=64, levels=checker())])

    p = [q[0] for q in floor_v]
    col = [(p[0], p[1], p[3], 0x08), (p[1], p[2], p[3], 0x08)]
    corners = [(-half_x, -half_z), (-half_x, half_z), (half_x, half_z), (half_x, -half_z)]
    for (ax, az), (bx, bz) in zip(corners, corners[1:] + corners[:1]):
        a0, a1, b0, b1 = (ax, 0.0, az), (ax, stm.WALL_H, az), (bx, 0.0, bz), (bx, stm.WALL_H, bz)
        for t in ((a0, a1, b0), (a1, b1, b0)):
            n = stm._normal(*t)
            inward = (-(t[0][0] + t[2][0]) / 2, 0.0, -(t[0][2] + t[2][2]) / 2)
            if sum(n[k] * inward[k] for k in range(3)) < 0:
                t = (t[0], t[2], t[1])
            col.append(t + (stm.EDGE,))
    d = bytearray(open(base_dat, 'rb').read())
    block, _stats = collision_build.build_block(col)
    d = bytearray(collision_build.append_collision(bytes(d), block))
    dat.clear_placements(d)
    dat.clear_effects(d)
    for layout in dat.spawn_layouts(bytes(d)):
        n = len(layout)
        for i, s in enumerate(layout):
            x = -half_x + 2 * half_x * (i + 0.5) / n
            z = -half_z + 100.0
            s.pos, s.yaw = (x, 0.0, z), 0.0
            s.orbs = [(x - 40.0, 0.0, z + 60.0), (x, 0.0, z + 80.0), (x + 40.0, 0.0, z + 60.0)]
            dat.write_spawn(d, s)
    return bytes(d), new_alr, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('base_dat')
    ap.add_argument('base_alr')
    ap.add_argument('out_dir')
    ap.add_argument('--map', default='st03')
    ap.add_argument('--count', type=int, default=20)
    ap.add_argument('--tris', type=int, default=50000)
    ap.add_argument('--no-shadows', action='store_true', help='leave out the stage shadow model')
    a = ap.parse_args()
    d, m, total = build(a.base_dat, a.base_alr, a.count, a.tris, not a.no_shadows)
    os.makedirs(a.out_dir, exist_ok=True)
    open(os.path.join(a.out_dir, a.map + '.dat'), 'wb').write(d)
    open(os.path.join(a.out_dir, a.map + '.alr'), 'wb').write(m)
    print('%d spheres, %d stage triangles, .alr %.1f MB' % (a.count, total, len(m) / 1e6))


if __name__ == '__main__':
    main()
