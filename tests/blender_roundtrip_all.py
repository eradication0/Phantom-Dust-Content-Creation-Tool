"""Round trip of every game map through the add-on (Blender without a window). Uses your own game files only.

  blender -b --factory-startup --python tests/blender_roundtrip_all.py -- <Assets/Data folder> <out_dir> [stNN ...]

For each map (default: every Map/stNN.dat): import it as Import Game Original does, export it back to its own
slot with no edits (as the Export operator does) and compare the bytes with the game's files: they must be
identical with the optional fallback "Preserve unedited parts from the original file" ON (roundtrip.py:
untouched parts are written as the game has them; the default export builds from the scene and is measured
elsewhere). Then two edits on a fresh import:
- one spawn moved 1 m: only that spawn's bytes in the .dat change, the .alr stays identical;
- one placed object moved 1 m: only its 0x24-byte placement entry changes, the .alr stays identical;
- one effect moved 1 m: only its 0x5C-byte entry changes, the .alr stays identical;
- one stage mesh moved 0.2 m: the .alr is rebuilt (every other game mesh, the object models and the .dat's
  object tables stay as the game has them), the .dat is identical;
- one object type's model reshaped: it is added as one new object type, every placement list keeps its size.
Writes into <out_dir> only; prints PASS/FAIL lines and RESULT.
"""
import os
import sys

import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'addon'))
sys.path.insert(0, ROOT)
import phantom_dust_stage as addon                  # noqa: E402
from phantom_dust_stage import exporter, importer   # noqa: E402
from phantom_dust_stage import sky as pd_sky        # noqa: E402
from phantom_dust_stage._lib import dat             # noqa: E402

args = sys.argv[sys.argv.index('--') + 1:]
data, out_dir = args[0], args[1]
mdir = exporter.map_dir(data)
stages = args[2:] or sorted(n[:-4].lower() for n in os.listdir(mdir)
                            if n.lower().startswith('st') and n.lower().endswith('.dat') and '_' not in n)
os.makedirs(out_dir, exist_ok=True)
addon.register()
pd_sky._game_data = lambda _ctx: data          # loaded from sys.path: no add-on preferences to hold the folder
failures = []


def check(cond, what):
    print(('PASS ' if cond else 'FAIL ') + what, flush=True)
    if not cond:
        failures.append(what)


def round_trip(stage, edit=None):
    """Import `stage` into a new scene, apply `edit`, export; returns (dat, alr) bytes written."""
    scene = bpy.data.scenes.new('RT_' + stage)
    with bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
        ctx = bpy.context
        dat_path, alr_path = exporter.game_original_dat(data, stage), exporter.game_original_alr(data, stage)
        importer.import_stage(ctx, dat_path, alr_path=alr_path, stage=stage, preserve=True)   # the fallback
        if edit:
            edit(scene)
            scene.view_layers[0].update()
        name = stage + ('_' + edit.__name__ if edit else '')
        out_dat, out_alr = os.path.join(out_dir, name + '.dat'), os.path.join(out_dir, name + '.alr')
        vmsg, objects, placements = exporter.export_models(ctx, alr_path, out_alr, scene.pd_scale, True, True,
                                                           compress_textures='ALL', texture_budget_mb=24,
                                                           lightmap_budget_mb=16)
        exporter.export_scene(ctx, dat_path, out_dat, scene.pd_scale, True, objects, placements, data)
    bpy.data.scenes.remove(scene)
    bpy.data.orphans_purge(do_recursive=True)
    read = lambda p: open(p, 'rb').read() if os.path.isfile(p) else None
    return read(out_dat), read(out_alr), read(dat_path), read(alr_path)


def spawn(scene):
    sp = exporter.collections_with_role(scene, 'SPAWNS')[0]
    next(o for o in sp.all_objects if o.name.endswith('L1_SPAWN_1') or o.name == 'L1_SPAWN_1').location.x += 1.0


def placement(scene):
    oc = exporter.collections_with_role(scene, 'OBJECTS')[0]
    next(o for tc in oc.children for o in tc.objects if o.type == 'MESH' and 'pd_placement' in o).location.x += 1.0


def effect(scene):
    ec = exporter.collections_with_role(scene, 'EFFECTS')[0]
    next(o for tc in ec.children for o in tc.objects).location.x += 1.0


def only_within(new, old, size):
    """The files differ in one span of at most `size` bytes (and have the same length)."""
    changed = [i for i in range(min(len(new), len(old))) if new[i] != old[i]]
    return len(new) == len(old) and bool(changed) and changed[-1] - changed[0] < size, len(changed)


