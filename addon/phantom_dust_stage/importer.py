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


def import_stage(context, path, scale=cv.DEFAULT_SCALE, collision=True, spawns=True, visuals=True, alr_path=None,
                 stage=None, objects=True, effects=True, sky=True, variant=0):
    from . import surfaces
    b = open(path, 'rb').read()
    stage = stage or os.path.splitext(os.path.basename(path))[0]
    root = _collection('PD_' + stage, context.scene.collection)
    report = []
    if stage in dict(cv.GAME_ORIGINALS):
        context.scene.pd_game_original = stage           # first: the sky and textures below refer to it
    context.scene.pd_scale = scale

    alr_path = alr_path or os.path.splitext(path)[0] + '.alr'
    b_alr = open(alr_path, 'rb').read() if os.path.isfile(alr_path) else None
    if visuals:
        if b_alr is not None:
            from . import visuals as vis
            report.append(vis.import_visuals(context, alr_path, root, scale, roots=(0, 1)))
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

    if sky and b_alr is not None and stage in dict(cv.GAME_ORIGINALS):
        from . import sky as pd_sky
        try:
            pd_sky.apply_preset(context, stage)            # the map's own sky as editable settings ...
            pd_sky.build_preview(context)                  # ... on the sky sphere
            report.append('sky: editable (Scene > Phantom Dust Sky)')
        except (RuntimeError, OSError, ValueError) as e:
            report.append('sky skipped: %s' % e)

    from . import restricted
    restricted.refresh(context.scene)                     # surface 10 walls: see-through red
    context.scene.pd_imported = True
    return root, '; '.join(report)
