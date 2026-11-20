"""Run the add-on inside Blender without a window.

  blender -b --factory-startup --python tests/blender_roundtrip.py -- <Assets/Data folder> <out_dir> [--ingame-test]

1. Round trip: import Map/st04.dat, export it unchanged onto st04, compare spawns/orbs and collision.
2. From scratch: a new scene with only a floor, a box and one hand-made layout of 4 spawns, exported onto
   st04; checks the collision is exactly that geometry and the layout fills every slot.
3. Mistakes are reported: a spawn with 2 orbs, a layout with 3 spawns.
4. With --ingame-test, also writes <out_dir>/ingame_test.dat from the imported scene: spawns raised 250 game
   units (orbs left in place) and a solid box added at each distinct first orb.
"""
import math
import os
import sys
from collections import Counter

import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'addon'))
sys.path.insert(0, ROOT)
import phantom_dust_stage as addon          # noqa: E402
from pdstage import dat                     # noqa: E402

args = sys.argv[sys.argv.index('--') + 1:]
data, out_dir = args[0], args[1]
src = os.path.join(data, 'Map', 'st04.dat')
os.makedirs(out_dir, exist_ok=True)
addon.register()
failures = []


def check(cond, what):
    print(('PASS ' if cond else 'FAIL ') + what)
    if not cond:
        failures.append(what)


def export(path, **kw):
    return bpy.ops.export_scene.phantom_dust_stage(filepath=path, game_original='st04', game_data=data, **kw)


def tri_key(t):
    vs = [tuple(round(x, 1) for x in v) for v in t[:3]]
    i = vs.index(min(vs))                       # same triangle may start at another corner
    return tuple(vs[i:] + vs[:i]), t[4]


def box_mesh(name, size, height):
    me = bpy.data.meshes.new(name)
    s = size / 2
    v = [(x, y, z) for z in (0, height) for y in (-s, s) for x in (-s, s)]
    f = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    me.from_pydata(v, [], f)
    me.update()
    return me


# ------------------------------------------------------------------ 1. round trip
bpy.ops.import_scene.phantom_dust_stage(filepath=src, scale=0.1)
check(bpy.context.scene.pd_game_original == 'st04', 'import sets the game original to st04')
roles = Counter(c.pd_role for c in bpy.context.scene.collection.children_recursive)
check(roles['COLLIDERS'] == 1 and roles['SPAWNS'] == 1, 'import tags one Colliders and one Spawn Points collection')
out1 = os.path.join(out_dir, 'roundtrip.dat')
check(export(out1) == {'FINISHED'}, 'export of the imported scene')
a, b = open(src, 'rb').read(), open(out1, 'rb').read()
worst = 0.0
for la, lb in zip(dat.spawn_layouts(a), dat.spawn_layouts(b)):
    for s, t in zip(la, lb):
        worst = max([worst, abs(math.atan2(math.sin(s.yaw - t.yaw), math.cos(s.yaw - t.yaw)))]
                    + [abs(x - y) for x, y in zip(s.pos, t.pos)]
                    + [abs(x - y) for o, p in zip(s.orbs, t.orbs) for x, y in zip(o, p)])
        assert s.tail == t.tail and s.flags == t.flags
check(worst < 0.01, 'round trip spawns/orbs/yaw within 0.01 (max %.5f)' % worst)
ta, tb = dat.triangles(a), dat.triangles(b)
check(Counter(map(tri_key, ta)) == Counter(map(tri_key, tb)), 'round trip collision: same %d triangles and surface types' % len(ta))
check(dat.check_collision(b)['flipped'] == 0, 'round trip collision normals match winding')

if '--ingame-test' in args:
    sp = [c for c in bpy.context.scene.collection.children_recursive if c.pd_role == 'SPAWNS'][0]
    for o in sp.all_objects:
        if o.parent is None:
            o.location.z += 25.0
            for ch in o.children:
                ch.location.z -= 25.0
    bpy.context.view_layer.update()
    col = [c for c in bpy.context.scene.collection.children_recursive if c.pd_surface == '08'][0]
    seen = set()
    for o in sp.all_objects:
        if o.name.endswith('_ORB_1'):
            p = o.matrix_world.translation.copy()
            k = tuple(round(x, 1) for x in p)
            if k not in seen:
                seen.add(k)
                ob = bpy.data.objects.new('TestBox', box_mesh('TestBox', 4.0, 2.5))
                ob.location = (p.x, p.y, p.z - 0.5)
                col.objects.link(ob)
    bpy.context.view_layer.update()
    out2 = os.path.join(out_dir, 'ingame_test.dat')
    check(export(out2) == {'FINISHED'}, 'in-game test file written (%d boxes): %s' % (len(seen), out2))

