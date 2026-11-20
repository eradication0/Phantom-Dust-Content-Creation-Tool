"""The add-on's whole workflow in Blender without a window, against a COPY of the game's data folder:
New Map Setup -> add a block -> Bake Lighting -> Export with "Install into the game" -> export again
(the base must still be the game's own file) -> restore.

  blender -b --factory-startup --python tests/blender_workflow.py -- <Assets/Data folder> <work_dir>

The real game folder is only read (st04 and the effect source maps are copied into work_dir/Data/Map).
"""
import hashlib
import os
import shutil
import sys

import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'addon'))
sys.path.insert(0, ROOT)
import phantom_dust_stage as addon                     # noqa: E402
from phantom_dust_stage import exporter, scene_tools   # noqa: E402
from pdstage import dat, maplight, objects_build       # noqa: E402

src_data, work = sys.argv[sys.argv.index('--') + 1:][:2]
data = os.path.join(work, 'Data')
shutil.rmtree(data, ignore_errors=True)
os.makedirs(os.path.join(data, 'Map'))
for f in ('st04.dat', 'st04.alr', 'st09.dat'):
    shutil.copyfile(os.path.join(src_data, 'Map', f), os.path.join(data, 'Map', f))
digest = lambda p: hashlib.sha1(open(p, 'rb').read()).hexdigest()
orig = {f: digest(os.path.join(data, 'Map', f)) for f in ('st04.dat', 'st04.alr')}

addon.register()
fails = []


def check(ok, what):
    print(('PASS ' if ok else 'FAIL ') + what)
    if not ok:
        fails.append(what)


for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
scene = bpy.context.scene
check(bpy.ops.pdstage.new_map() == {'FINISHED'}, 'New Map Setup runs')
try:
    again = bpy.ops.pdstage.new_map()
except RuntimeError:                                   # an operator's error report raises in scripts
    again = {'CANCELLED'}
check(again == {'CANCELLED'}, 'a second setup in the same scene is refused')
names = {c.name: c.pd_role for c in bpy.data.collections}
check(names.get('Visuals') == 'VISUALS' and names.get('Colliders') == 'COLLIDERS' and names.get('Spawn_Points') == 'SPAWNS'
      and names.get('Objects') == 'OBJECTS' and names.get('Effects') == 'EFFECTS', 'collections made with their roles')

# a block on the floor, so the bake has a shadow to cast
bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, scene_tools.FLOOR_Z + 1.0))
block = bpy.context.object
for c in block.users_collection:
    c.objects.unlink(block)
bpy.data.collections['Visuals'].objects.link(block)
col = block.copy()
col.data = block.data.copy()
col.hide_render = True
bpy.data.collections['Colliders'].objects.link(col)

check(bpy.ops.pdstage.bake_light(samples=8) == {'FINISHED'}, 'Bake Lighting runs')
floor = bpy.data.objects['Floor']
lum = [sum(c.color_srgb[:3]) / 3 for c in floor.data.color_attributes['PD_Light'].data]
check(max(lum) > 0.99 and min(lum) < max(lum) * 0.8, 'floor got baked light and shade (%.2f..%.2f)' % (min(lum), max(lum)))
check(all(not o.hide_render for o in (floor, block)) and col.hide_render, 'render visibility restored after the bake')

out = os.path.join(work, 'out')
os.makedirs(out, exist_ok=True)
for run in (1, 2):
    res = bpy.ops.export_scene.phantom_dust_stage(filepath=os.path.join(out, 'st04.dat'), game_original='st04',
                                                  game_data=data, install_to_game=True)
    check(res == {'FINISHED'}, 'export + install, run %d' % run)
    game_dat = open(os.path.join(data, 'Map', 'st04.dat'), 'rb').read()
    check(digest(os.path.join(data, 'Map', 'st04.dat')) == digest(os.path.join(out, 'st04.dat')), 'installed .dat is the export (run %d)' % run)
    check(digest(os.path.join(data, 'Map', exporter.BACKUP_DIR, 'st04.dat')) == orig['st04.dat'], 'backup holds the game\'s own .dat (run %d)' % run)
    sizes = len(game_dat)
    if run == 1:
        first = sizes
check(sizes == first, 'second export starts from the backup, not the installed map (same size %d)' % sizes)
_names, _table, places = objects_build.read_objects(game_dat)
pad = [p for p in places if (p['category'], p['type']) == objects_build.PRESETS['JUMP_PAD'][:2]]
check(len(pad) == 1 and abs(pad[0]['pos'][1] - scene_tools.FLOOR_Z * 10) < 0.5,
      'the setup\'s jump pad is placed on the floor (%s)' % [p['pos'] for p in pad])
d = maplight.describe(maplight.script_of(game_dat))
check(d['sets'][0]['direction'][1] < 0, 'game light points down, following the sun')
check(dat.check_collision(game_dat)['bad_index'] == 0, 'collision readable')
try:
    res = bpy.ops.export_scene.phantom_dust_stage(filepath=os.path.join(data, 'Map', 'st04.dat'), game_original='st04',
                                                  game_data=data)
except RuntimeError:
    res = {'CANCELLED'}
check(res == {'CANCELLED'}, 'exporting straight into the game folder is refused')

done = exporter.restore(data, 'st04')
check(sorted(done) == ['st04.alr', 'st04.dat'] and all(digest(os.path.join(data, 'Map', f)) == h for f, h in orig.items()),
      'restore puts the game\'s own files back')
print('RESULT: %d failure(s)' % len(fails))
sys.exit(1 if fails else 0)
