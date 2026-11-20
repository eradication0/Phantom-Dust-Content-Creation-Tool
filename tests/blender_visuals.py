"""Visual export checks in Blender (no window).

  blender -b --factory-startup --python tests/blender_visuals.py -- <Assets/Data folder> <out_dir> [--ingame-test]

1. Import st04 with its model, export: the stage's triangles, baked colours and textures match the original.
2. Add a cube with a new texture and painted lighting: it exports as a new mesh with a new texture entry.
3. Re-import the exported model and render the spawn view (out_dir/reimport_spawn.png) to compare by eye.
With --ingame-test, step 2's cube is placed at layout 1's first orb, with a matching collider, and
out_dir/ingame_test.dat + .alr are written for a game test.
"""
import math
import os
import sys
from collections import Counter

import bpy
from mathutils import Vector

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'addon'))
sys.path.insert(0, ROOT)
import phantom_dust_stage as addon          # noqa: E402
from pdstage import alr, dat                # noqa: E402

args = sys.argv[sys.argv.index('--') + 1:]
data, out_dir = args[0], args[1]
os.makedirs(out_dir, exist_ok=True)
addon.register()
fails = []


def check(cond, what):
    print(('PASS ' if cond else 'FAIL ') + what)
    if not cond:
        fails.append(what)


def stage_tris(b, root=0):
    h = alr.header(b)
    texs = alr.textures(b)
    out = Counter()
    for m in alr.meshes(b, h['roots'][root]):
        mat = m['materials'][m['material']]
        if mat['shader'].startswith('sshadow'):
            continue
        vb = m['vbufs'][m['vbuf']]
        pos, uv, _ = alr.read_vertices(b, h['resource_offset'], vb)
        cols = alr.read_colours(b, h['resource_offset'], vb)
        mtx = alr.node_matrix(m['nodes'], m['node'])
        tex = texs[mat['textures'][0]]['name']
        for t in alr.triangles_from_indices(m['indices'], m['primitive']):
            A, B, C = (alr.apply(mtx, pos[i]) for i in t)
            u = [B[k] - A[k] for k in range(3)]
            v = [C[k] - A[k] for k in range(3)]
            if math.sqrt(sum(x * x for x in (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2],
                                              u[0] * v[1] - u[1] * v[0]))) < 2e-3:
                continue                     # zero-area triangles draw nothing; export may drop them
            corners = [(tuple(round(c, 1) for c in alr.apply(mtx, pos[i])),
                        tuple(round(c % 1.0, 2) % 1.0 for c in uv[i]) if uv else None,
                        cols[i] if cols else (255, 255, 255, 255)) for i in t]
            k = corners.index(min(corners))
            out[(tuple(corners[k:] + corners[:k]), tex)] += 1
    return out


src_alr = os.path.join(data, 'Map', 'st04.alr')
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
bpy.ops.import_scene.phantom_dust_stage(filepath=os.path.join(data, 'Map', 'st04.dat'), scale=0.1)

# 1. round trip
out1 = os.path.join(out_dir, 'roundtrip.dat')
r = bpy.ops.export_scene.phantom_dust_stage(filepath=out1, game_original='st04', game_data=data)
check(r == {'FINISHED'} and os.path.isfile(out1[:-4] + '.alr'), 'export writes roundtrip.dat and roundtrip.alr')
a, b = open(src_alr, 'rb').read(), open(out1[:-4] + '.alr', 'rb').read()
ta, tb = stage_tris(a), stage_tris(b)
check(sum(ta.values()) == sum(tb.values()), 'visible stage triangles %d -> %d' % (sum(ta.values()), sum(tb.values())))
same = sum((ta & tb).values())
check(same >= 0.995 * sum(ta.values()), 'stage triangles with same position, UV, colour and texture: %d of %d' % (same, sum(ta.values())))
check(len(alr.textures(b)) == len(alr.textures(a)), 'no textures duplicated (imported images reuse the map\'s)')
check(stage_tris(a, 1) == stage_tris(b, 1) and stage_tris(a, 2) == stage_tris(b, 2), 'background and sky kept from the base')

