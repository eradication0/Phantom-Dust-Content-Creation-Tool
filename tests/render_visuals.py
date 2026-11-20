"""Import a map with its visible model and render views to check it (Blender, no window).

  blender -b --factory-startup --python tests/render_visuals.py -- <Map/stNN.dat> <out_dir>

Writes overview.png (from outside) and spawn_<n>.png (eye height at spawns, looking where the player faces),
and prints image/mesh statistics.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'addon'))
sys.path.insert(0, ROOT)
import phantom_dust_stage as addon          # noqa: E402

args = sys.argv[sys.argv.index('--') + 1:]
src, out_dir = args[0], args[1]
os.makedirs(out_dir, exist_ok=True)
addon.register()
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)

res = bpy.ops.import_scene.phantom_dust_stage(filepath=src, scale=0.1, collision=True, spawns=True, visuals=True)
print('import', res)
imgs = [i for i in bpy.data.images if i.packed_file]
print('IMAGES %d packed, sizes ok %d, sample %s' % (len(imgs), sum(1 for i in imgs if i.size[0] > 0),
      [(i.name, tuple(i.size)) for i in imgs[:4]]))
vis = [c for c in bpy.data.collections if c.pd_role == 'VISUALS'][0]
for c in vis.children:
    print('COLLECTION %-10s objects %3d' % (c.name, len(c.objects)))
cols = [c for c in bpy.data.collections if c.pd_role == 'COLLIDERS'][0]
for c in cols.children_recursive:
    for o in c.objects:
        o.hide_render = True

scene = bpy.context.scene
scene.render.engine = 'BLENDER_WORKBENCH'
scene.display.shading.light = 'FLAT'
scene.display.shading.color_type = 'TEXTURE'
scene.render.resolution_x, scene.render.resolution_y = 960, 540
scene.render.image_settings.file_format = 'PNG'
cam_data = bpy.data.cameras.new('Cam')
cam_data.lens = 18
cam_data.clip_end = 2000
cam = bpy.data.objects.new('Cam', cam_data)
scene.collection.objects.link(cam)
scene.camera = cam


def shoot(name, loc, target):
    cam.location = loc
    d = Vector(target) - Vector(loc)
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    scene.render.filepath = os.path.join(out_dir, name)
    bpy.ops.render.render(write_still=True)
    print('RENDER', scene.render.filepath)


stage = [c for c in vis.children if c.name.startswith('Stage')][0]
pts = [o.matrix_world @ Vector(v) for o in stage.objects for v in o.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
mid = (lo + hi) / 2
print('STAGE bounds', tuple(round(x, 1) for x in lo), tuple(round(x, 1) for x in hi))
shoot('overview.png', mid + Vector((hi.x - lo.x, -(hi.y - lo.y), (hi.z - lo.z) * 1.5)), mid)

spawns = sorted((o for o in bpy.data.objects if o.name.startswith('L1_SPAWN_') and '_ORB_' not in o.name),
                key=lambda o: o.name)
for s in spawns[:2]:
    eye = s.matrix_world.translation + Vector((0, 0, 1.5))
    fwd = s.matrix_world.to_3x3() @ Vector((0, 1, 0))
    shoot('spawn_%s.png' % s.name, eye - fwd * 3.0, eye + fwd * 10.0)
