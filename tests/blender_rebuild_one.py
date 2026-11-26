"""Round trips of one map built from the scene (the default export: fallback "Preserve unedited parts" OFF).

blender --background --factory-startup --python tests/blender_rebuild_one.py -- <repository> <Assets/Data> <stage> <out dir> <mode>
mode: 'untouched'  import, export (U1); new scene, import U1, export (U2); import U2, export (U3)
      'edits'      import; per edit kind: edit, export (<edit>), take the edit back in the scene, export (<edit>_undo)
      'p2edits' / 'alledits'  the same with the p2 sections' edits / every edit kind (EDITS + P2 + P3)
Writes <out>/<stage>_<name>.dat/.alr and <out>/<stage>_<mode>.json. Compare with tools/check_stage.py (structure)
and tools/stage_semantics.py (what the game reads from the .dat).
"""
import json
import os
import sys
import time
import traceback

import bpy

args = sys.argv[sys.argv.index('--') + 1:]
repo, data, stage, out_dir, mode = args[:5]
src_dir = args[5] if len(args) > 5 else None          # import from another folder (Xbox data, Ascension)
sys.path.insert(0, os.path.join(repo, 'addon'))
os.makedirs(out_dir, exist_ok=True)
res = dict(stage=stage, mode=mode, runs={})

import phantom_dust_stage as addon                     # noqa: E402
from phantom_dust_stage import exporter, importer, roundtrip, scene_tools  # noqa: E402
from phantom_dust_stage.exporter import collections_with_role as cwr  # noqa: E402
addon.register()
from phantom_dust_stage import sky as _sky             # noqa: E402
_sky._game_data = lambda _ctx: data
ctx = bpy.context


def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon.register() if not hasattr(bpy.types.Scene, 'pd_scale') else None


def do_import(dat_path, alr_path):
    t = time.time()
    _root, msg = importer.import_stage(ctx, dat_path, alr_path=alr_path, stage=stage, preserve=False)
    return msg, time.time() - t


def do_export(name):
    roundtrip.ENABLED = False                           # the harness runs with the fallback off
    out_dat = os.path.join(out_dir, '%s_%s.dat' % (stage, name))
    out_alr = os.path.join(out_dir, '%s_%s.alr' % (stage, name))
    for p in (out_dat, out_alr):
        if os.path.exists(p):
            os.remove(p)
    t = time.time()
    r = dict()
    try:
        scene_tools.set_broken_parts_hidden(ctx, True)
        base_dat = exporter.game_original_dat(data, stage)
        base_alr = exporter.game_original_alr(data, stage)
        vmsg, objects, placements = exporter.export_models(ctx, base_alr, out_alr, ctx.scene.pd_scale, True, True,
                                                           compress_textures='ALL', texture_budget_mb=24,
                                                           lightmap_budget_mb=16)
        msg = exporter.export_scene(ctx, base_dat, out_dat, ctx.scene.pd_scale, True, objects, placements, data)
        r['report'] = msg + ('; ' + vmsg if vmsg else '')
        if not vmsg and os.path.exists(base_alr) and not os.path.exists(out_alr):
            import shutil
            shutil.copyfile(base_alr, out_alr)
            r['alr'] = 'no model collections: the game file'
    except Exception:
        r['error'] = traceback.format_exc()
    r['t'] = time.time() - t
    res['runs'][name] = r
    return out_dat, out_alr


EDITS = ['spawn', 'collision', 'visual', 'object', 'effect', 'lighting', 'fog', 'pointlight', 'showcase']
P2_EDITS = ['sprite', 'md00anim', 'objanim', 'cube', 'enterlight']     # mode 'p2edits': the p2 sections
P3_EDITS = ['skymesh', 'joint', 'townlight', 'lightlink']               # sky dome, stage joints, town light lists
ALL_EDITS = EDITS + P2_EDITS + P3_EDITS                                 # mode 'alledits'
_saved = {}


