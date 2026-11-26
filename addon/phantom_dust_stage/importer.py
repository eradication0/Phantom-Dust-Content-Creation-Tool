"""Import a map's stNN.dat (+ .alr) as a starting point (optional; export works on any scene).

  PD_<stage>
    Visuals                  role Visuals: Stage and Background models (the sky becomes the editable PD sky)
    Colliders                role Colliders
      Stone, strong landing (08)   one collection and mesh per surface type, named after it
    Objects, Effects         see objects_import.py
    Spawn_Points             role Spawn Points
      LAYOUT_1 ...           one per layout
        L1_SPAWN_1           empty; location = spawn, +Y axis = facing
          L1_SPAWN_1_ORB_1   3 child empties = orb points

Also sets the scene's game original and scale so exporting goes back to the same stage slot.
"""
import os

import bpy
from mathutils import Matrix, Vector

from ._lib import dat
from . import convert as cv


def _collection(name, parent, role='NONE', surface=''):
    c = bpy.data.collections.new(name)
    parent.children.link(c)
    c.pd_role = role
    c.pd_surface = surface
    return c


def _has_draws(b_alr, root):
    """True when model `root` of the .alr bytes holds at least one draw (chunk 0x02)."""
    from ._lib import alr
    h = alr.header(b_alr)
    if root >= len(h['roots']) or h['roots'][root] <= 0:
        return False
    return any(t == 0x02 for _o, t, _s in alr.chain(b_alr, h['roots'][root]))