# 2. a new textured, lit cube
img = bpy.data.images.new('pd_checker', 64, 64)
px = [0.0] * (64 * 64 * 4)
for y in range(64):
    for x in range(64):
        on = ((x // 8) + (y // 8)) % 2
        px[(y * 64 + x) * 4:(y * 64 + x) * 4 + 4] = (1.0, 0.3 + 0.7 * on, 0.1, 1.0)
img.pixels = px
vis = [c for c in bpy.data.collections if c.pd_role == 'VISUALS'][0]
stage = [c for c in vis.children if c.name.startswith('Stage')][0]
bpy.ops.mesh.primitive_cube_add(size=4.0)
cube = bpy.context.active_object
for c in list(cube.users_collection):
    c.objects.unlink(cube)
stage.objects.link(cube)
sp = bpy.data.objects['L1_SPAWN_1_ORB_1']
bpy.context.view_layer.update()
cube.location = sp.matrix_world.translation + Vector((0, 0, 1.5))
mat = addon.visuals._material('pd_checker_mat', img)
cube.data.materials.append(mat)
light = cube.data.color_attributes.new('PD_Light', 'BYTE_COLOR', 'POINT')
for i, v in enumerate(light.data):
    v.color_srgb = (1.0, 1.0, 1.0, 1.0) if i % 2 else (0.35, 0.35, 0.35, 1.0)
cube.data.uv_layers.new(name='UVMap') if not cube.data.uv_layers else None
if '--ingame-test' in args:
    cols = [c for c in bpy.data.collections if c.pd_surface == '08'][0]
    box = bpy.data.objects.new('CubeCollider', cube.data.copy())
    box.location = cube.location
    cols.objects.link(box)
bpy.context.view_layer.update()
out2 = os.path.join(out_dir, 'ingame_test.dat' if '--ingame-test' in args else 'cube.dat')
r = bpy.ops.export_scene.phantom_dust_stage(filepath=out2, game_original='st04', game_data=data)
c = open(out2[:-4] + '.alr', 'rb').read()
tc = alr.textures(c)
check(r == {'FINISHED'} and tc[-1]['name'] == 'pd_checker' and tc[-1]['width'] == 64 and tc[-1]['mips'] == 7,
      'new texture added: %s %dx%d, %d mips' % (tc[-1]['name'], tc[-1]['width'], tc[-1]['height'], tc[-1]['mips']))
added = sum(stage_tris(c).values()) - sum(ta.values())
check(added == 12, 'cube adds 12 triangles to the stage (got %d)' % added)
ccols = Counter(col for (corners, tex), n in stage_tris(c).items() if tex == 'pd_checker' for _, _, col in corners)
check(set(ccols) == {(89, 89, 89, 255), (255, 255, 255, 255)}, 'cube carries its painted lighting %s' % dict(ccols))
hc = alr.header(c)
sh = [m for m in alr.meshes(c, hc['roots'][0]) if m['materials'][m['material']]['shader'] == 'sshadowch']
sh_tris = sum(len(alr.triangles_from_indices(m['indices'], m['primitive'])) for m in sh)
sh_y = [p[1] for m in sh for p in alr.read_vertices(c, hc['resource_offset'], m['vbufs'][m['vbuf']])[0]]
stage_y = [v[1] for (corners, _t) in stage_tris(c) for v, _uv, _col in corners]
check(len(sh) == 1 and sh[0]['vbufs'][sh[0]['vbuf']]['format'] == 0x07 and sh_tris == 12 and max(sh_y) < min(stage_y) - 900,
      'shadow mesh: a 12-triangle box far below the stage (turns character shadows on, confirmed in game)')
if '--ingame-test' in args:
    check(len(dat.triangles(open(out2, 'rb').read())) == len(dat.triangles(open(os.path.join(data, 'Map', 'st04.dat'), 'rb').read())) + 12,
          'cube collider added to the collision')

# 3. re-import the exported model and render the spawn view
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
for coll in list(bpy.data.collections):
    bpy.data.collections.remove(coll)
bpy.ops.import_scene.phantom_dust_stage(filepath=out2, scale=0.1, collision=False)
scene = bpy.context.scene
scene.render.engine = 'BLENDER_WORKBENCH'
scene.display.shading.light = 'FLAT'
scene.display.shading.color_type = 'TEXTURE'
scene.render.resolution_x, scene.render.resolution_y = 960, 540
cam = bpy.data.objects.new('Cam', bpy.data.cameras.new('Cam'))
cam.data.lens = 18
scene.collection.objects.link(cam)
scene.camera = cam
s = bpy.data.objects['L1_SPAWN_1']
bpy.context.view_layer.update()
eye = s.matrix_world.translation + Vector((0, 0, 1.5))
fwd = s.matrix_world.to_3x3() @ Vector((0, 1, 0))
cam.location = eye - fwd * 3.0
cam.rotation_euler = (fwd).to_track_quat('-Z', 'Y').to_euler()
scene.render.filepath = os.path.join(out_dir, 'reimport_spawn.png')
bpy.ops.render.render(write_still=True)
print('RENDER', scene.render.filepath)
print('RESULT: %d failure(s)' % len(fails))