# ------------------------------------------------------------------ 2. from scratch
scene = bpy.data.scenes.new('Scratch')
with bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
    cols = bpy.data.collections.new('MyColliders'); scene.collection.children.link(cols); cols.pd_role = 'COLLIDERS'
    floor = bpy.data.meshes.new('Floor')
    floor.from_pydata([(-20, -20, 6.4), (20, -20, 6.4), (20, 20, 6.4), (-20, 20, 6.4)], [], [(0, 1, 2, 3)])
    floor.update()
    cols.objects.link(bpy.data.objects.new('Floor', floor))
    slope = bpy.data.collections.new('Ramp'); cols.children.link(slope); slope.pd_surface = '07'
    ramp = bpy.data.objects.new('Box', box_mesh('Box', 4.0, 2.0)); ramp.location = (5, 5, 6.4)
    slope.objects.link(ramp)

    sp = bpy.data.collections.new('MySpawns'); scene.collection.children.link(sp); sp.pd_role = 'SPAWNS'
    lay = bpy.data.collections.new('LAYOUT_1'); sp.children.link(lay)
    want = []
    for i, (x, y, rz) in enumerate([(-10, -10, 0.0), (10, -10, 1.5), (10, 10, 3.0), (-10, 10, -1.5)], 1):
        e = bpy.data.objects.new('SPAWN_%d' % i, None); e.location = (x, y, 7.0); e.rotation_euler = (0, 0, rz)
        lay.objects.link(e)
        for k in range(1, 4):
            o = bpy.data.objects.new('SPAWN_%d_ORB_%d' % (i, k), None); o.parent = e; o.location = (0, 5.0 * k, -0.6)
            lay.objects.link(o)
        want.append((x, y, rz))
    scene.view_layers[0].update()
    out3 = os.path.join(out_dir, 'scratch.dat')
    res = bpy.ops.export_scene.phantom_dust_stage(filepath=out3, game_original='st04', game_data=data)
    check(res == {'FINISHED'}, 'export of a scene built from scratch')
    c = open(out3, 'rb').read()
    tris = dat.triangles(c)
    check(len(tris) == 2 + 12, 'scratch collision is exactly floor (2) + box (12) triangles, got %d' % len(tris))
    check(Counter(t[4] for t in tris) == Counter({8: 2, 7: 12}), 'surface types: floor 08 (default), box 07 (from Ramp collection)')
    floor_tris = [t for t in tris if t[4] == 8]
    check(all(abs(t[3][1] - 1) < 1e-4 and abs(t[0][1] - 64) < 1e-3 for t in floor_tris), 'floor faces up (+y) at game height 64')
    lays = dat.spawn_layouts(c)
    first = lays[0]
    check(all([(s.pos, s.yaw, s.orbs) for s in l] == [(s.pos, s.yaw, s.orbs) for s in first] for l in lays),
          'one scene layout filled all %d layout slots' % len(lays))
    ok = all(abs(s.pos[0] - x * 10) < 1e-3 and abs(s.pos[2] + y * 10) < 1e-3 and abs(s.pos[1] - 70) < 1e-3
             for s, (x, y, rz) in zip(first, want))
    check(ok, 'spawn positions converted (Blender x,y,z -> game x, z, -y) x10')
    fwd = [(math.sin(s.yaw), math.cos(s.yaw)) for s in first]
    orb_dir = [((s.orbs[0][0] - s.pos[0]) / 50, (s.orbs[0][2] - s.pos[2]) / 50) for s in first]
    check(all(abs(f[0] - d[0]) < 1e-3 and abs(f[1] - d[1]) < 1e-3 for f, d in zip(fwd, orb_dir)),
          'orbs placed along +Y of the spawn end up in front of its game facing')

    # ------------------------------------------------------------------ 3. mistakes are reported
    bpy.data.objects.remove(bpy.data.objects['SPAWN_1_ORB_3'])
    try:
        r = bpy.ops.export_scene.phantom_dust_stage(filepath=os.path.join(out_dir, 'bad.dat'), game_original='st04', game_data=data)
    except RuntimeError as e:
        r = str(e)
    check('3' in str(r) and 'orb' in str(r), 'spawn with 2 orbs is refused: %s' % str(r).strip().splitlines()[-1])
    o = bpy.data.objects.new('SPAWN_1_ORB_3', None); o.parent = bpy.data.objects['SPAWN_1']; lay.objects.link(o)
    bpy.data.objects.remove(bpy.data.objects['SPAWN_4'])
    for k in range(1, 4):
        bpy.data.objects.remove(bpy.data.objects['SPAWN_4_ORB_%d' % k])
    try:
        r = bpy.ops.export_scene.phantom_dust_stage(filepath=os.path.join(out_dir, 'bad.dat'), game_original='st04', game_data=data)
    except RuntimeError as e:
        r = str(e)
    check('needs 4' in str(r), 'layout with 3 spawns is refused: %s' % str(r).strip().splitlines()[-1])

print('RESULT: %d failure(s)' % len(failures))