def import_stage(context, path, scale=cv.DEFAULT_SCALE, collision=True, spawns=True, visuals=True, alr_path=None,
                 stage=None, objects=True, effects=True, sky=True, variant=0, preserve=False):
    """preserve: also record what the import made, for the optional export fallback "Preserve unedited parts from
    the original file" (roundtrip.py). Off by default: the scene then holds only what it shows."""
    from . import surfaces, roundtrip
    roundtrip.ENABLED = bool(preserve)
    from . import visuals as _vis
    _vis._SHARED.clear()                                 # one Blender image per texture within this import
    # the scale as typed (an operator's float property holds 0.1 as 0.100000001...): the export's round trip
    # works out where the import put each value from it (exporter._import_scale)
    scale = float('%.6g' % scale)
    b = open(path, 'rb').read()
    stage = stage or os.path.splitext(os.path.basename(path))[0]
    root = _collection('PD_' + stage, context.scene.collection)
    report = []
    if dat.layout_kind(b) != 'stage':
        # st00.dat (short header, never loaded by the game) and the town's area files have no collision, spawn,
        # object or effect tables: only the model file is imported
        collision = spawns = objects = effects = False
        report.append('%s has no stage tables (collision, spawns, objects, effects)' % os.path.basename(path))
    if stage in dict(cv.GAME_ORIGINALS):
        context.scene.pd_game_original = stage           # first: the sky and textures below refer to it
    context.scene.pd_scale = scale

    alr_path = alr_path or os.path.splitext(path)[0] + '.alr'
    b_alr = open(alr_path, 'rb').read() if os.path.isfile(alr_path) else None
    # The game's sky dome (root 2 of a battle stage: sbtscloud3 clouds over svc / sc vertex-coloured domes) comes in
    # as real meshes in the Sky collection, exported back as root 2 from them. sky='preset' keeps the old behaviour
    # (the add-on's own sky model, built from settings started from this map's sky).
    game_sky = bool(sky) and sky != 'preset' and b_alr is not None and dat.layout_kind(b) == 'stage' \
        and _has_draws(b_alr, 2)
    if visuals:
        if b_alr is not None:
            from . import visuals as vis
            report.append(vis.import_visuals(context, alr_path, root, scale, roots=(0, 1, 2) if game_sky else (0, 1)))
            if dat.layout_kind(b) in ('stage', 'area'):
                from . import townlights
                msg = townlights.import_town_lights(context, b, alr_path, root, scale, stage)
                if msg:
                    report.append(msg)
        else:
            report.append('no %s: visible model skipped' % os.path.basename(alr_path))

    if collision:
        cols = _collection('Colliders', root, 'COLLIDERS')
        by_type = {}
        for v0, v1, v2, _n, st in dat.triangles(b):
            by_type.setdefault(st, []).append((v0, v1, v2))
        for st in sorted(by_type):
            sub = _collection('%s (%02X)' % (surfaces.name(st), st), cols, surface='%02X' % st)
            verts, index, faces = [], {}, []
            for tri in by_type[st]:
                f = []
                for v in tri:
                    k = tuple(round(x, 4) for x in v)
                    if k not in index:
                        index[k] = len(verts)
                        verts.append(cv.to_blender(v, scale))
                    f.append(index[k])
                faces.append(cv.flip_winding(f))                     # the mirror reverses winding
            me = bpy.data.meshes.new('COL_%s_%02X' % (stage, st))
            me.from_pydata(verts, [], faces)
            me.update()
            ob = bpy.data.objects.new(me.name, me)
            ob.display_type = 'WIRE'
            sub.objects.link(ob)
        report.append('%d collision triangles in %d surface types' % (sum(map(len, by_type.values())), len(by_type)))

    if spawns:
        sp = _collection('Spawn_Points', root, 'SPAWNS')
        layouts = dat.spawn_layouts(b)
        for li, layout in enumerate(layouts, 1):
            lc = _collection('LAYOUT_%d' % li, sp)
            for si, s in enumerate(layout, 1):
                e = bpy.data.objects.new('L%d_SPAWN_%d' % (li, si), None)
                e.empty_display_type = 'ARROWS'
                e.empty_display_size = 20 * scale
                loc = Vector(cv.to_blender(s.pos, scale))
                rz = cv.yaw_to_blender(s.yaw)
                e.location = loc
                e.rotation_euler = (0.0, 0.0, rz)
                lc.objects.link(e)
                inv = Matrix.Rotation(-rz, 4, 'Z') @ Matrix.Translation(-loc)
                for k, ob_pos in enumerate(s.orbs, 1):
                    o = bpy.data.objects.new('%s_ORB_%d' % (e.name, k), None)
                    o.empty_display_type = 'SPHERE'
                    o.empty_display_size = 4 * scale
                    o.parent = e
                    o.location = inv @ Vector(cv.to_blender(ob_pos, scale))
                    lc.objects.link(o)
        report.append('%d layouts, %d spawns' % (len(layouts), sum(map(len, layouts))))

    from . import objects_import
    if objects and b_alr is not None:
        report.append(objects_import.import_objects(context, b, b_alr, root, scale, stage, variant))
    if effects:
        report.append(objects_import.import_effects(context, b, root, scale, stage))
    if visuals and b_alr is not None:
        from . import visuals as vis
        made, skipped = vis.import_texture_table(alr_path)
        report.append('%d textures no material uses as images (effects, sprites)%s' % (
            made, ', %d cube maps left as the game file has them' % len(skipped) if skipped else ''))
    if dat.layout_kind(b) == 'stage':
        from . import maplights
        report.append(maplights.import_lights(context, b, root, scale, stage))
        from . import stage_extras                         # SP00, MD00 + blobs, enter lights as Blender data
        if visuals and b_alr is not None:
            report.append(stage_extras.import_sprites(context, b, b_alr, root, scale))
            report.append(stage_extras.import_md00(context, b, b_alr, root, scale))
        from . import townlights
        if not townlights.town_lights(context.scene):
            # battle maps: the enter stream's light list as Enter Lights. The town's (st09.dat 0xFC) is the
            # Town_Lights collection made with the visuals, whose light linking gives the draws their lists
            report.append(stage_extras.import_enter_lights(context, b, root, scale, stage))

    if game_sky:
        context.scene.pd_sky_custom = False                # the dome is the Sky collection's meshes
        report.append('sky: the game\'s dome as meshes (Visuals > Sky)')
    elif sky == 'preset' and b_alr is not None and stage in dict(cv.GAME_ORIGINALS):
        from . import sky as pd_sky
        try:
            pd_sky.apply_preset(context, stage)            # the map's own sky as editable settings ...
            pd_sky.build_preview(context)                  # ... on the sky sphere
            report.append('sky: editable (Scene > Phantom Dust Sky)')
        except (RuntimeError, OSError, ValueError) as e:
            report.append('sky skipped: %s' % e)
    else:
        # no dome in the map's root 2 (st09, st32): none is added. The Phantom Dust Sky settings (a gradient dome
        # built by the add-on) stay off until the user turns them on
        context.scene.pd_sky_custom = False

    from . import restricted
    restricted.refresh(context.scene)                     # surface 10 walls: see-through red
    context.scene.pd_imported = True
    if preserve:
        _record_roundtrip(context, path, alr_path, stage, scale, report)
    else:
        context.scene.pop(roundtrip.KEY, None)
    return root, '; '.join(report)


def _record_roundtrip(context, dat_path, alr_path, stage, scale, report):
    """Remember what the export would read from the scene just imported, so exporting it back to the same slot
    keeps every part that was not edited byte for byte (roundtrip.py). A failure here only loses that."""
    from . import exporter, roundtrip
    context.view_layer.update()                           # matrix_world of the new objects
    try:
        from . import sky
        game_data = sky._game_data(context)               # the game data folder the export will use
        if not game_data or not os.path.isdir(os.path.join(game_data, 'Map')):
            game_data = os.path.dirname(os.path.dirname(os.path.abspath(dat_path)))
            if os.path.basename(game_data).lower() == 'map':  # imported from the add-on's backup folder
                game_data = os.path.dirname(game_data)
        digests = exporter.scene_digests(context, context.scene.pd_scale, dat_path, alr_path, game_data)
        roundtrip.record(context.scene, stage.lower(), dat_path, alr_path, digests)
    except Exception as e:                                # noqa: BLE001 -- never fail the import for this
        context.scene.pop(roundtrip.KEY, None)
        report.append('untouched parts will be rebuilt on export (%s)' % e)
