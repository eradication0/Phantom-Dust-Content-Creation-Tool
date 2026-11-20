"""Light map test: do the hub's light-map shader (lbts, vertex format 0x1F, two UV maps) work on a battle stage?

    python tools/lightmap_test_map.py BASE_DAT BASE_ALR HUB_ALR OUT_DIR [--map st03]

BASE_DAT / BASE_ALR: the game's own files of the map being replaced (Lost Palace, st03). HUB_ALR: st09_01.alr
(the underground hub), where the lbts material and the light map ug_1_light1 are copied from.

The stage is four floor pads in a row, all with the same tiling checker texture on UV0 (8 x 8 repeats):
  1  lbts, the hub's own light map ug_1_light1 stretched over the pad (UV1 = 0-1)
  2  lbts, a test light map: white with black stripes, a red, a green and a blue square, a dark corner
  3  lbts, a plain white light map (should look like pad 4 plus the ambient)
  4  sd, the normal stage shader with white vertex light (for comparison)
Expected if lbts works: pads 1-3 show the checker sharp (tiling UV0) with the light map laid over it (UV1).
Collision: the floor with invisible edge walls. Objects and effects removed, spawns face the pads.
Not part of the add-on (a standalone test, like the other tools/*_test_map.py).
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'addon', 'phantom_dust_stage'))
import surface_test_map as stm  # noqa: E402
from pdstage import alr, alr_build, collision_build, dat  # noqa: E402

LBTS_FORMAT, LBTS_SIZE, LBTS_MASK = 0x1F, 0x20, 0x0010304F
PAD = 300.0          # pad size (game units; 30 m)
GAP = 40.0


def mips(level0, w):
    """BGRA mip chain from a function (x, y, w) -> (b, g, r, a) at the top level, box-filtered down."""
    lv = [bytes(b for y in range(w) for x in range(w) for b in level0(x, y, w))]
    while w > 1:
        prev, w2 = lv[-1], w // 2
        out = bytearray()
        for y in range(w2):
            for x in range(w2):
                for c in range(4):
                    s = sum(prev[((2 * y + dy) * w + 2 * x + dx) * 4 + c] for dy in (0, 1) for dx in (0, 1))
                    out.append(s // 4)
        lv.append(bytes(out))
        w = w2
    return lv


def checker(x, y, w):
    v = 200 if ((x * 4 // w) + (y * 4 // w)) % 2 else 110
    edge = x % (w // 4) == 0 or y % (w // 4) == 0
    return (40, 40, 40, 255) if edge else (v, v, v, 255)


def test_light(x, y, w):
    """White, black diagonal stripes in one half, red / green / blue squares, a dark corner. Alpha 0 (the
    shader adds the light map once more by its alpha)."""
    u, v = x / w, y / w
    col = (255, 255, 255)
    if u < 0.5 and int((u + v) * 16) % 2:
        col = (0, 0, 0)
    for (cu, cv, c) in ((0.6, 0.1, (0, 0, 255)), (0.6, 0.4, (0, 255, 0)), (0.6, 0.7, (255, 0, 0))):
        if cu <= u < cu + 0.2 and cv <= v < cv + 0.2:
            col = c                                  # BGR order: (0,0,255) is red
    if u > 0.85 and v > 0.85:
        col = (30, 30, 30)
    return col + (0,)


def flat(x, y, w):
    return (255, 128, 128, 255)                       # BGRA of (0.5, 0.5, 1): a flat normal


def hub_light(hub):
    """The hub's light map as a new texture (DXT5 levels copied as they are)."""
    t = next(t for t in alr.textures(hub) if t['name'] == 'ug_1_light1')
    start = alr.header(hub)['resource_offset'] + t['offset']
    data = hub[start:start + t['size']]
    levels, w, o = [], t['width'], 0
    for _ in range(t['mips']):
        n = max(1, (w + 3) // 4) ** 2 * 16
        levels.append(data[o:o + n])
        o += n
        w = max(1, w // 2)
    return dict(name='pd_lmhub', width=t['width'], height=t['height'], levels=levels, format=t['raw_format'])


def lbts_material(hub):
    for m in alr.meshes(hub, alr.header(hub)['roots'][0]):
        mat = m['materials'][m['material']]
        if mat['shader'] == 'lbts':
            return bytes(mat['raw'])
    raise SystemExit('no lbts material in the hub file')


def pad_lbts(x0, z0, material, lightmap_ref, diffuse_ref, normal_ref):
    """One floor pad as a raw lbts mesh: format 0x1F vertices, UV0 tiling 8 x 8, UV1 = 0-1."""
    up, tangent, binormal = (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)
    corners = [(0, 0), (0, 1), (1, 1), (1, 0)]
    vb = bytearray()
    for (a, c) in corners:
        pos = (x0 + a * PAD, 0.0, z0 + c * PAD)
        u0, v0 = int(a * 8 * 4096) & 0xFFFF, int(c * 8 * 4096) & 0xFFFF
        u1, v1 = int(round(a * 4095)), int(round(c * 4095))
        vb += struct.pack('<3fIHHIIHH', *pos, alr_build.pack_normal(up), min(u0, 0xFFFF), min(v0, 0xFFFF),
                          alr_build.pack_normal(tangent), alr_build.pack_normal(binormal), u1, v1)
    assert len(vb) == 4 * LBTS_SIZE
    return dict(raw=dict(material=material, format=LBTS_FORMAT, vertex_size=LBTS_SIZE, vertex_bytes=bytes(vb),
                         tris=[(0, 1, 3), (1, 2, 3)],
                         tex_override={0: diffuse_ref, 1: lightmap_ref, 2: normal_ref}))


def build(base_dat, base_alr, hub_alr):
    hub = open(hub_alr, 'rb').read()
    alr_build.VERTEX_MASK[LBTS_FORMAT] = LBTS_MASK            # this test only: the vertex buffer's attribute mask
    material = lbts_material(hub)
    textures = [dict(name='pd_lmcheck', width=64, height=64, levels=mips(checker, 64)),     # new 0
                hub_light(hub),                                                             # new 1
                dict(name='pd_lmtest', width=64, height=64, levels=mips(test_light, 64)),   # new 2
                dict(name='pd_lmwhite', width=4, height=4, levels=mips(lambda x, y, w: (255, 255, 255, 0), 4)),
                dict(name='pd_lmflat', width=4, height=4, levels=mips(flat, 4))]            # new 4
    diffuse, normal = ('new', 0), ('new', 4)
    n = 4
    x_start = -(n * PAD + (n - 1) * GAP) / 2
    z0 = -PAD / 2
    stage = []
    for i, lm in enumerate((('new', 1), ('new', 2), ('new', 3))):
        stage.append(pad_lbts(x_start + i * (PAD + GAP), z0, material, lm, diffuse, normal))
    x4 = x_start + 3 * (PAD + GAP)
    up, white = (0.0, 1.0, 0.0), (255, 255, 255, 255)
    sd_v = [((x4, 0.0, z0), up, (0, 0), white), ((x4, 0.0, z0 + PAD), up, (0, 8), white),
            ((x4 + PAD, 0.0, z0 + PAD), up, (8, 8), white), ((x4 + PAD, 0.0, z0), up, (8, 0), white)]
    stage.append(dict(verts=sd_v, tris=[(0, 1, 3), (1, 2, 3)],
                      material=dict(diffuse=diffuse, normal=None, reflection=None, specular=(0, 0, 0, 0))))
    b = open(base_alr, 'rb').read()
    new_alr, _ = alr_build.rebuild(b, replace={0: stage}, clear=(1,), shadows_for=(0,), textures=textures)

    # collision: one floor under all pads, invisible edge walls
    half_x, half_z = -x_start + 100.0, PAD / 2 + 300.0
    corners = [(-half_x, -half_z), (-half_x, half_z), (half_x, half_z), (half_x, -half_z)]
    p = [(cx, 0.0, cz) for cx, cz in corners]
    col = [(p[0], p[1], p[3], 0x08), (p[1], p[2], p[3], 0x08)]
    for (ax, az), (bx, bz) in zip(corners, corners[1:] + corners[:1]):
        a0, a1, b0, b1 = (ax, 0.0, az), (ax, stm.WALL_H, az), (bx, 0.0, bz), (bx, stm.WALL_H, bz)
        for t in ((a0, a1, b0), (a1, b1, b0)):
            nrm = stm._normal(*t)
            inward = (-(t[0][0] + t[2][0]) / 2, 0.0, -(t[0][2] + t[2][2]) / 2)
            if sum(nrm[k] * inward[k] for k in range(3)) < 0:
                t = (t[0], t[2], t[1])
            col.append(t + (stm.EDGE,))
    d = bytearray(open(base_dat, 'rb').read())
    block, _stats = collision_build.build_block(col)
    d = bytearray(collision_build.append_collision(bytes(d), block))
    dat.clear_placements(d)
    dat.clear_effects(d)
    for layout in dat.spawn_layouts(bytes(d)):
        k = len(layout)
        for i, s in enumerate(layout):
            x = -half_x + 2 * half_x * (i + 0.5) / k
            z = -half_z + 100.0
            s.pos, s.yaw = (x, 0.0, z), 0.0
            s.orbs = [(x - 40.0, 0.0, z + 60.0), (x, 0.0, z + 80.0), (x + 40.0, 0.0, z + 60.0)]
            dat.write_spawn(d, s)
    return bytes(d), new_alr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('base_dat')
    ap.add_argument('base_alr')
    ap.add_argument('hub_alr')
    ap.add_argument('out_dir')
    ap.add_argument('--map', default='st03')
    a = ap.parse_args()
    d, m = build(a.base_dat, a.base_alr, a.hub_alr)
    os.makedirs(a.out_dir, exist_ok=True)
    open(os.path.join(a.out_dir, a.map + '.dat'), 'wb').write(d)
    open(os.path.join(a.out_dir, a.map + '.alr'), 'wb').write(m)
    print('.alr %.1f MB, .dat %d bytes' % (len(m) / 1e6, len(d)))


if __name__ == '__main__':
    main()