def edit(kind, sign):
    sc = ctx.scene
    if kind == 'spawn':
        o = next(o for o in cwr(sc, 'SPAWNS')[0].all_objects if o.name == 'L1_SPAWN_1')
        o.location.x += 1.0 * sign
    elif kind == 'collision':
        o = next(o for c in cwr(sc, 'COLLIDERS') for o in c.all_objects if o.type == 'MESH')
        o.location.z += 0.5 * sign
    elif kind == 'visual':
        vis = cwr(sc, 'VISUALS')[0]
        stage_c = next(c for c in vis.children_recursive if c.name.startswith('Stage'))
        o = next(o for o in stage_c.objects if o.type == 'MESH')
        o.location.y += 0.2 * sign
    elif kind == 'object':
        o = next(o for oc in cwr(sc, 'OBJECTS') for tc in oc.children for o in tc.objects if o.type == 'MESH')
        o.location.x += 1.0 * sign
    elif kind == 'effect':
        o = next(o for ec in cwr(sc, 'EFFECTS') for tc in ec.children for o in tc.objects)
        o.location.x += 1.0 * sign
    elif kind == 'lighting':
        o = next(o for o in sc.objects if o.type == 'LIGHT' and o.get('pd_light_set') == 0 and o.data.type == 'SUN')
        c = o.data.color
        o.data.color = (c[0], c[1] + (0.2 if sign > 0 else -0.2), c[2])
    elif kind == 'fog':
        w = next(w for w in bpy.data.worlds if w.get('pd_light_set') == 0)
        w.mist_settings.start += 10.0 * sign
        o = w
    elif kind == 'showcase':               # for the pictures: the biggest stage mesh raised 2 m
        vis = cwr(sc, 'VISUALS')[0]
        stage_c = next(c for c in vis.children_recursive if c.name.startswith('Stage'))
        o = max((o for o in stage_c.objects if o.type == 'MESH'), key=lambda o: len(o.data.polygons))
        o.location.z += 2.0 * sign
    elif kind == 'pointlight':
        o = next(o for o in sc.objects if o.type == 'LIGHT' and o.get('pd_light_set') == 0 and o.data.type == 'POINT')
        o.location.z += 1.0 * sign
    elif kind == 'sprite':                 # a sprite type's quads 20 % wider (its frames' extent)
        o = next(o for o in sc.objects if 'pd_sprite_number' in o)
        for v in o.data.vertices:
            v.co.x *= 1.2 if sign > 0 else 1 / 1.2
    elif kind in ('md00anim', 'objanim'):  # an animation's translation keys raised by 1 m (0.5 m)
        from phantom_dust_stage import stage_extras
        key = 'pd_joint' if kind == 'md00anim' else 'pd_piece_value'
        path = 'location' if kind == 'md00anim' else 'delta_location'
        o = next(o for o in sc.objects if key in o and o.animation_data and o.animation_data.action)
        fc = stage_extras.curves_of(o)[path][2]
        for k in fc.keyframe_points:
            k.co[1] += (1.0 if kind == 'md00anim' else 0.5) * sign
        fc.update()
    elif kind == 'cube':                   # the cube map half as bright (undo: the pixels saved before)
        import numpy as np
        img = next(i for i in bpy.data.images if i.get('pd_cube_map'))
        if sign > 0:
            px = np.empty(img.size[0] * img.size[1] * 4, dtype=np.float32)
            img.pixels.foreach_get(px)
            _saved['cube'] = px.copy()
            px[0::4] *= 0.5
            px[1::4] *= 0.5
            px[2::4] *= 0.5
            img.pixels.foreach_set(px)
        else:
            img.pixels.foreach_set(_saved.pop('cube'))
        img.update()
        o = img
    elif kind == 'enterlight':
        o = next(o for o in sc.objects if 'pd_light_index' in o)
        o.location.z += 1.0 * sign
    elif kind == 'skymesh':                # a mesh of the game's sky dome (Visuals > Sky) raised 1 m
        vis = cwr(sc, 'VISUALS')[0]
        sky_c = next(c for c in vis.children_recursive if c.name.startswith('Sky'))
        o = next(o for o in sky_c.all_objects if o.type == 'MESH')
        o.location.z += 1.0 * sign
    elif kind == 'joint':                  # a joint empty of the background model moved 0.5 m (its draws with it)
        vis = cwr(sc, 'VISUALS')[0]
        bg = next(c for c in vis.children_recursive if c.name.startswith('Background'))
        o = next(o for o in bg.all_objects if o.type == 'EMPTY' and o.get('pd_joint') and
                 any(ch.type == 'MESH' for ch in o.children))
        o.location.x += 0.5 * sign
    elif kind == 'townlight':              # a town light (light list of the .dat) raised 1 m
        o = next(o for o in sc.objects if o.type == 'LIGHT' and o.get('pd_town_light') == 'point')
        o.location.z += 1.0 * sign
    elif kind == 'lightlink':              # one draw taken out of a town light's light linking (undo: put back)
        o = next(o for o in sc.objects if o.type == 'LIGHT' and o.get('pd_town_light') == 'point' and
                 o.light_linking.receiver_collection is not None and o.light_linking.receiver_collection.objects)
        rc = o.light_linking.receiver_collection
        if sign > 0:
            m = sorted(rc.objects, key=lambda x: x.name)[0]
            _saved['lightlink'] = m.name
            rc.objects.unlink(m)
        else:
            rc.objects.link(bpy.data.objects[_saved.pop('lightlink')])
    ctx.view_layer.update()
    return o.name


try:
    sdir = src_dir or os.path.join(data, 'Map')
    d0, a0 = os.path.join(sdir, stage + '.dat'), os.path.join(sdir, stage + '.alr')
    if mode == 'untouched':
        msg, t = do_import(d0, a0)
        res['import'] = msg
        res['t_import'] = t
        cur = do_export('u1')
        for k in (2, 3):
            fresh()
            do_import(*cur)
            cur = do_export('u%d' % k)
    else:
        msg, t = do_import(d0, a0)
        res['import'] = msg
        for kind in {'p2edits': P2_EDITS, 'alledits': ALL_EDITS}.get(mode, EDITS):
            try:
                name = edit(kind, +1)
            except (StopIteration, IndexError, KeyError):
                res['runs'][kind] = dict(skipped='nothing to edit')
                continue
            do_export(kind)
            res['runs'][kind]['edited'] = name
            edit(kind, -1)
            do_export(kind + '_undo')
except Exception:
    res['error'] = traceback.format_exc()
with open(os.path.join(out_dir, '%s_%s.json' % (stage, mode)), 'w') as f:
    json.dump(res, f, indent=1)
print('RB_DONE', stage, mode, 'error' in res or any('error' in r for r in res['runs'].values()))