def object_model(scene):
    """Move one vertex of the first object type's model (every placement of the type shares the mesh)."""
    oc = exporter.collections_with_role(scene, 'OBJECTS')[0]
    o = next(o for tc in oc.children for o in tc.objects if o.type == 'MESH' and 'pd_placement' in o)
    o.data.vertices[0].co.z += 0.3
    o.data.update()


def collision(scene):
    """Raise one collision mesh (one surface type) by 0.5."""
    o = sorted((o for c in exporter.collections_with_role(scene, 'COLLIDERS') for o in c.all_objects
                if o.type == 'MESH'), key=lambda o: o.name)[0]
    o.location.z += 0.5


def copy_object(scene):
    """Add a copy of a placed object (Shift+D), 3 m away."""
    oc = exporter.collections_with_role(scene, 'OBJECTS')[0]
    src = next(o for tc in oc.children for o in tc.objects if o.type == 'MESH' and 'pd_placement' in o)
    o = src.copy()
    for c in src.users_collection:
        c.objects.link(o)
    o.location.x += 3.0


def visual(scene):
    vis = exporter.collections_with_role(scene, 'VISUALS')[0]
    stage_c = next(c for c in vis.children_recursive if c.name.startswith('Stage'))
    next(o for o in stage_c.objects if o.type == 'MESH').location.y += 0.2


for st in stages:
    try:
        d, a, od, oa = round_trip(st)
        check(d == od, '%s: untouched .dat identical (%d bytes)' % (st, len(od)))
        check(a == oa, '%s: untouched .alr identical (%d bytes)' % (st, len(oa or b'')))
    except Exception as e:                     # noqa: BLE001
        check(False, '%s: round trip raised %r' % (st, e))

edit_stages = [s for s in ('st04', 'st07') if s in stages] or stages[:1]
for st in edit_stages:
    try:
        d, a, od, oa = round_trip(st, spawn)
        ok, n = only_within(d, od, 0x50)
        check(ok, '%s: a moved spawn changes only its own 0x50-byte entry (%d bytes changed)' % (st, n))
        check(a == oa, '%s: a moved spawn leaves the .alr identical' % st)
        d, a, od, oa = round_trip(st, placement)
        ok, n = only_within(d, od, 0x24)
        check(ok, '%s: a moved object changes only its own 0x24-byte placement (%d bytes changed)' % (st, n))
        check(a == oa, '%s: a moved object leaves the .alr identical' % st)
        d, a, od, oa = round_trip(st, effect)
        ok, n = only_within(d, od, 0x5C)
        check(ok, '%s: a moved effect changes only its own 0x5C-byte entry (%d bytes changed)' % (st, n))
        check(a == oa, '%s: a moved effect leaves the .alr identical' % st)
        d, a, od, oa = round_trip(st, visual)
        check(d == od, '%s: a moved stage mesh leaves the .dat identical (objects kept)' % st)
        check(a is not None and a != oa and len(a) == len(oa),
              '%s: a moved stage mesh is written into its own vertices (same .alr size)' % st)
        d, a, od, oa = round_trip(st, collision)
        cc = dat.check_collision(d)
        check(a == oa and len(dat.triangles(d)) == len(dat.triangles(od)) and dat.collision(d)[0][0].offset >= 0
              and not (cc['bad_index'] or cc['bad_normal'] or cc['flipped']),
              '%s: a raised collision mesh keeps every triangle, valid (.dat %+d bytes), .alr identical'
              % (st, len(d) - len(od)))
        d, a, od, oa = round_trip(st, copy_object)
        n_old = sum(c for _s, _o, c in dat.placement_tables(od))
        n_new = sum(c for _s, _o, c in dat.placement_tables(d))
        check(a == oa and n_new == n_old + 1 and dat.header(d)['object_count'] == dat.header(od)['object_count'],
              '%s: a copied object adds one placement (%d -> %d), no new type, .alr identical' % (st, n_old, n_new))
        d, a, od, oa = round_trip(st, object_model)
        in_place = d == od and a is not None and a != oa and len(a) == len(oa)
        n_old, n_new = (dat.header(x)['object_count'] for x in (od, d))
        same_lists = [dat.placement_tables(od)[k][2] == dat.placement_tables(d)[k][2]
                      for k in range(len(dat.placement_tables(od)))]
        # written into its own meshes when only vertices moved and none is shared with another mesh, else added
        # as one new type (every placement list kept)
        check(in_place or (n_new == n_old + 1 and all(same_lists)),
              '%s: a reshaped object model is %s' % (st, 'written into its own meshes (.dat identical, same .alr '
                                                     'size)' if in_place else 'added as one new type (%d -> %d)'
                                                     % (n_old, n_new)))
    except Exception as e:                     # noqa: BLE001
        check(False, '%s: edited round trip raised %r' % (st, e))

print('RESULT: %d failure(s)' % len(failures))
