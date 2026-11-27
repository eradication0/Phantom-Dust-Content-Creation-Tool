"""AI navigation mesh (com/stNN/comdataV.cad) in Blender: import, export, Generate Nav Mesh, pink display.

  Nav_Mesh                 collection, role Nav Mesh
    NavMesh                quads the computer players walk on (one face = one nav polygon, the game holds 128).
                           Face attributes: pd_nav_flags (1 = depends on stage objects, 2 = jump pad),
                           pd_nav_substitute (the polygon to head for when the target is off the mesh; -1 = work
                           it out)
    NavLinks               edges: the portals between two polygons. Edge attributes pd_poly_a / pd_poly_b (face
                           indices), pd_link_flags (1 = one way, a -> b: drops), pd_link_blocker. Made again from the
                           faces on export when the faces were changed after it was made
    NavPoint.000 ...       empties: nav points (pd_nav_id, pd_nav_radius)
    JumpPoint.000 ...      empties: where a jump pad lands the AI (pd_jump_pads: the pad faces, "3,7")

Everything is in game units times the scene scale, mirrored to Blender like the rest of the map (convert.py). The
routes the AI follows are worked out on export (pdstage/cad.py); so are link costs and the ids on each polygon.
The game reads com\\st(N % 10)\\comdataV.cad: st02, st12 and st22 share one file, and st01 has none.
"""
import math
import os

import bpy
from bpy.props import BoolProperty

from ._lib import cad, navgen
from . import convert as cv

ROLE = 'NAVMESH'
COLL_NAME = 'Nav_Mesh'
PINK = (1.0, 0.25, 0.75, 1.0)
LINK_PINK = (1.0, 0.6, 0.9, 1.0)
JUMP_COLOUR = (1.0, 0.6, 0.1, 1.0)
FLAGS = 'pd_nav_flags'
SUBST = 'pd_nav_substitute'
BACKUP_DIR = 'pd_addon_backup'


# ---------------------------------------------------------------- game files

def com_dir(game_data):
    from . import exporter
    data = os.path.dirname(exporter.map_dir(game_data))
    return exporter._child(data, 'com') or os.path.join(data, 'com')


def stage_number(stage):
    try:
        return int(str(stage).lower().lstrip('st').split('_')[0])
    except ValueError:
        return None


def nav_folder(game_data, stage):
    """com\\stXX of a stage (XX = stage % 10), or None when the game reads no nav mesh there (st01...)."""
    from . import exporter
    n = stage_number(stage)
    if n is None or n % 10 == 1:
        return None
    d = com_dir(game_data)
    name = 'st%02d' % (n % 10)
    return exporter._child(d, name) or os.path.join(d, name)


def target_files(game_data, stage):
    """The comdataV.cad names an export to `stage` replaces: every variant of the folder, except st04's boss room
    (comdata2, used by Panorama Boss st24 only), which is all st24 replaces."""
    folder = nav_folder(game_data, stage)
    if folder is None:
        return None, []
    n = stage_number(stage)
    have = sorted(f for f in os.listdir(folder) if f.lower().startswith('comdata') and f.lower().endswith('.cad')) \
        if os.path.isdir(folder) else []
    if n == 24:
        names = ['comdata2.cad']
    else:
        names = [f for f in have if not (n % 10 == 4 and f.lower() == 'comdata2.cad')] or ['comdata0.cad']
    return folder, names


def original_file(game_data, stage, variant=0):
    """The game's own nav mesh for a stage (from the add-on's backup if one was installed over it), or None."""
    from . import exporter
    folder = nav_folder(game_data, stage)
    if folder is None:
        return None
    for v in (variant, 0):
        name = 'comdata%d.cad' % v
        bdir = exporter._child(folder, BACKUP_DIR)
        for d in (bdir, folder):
            p = exporter._child(d, name) if d else None
            if p and os.path.isfile(p):
                return p
    return None


def install(game_data, stage, cad_path):
    """Copy an exported nav mesh over the stage's nav files (the game's own backed up once). Returns paths."""
    import shutil
    folder, names = target_files(game_data, stage)
    if folder is None or not os.path.isfile(cad_path):
        return []
    os.makedirs(folder, exist_ok=True)
    bdir = os.path.join(folder, BACKUP_DIR)
    os.makedirs(bdir, exist_ok=True)
    done = []
    for name in names:
        dst = os.path.join(folder, name)
        from . import exporter
        dst = exporter._child(folder, name) or dst
        if os.path.isfile(dst) and not os.path.isfile(os.path.join(bdir, name)):
            shutil.copy2(dst, os.path.join(bdir, name))
        shutil.copyfile(cad_path, dst)
        done.append(dst)
    return done


def restore(game_data, stage):
    import shutil
    folder, names = target_files(game_data, stage)
    done = []
    if folder is None:
        return done
    for name in names:
        b = os.path.join(folder, BACKUP_DIR, name)
        if os.path.isfile(b):
            shutil.copyfile(b, os.path.join(folder, name))
            done.append('com/%s/%s' % (os.path.basename(folder), name))
    return done


# ---------------------------------------------------------------- scene <-> model

def collections(scene):
    return [c for c in scene.collection.children_recursive if getattr(c, 'pd_role', 'NONE') == ROLE]


def _style(ob):
    ob.display_type = 'WIRE'
    ob.color = PINK
    ob.hide_render = True
    ob.show_in_front = True
    ob['pd_no_bake'] = True


def _int_attr(me, name, domain, values):
    a = me.attributes.get(name) or me.attributes.new(name, 'INT', domain)
    a.data.foreach_set('value', [int(v) for v in values])


def build(context, model, scale, parent=None, coll=None):
    """Put a nav mesh model (game units) into the scene: the Nav Mesh collection (made, or emptied and reused)."""
    if coll is None:
        coll = bpy.data.collections.new(COLL_NAME)
        (parent or context.scene.collection).children.link(coll)
        coll.pd_role = ROLE
    for o in list(coll.objects):
        data = o.data
        bpy.data.objects.remove(o)
        if data is not None and data.users == 0:
            bpy.data.meshes.remove(data)
    polys = model['polys']
    verts, faces = [], []
    for p in polys:
        f = []
        for v in p['quad']:
            f.append(len(verts))
            verts.append(cv.to_blender(v, scale))
        faces.append(f[::-1])                      # the mirror reverses winding: faces keep pointing up
    me = bpy.data.meshes.new('NavMesh')
    me.from_pydata(verts, [], faces)
    me.update()
    _int_attr(me, FLAGS, 'FACE', [p['flags'] & 0x3 for p in polys])
    _int_attr(me, SUBST, 'FACE', [-1 if p.get('substitute', 255) == 255 else p['substitute'] for p in polys])
    ob = bpy.data.objects.new('NavMesh', me)
    ob['pd_nav'] = 'MESH'
    _style(ob)
    coll.objects.link(ob)
    # links
    lv, le = [], []
    for l in model['links']:
        le.append((len(lv), len(lv) + 1))
        lv.append(cv.to_blender(l['a'], scale))
        lv.append(cv.to_blender(l['b'], scale))
    lme = bpy.data.meshes.new('NavLinks')
    lme.from_pydata(lv, le, [])
    lme.update()
    links = model['links']
    for name, key in (('pd_poly_a', 'pa'), ('pd_poly_b', 'pb'), ('pd_link_flags', 'flags'),
                      ('pd_link_blocker', 'blocker')):
        _int_attr(lme, name, 'EDGE', [l.get(key, 0) for l in links])
    lob = bpy.data.objects.new('NavLinks', lme)
    lob['pd_nav'] = 'LINKS'
    lob['pd_face_count'] = len(polys)
    lob['pd_faces_hash'] = _faces_hash(me)
    _style(lob)
    coll.objects.link(lob)
    for k, nv in enumerate(model['navs']):
        e = bpy.data.objects.new('NavPoint.%03d' % k, None)
        e.empty_display_type = 'PLAIN_AXES'
        e.empty_display_size = 6 * scale
        e.location = cv.to_blender(nv['pos'], scale)
        e['pd_nav'] = 'POINT'
        e['pd_nav_id'] = int(nv.get('id', k))
        e['pd_nav_radius'] = float(nv.get('radius', 100.0))
        e['pd_nav_poly'] = int(nv.get('poly', -1))
        e.color = PINK
        coll.objects.link(e)
    for k, jp in enumerate(model['jumps']):
        e = bpy.data.objects.new('JumpPoint.%03d' % k, None)
        e.empty_display_type = 'CONE'
        e.empty_display_size = 6 * scale
        e.rotation_euler = (math.pi, 0.0, 0.0)              # pointing down: where the AI lands
        e.location = cv.to_blender(jp['pos'], scale)
        e['pd_nav'] = 'JUMP'
        e['pd_jump_pads'] = ','.join(str(p) for p in jp['pads'])
        e['pd_nav_poly'] = int(jp.get('poly', -1))
        e.color = JUMP_COLOUR
        coll.objects.link(e)
    return coll


def _faces_hash(me):
    import hashlib
    h = hashlib.blake2b(digest_size=10)
    h.update(str(len(me.polygons)).encode())
    for p in me.polygons:
        h.update(('%d;' % p.loop_total).encode())
        for vi in p.vertices:
            h.update(('%.2f %.2f %.2f;' % tuple(me.vertices[vi].co)).encode())
    return h.hexdigest()


def _attr(me, name, n, default):
    a = me.attributes.get(name)
    if a is None or len(a.data) != n:
        return [default] * n
    return [x.value for x in a.data]


def read_scene(scene, scale):
    """The model (cad.py) from the scene's Nav Mesh collections, or None when there is none. Raises ValueError for
    a mesh the game cannot take (faces with more than four corners)."""
    colls = collections(scene)
    if not colls:
        return None, ''
    polys, link_obs, navs, jumps, notes = [], [], [], [], []
    face_base = {}
    for c in colls:
        for o in sorted(c.all_objects, key=lambda o: cv.natural_key(o.name)):
            kind = o.get('pd_nav')
            if o.type == 'MESH' and kind != 'LINKS':
                me = o.data
                mw = o.matrix_world
                flags = _attr(me, FLAGS, len(me.polygons), 0)
                subs = _attr(me, SUBST, len(me.polygons), -1)
                face_base[o.name] = len(polys)
                for f, fl, sb in zip(me.polygons, flags, subs):
                    vs = [cv.to_game(mw @ me.vertices[i].co, scale) for i in f.vertices]
                    if len(vs) == 3:
                        vs.append(vs[2])
                    if len(vs) != 4:
                        raise ValueError('%s: face %d has %d corners; nav polygons are quads (or triangles)'
                                         % (o.name, f.index, len(vs)))
                    # clockwise seen from above in game x / z, as the game's own
                    area = sum(vs[i][0] * vs[(i + 1) % 4][2] - vs[(i + 1) % 4][0] * vs[i][2] for i in range(4))
                    if area > 0:
                        vs = vs[::-1]
                    polys.append(dict(quad=[tuple(v) for v in vs], flags=int(fl) & 0x3,
                                      substitute=255 if sb < 0 else int(sb)))
            elif o.type == 'MESH':
                link_obs.append(o)
            elif o.type == 'EMPTY' and kind in ('POINT', 'JUMP'):
                pos = cv.to_game(o.matrix_world.translation, scale)
                if kind == 'POINT':
                    navs.append(dict(pos=pos, id=int(o.get('pd_nav_id', len(navs))),
                                     radius=float(o.get('pd_nav_radius', 100.0)), poly=int(o.get('pd_nav_poly', -1))))
                else:
                    pads = [int(x) for x in str(o.get('pd_jump_pads', '')).replace(' ', '').split(',') if x != '']
                    jumps.append(dict(pos=pos, pads=pads, poly=int(o.get('pd_nav_poly', -1))))
    model = dict(polys=polys, links=[], navs=navs, jumps=jumps)
    # the polygon each point lies on: the stored one while it still holds the point, else found again
    for pt in navs + jumps:
        i = pt['poly']
        if not (0 <= i < len(polys) and cad.contains_xz(polys[i], pt['pos'], 8.0)):
            pt['poly'] = cad.poly_at(polys, pt['pos'])
    for j in jumps:
        j['pads'] = [p for p in j['pads'] if 0 <= p < len(polys)]
    # links: the NavLinks mesh while the faces are as it was made for, else made again from the faces
    lob = link_obs[0] if link_obs else None
    mesh_ob = next((o for c in colls for o in c.all_objects if o.type == 'MESH' and o.get('pd_nav') != 'LINKS'), None)
    fresh = (lob is not None and len(link_obs) == 1 and mesh_ob is not None and len(face_base) == 1
             and lob.get('pd_face_count') == len(polys) and lob.get('pd_faces_hash') == _faces_hash(mesh_ob.data))
    if fresh:
        me = lob.data
        mw = lob.matrix_world
        n = len(me.edges)
        pa, pb = _attr(me, 'pd_poly_a', n, -1), _attr(me, 'pd_poly_b', n, -1)
        fl, bl = _attr(me, 'pd_link_flags', n, 0), _attr(me, 'pd_link_blocker', n, 0)
        for k, e in enumerate(me.edges):
            if 0 <= pa[k] < len(polys) and 0 <= pb[k] < len(polys):
                a, b = (cv.to_game(mw @ me.vertices[i].co, scale) for i in e.vertices)
                model['links'].append(dict(a=a, b=b, pa=pa[k], pb=pb[k], flags=fl[k], blocker=bl[k]))
    else:
        model['links'] = navgen.links(polys)
        notes.append('links made from the faces')
    if any(p['substitute'] == 255 for p in polys):
        subs = cad.substitutes(model)
        for p, s in zip(polys, subs):
            if p['substitute'] == 255:
                p['substitute'] = s
    return model, '; '.join(notes)


# ---------------------------------------------------------------- import / export

def import_for_stage(context, root, game_data, stage, scale, variant=0):
    path = original_file(game_data, stage, variant) if game_data else None
    if path is None:
        return 'no nav mesh for %s (the game reads none)' % stage if nav_folder(game_data, stage) is None \
            else 'no nav mesh file found for %s' % stage
    try:
        model = cad.read(open(path, 'rb').read())
    except ValueError as e:
        return 'nav mesh skipped: %s' % e
    build(context, model, scale, parent=root)
    return 'nav mesh: %d polygons, %d links, %d jump points (%s)' % (
        len(model['polys']), len(model['links']), len(model['jumps']), os.path.basename(path))


def export(scene, scale, out_dat_path):
    """Write <name>.cad next to the exported .dat from the scene's Nav Mesh. Returns (path or None, message)."""
    try:
        model, note = read_scene(scene, scale)
    except ValueError as e:
        raise ValueError('Nav Mesh: %s' % e)
    if model is None:
        return None, 'no Nav Mesh collection: the game original\'s AI paths are kept (Generate Nav Mesh for a new map)'
    if not model['polys']:
        return None, 'the Nav Mesh is empty: the game original\'s AI paths are kept'
    try:
        data = cad.write(model)
    except ValueError as e:
        raise ValueError('Nav Mesh: %s' % e)
    path = os.path.splitext(out_dat_path)[0] + '.cad'
    with open(path, 'wb') as f:
        f.write(data)
    msg = 'nav mesh %d polygons, %d links, %d jump points -> %s' % (
        len(model['polys']), len(model['links']), len(model['jumps']), os.path.basename(path))
    return path, msg + ('; ' + note if note else '')


def counts(scene):
    """(polygons, links, nav points, jump points) in the scene's Nav Mesh, or None."""
    colls = collections(scene)
    if not colls:
        return None
    p = l = n = j = 0
    for c in colls:
        for o in c.all_objects:
            kind = o.get('pd_nav')
            if o.type == 'MESH' and kind == 'LINKS':
                l += len(o.data.edges)
            elif o.type == 'MESH':
                p += len(o.data.polygons)
            elif kind == 'POINT':
                n += 1
            elif kind == 'JUMP':
                j += 1
    return p, l, n, j


# ---------------------------------------------------------------- generate

def _scene_inputs(context, scale):
    from . import exporter, objects_export
    from ._lib import objects_build
    tris = exporter.gather_collision(context, scale)
    pads, boxes = [], []
    for oc in exporter.collections_with_role(context.scene, 'OBJECTS'):
        for tc in oc.children:
            preset = getattr(tc, 'pd_preset', 'SOLID')
            cat = objects_build.PRESETS.get(preset, (1,))[0]
            for _key, insts in objects_export._groups(tc):
                for o in insts:
                    if preset == 'JUMP_PAD':
                        power = o.get('pd_jump_power') or getattr(tc, 'pd_jump_power', 150)
                        pads.append((cv.to_game(o.matrix_world.translation, scale), float(power)))
                    elif cat == 2:
                        pts = [cv.to_game(o.matrix_world @ v.co, scale) for v in o.data.vertices]
                        if pts:
                            boxes.append(([min(p[k] for p in pts) for k in range(3)],
                                          [max(p[k] for p in pts) for k in range(3)]))
    spawns = []
    for sc in exporter.collections_with_role(context.scene, 'SPAWNS'):
        for lc in sc.children:
            for s in exporter._spawn_objects(lc):
                spawns.append(cv.to_game(s.matrix_world.translation, scale))
    return tris, pads, boxes, spawns


class PDSTAGE_OT_generate_nav_mesh(bpy.types.Operator):
    """Build the AI navigation mesh from this map's collision: quads where a fighter can stand (reachable from
    the spawns), links between them, drops and jump pad landings. Replaces the Nav Mesh collection's contents"""
    bl_idname = 'pdstage.generate_nav_mesh'
    bl_label = 'Generate Nav Mesh'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        c = counts(context.scene) if context.scene else None
        if c and c[0]:
            cls.poll_message_set('This map already has a nav mesh (delete the Nav_Mesh collection to generate '
                                 'a new one)')
            return False
        return True

    def execute(self, context):
        c = counts(context.scene)
        if c and c[0]:
            self.report({'WARNING'}, 'This map already has a nav mesh: kept. Delete the Nav_Mesh collection to '
                                     'generate a new one')
            return {'CANCELLED'}
        from mathutils import Vector
        from mathutils.bvhtree import BVHTree
        scale = context.scene.pd_scale
        try:
            tris, pads, boxes, spawns = _scene_inputs(context, scale)
        except Exception as e:                     # noqa: BLE001 -- an export check (surface text...)
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        if not tris:
            self.report({'ERROR'}, 'No collision in this scene (a Colliders collection, or Visuals marked as '
                                   'collision): the nav mesh is built from it')
            return {'CANCELLED'}
        verts, faces, index = [], [], {}
        for t in tris:
            f = []
            for v in t[:3]:
                k = (round(v[0], 3), round(v[1], 3), round(v[2], 3))
                if k not in index:
                    index[k] = len(verts)
                    verts.append(k)
                f.append(index[k])
            faces.append(f)
        tree = BVHTree.FromPolygons(verts, faces, all_triangles=True)

        def cast(o, d, dist):
            loc, nrm, idx, dd = tree.ray_cast(Vector(o), Vector(d), dist)
            if loc is None:
                return None
            return tuple(loc), tuple(nrm), idx, dd

        wm = context.window_manager
        wm.progress_begin(0, 10)
        step = [0]

        def progress(cell, n):
            step[0] += 1
            wm.progress_update(min(9, step[0]))
            print('Phantom Dust nav mesh: grid %g -> %d quads' % (cell, n))

        try:
            model, report = navgen.generate(tris, cast, pads=pads, boxes=boxes, spawns=spawns, progress=progress)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        finally:
            wm.progress_end()
        colls = collections(context.scene)
        parent = None
        if not colls:
            from . import exporter
            col = next(iter(exporter.collections_with_role(context.scene, 'COLLIDERS')), None)
            parent = next((p for p in bpy.data.collections if col is not None and col.name in p.children), None)
        build(context, model, scale, parent=parent, coll=colls[0] if colls else None)
        self.report({'INFO'}, 'Nav mesh: ' + report)
        return {'FINISHED'}


# ---------------------------------------------------------------- pink display

_handle = None
_gpu = {}


def _draw():
    ctx = bpy.context
    scene = ctx.scene
    if scene is None or not getattr(scene, 'pd_show_nav', True):
        return
    space = ctx.space_data
    if space is None or getattr(space, 'type', '') != 'VIEW_3D' or not space.overlay.show_overlays:
        return
    try:
        colls = collections(scene)
        if not colls:
            return
        import gpu
        from gpu_extras.batch import batch_for_shader
        if 'shader' not in _gpu:
            try:
                _gpu['shader'] = (gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR'), True)
            except (ValueError, SystemError):
                _gpu['shader'] = (gpu.shader.from_builtin('UNIFORM_COLOR'), False)
        shader, poly = _gpu['shader']
        faces, links_, jumps = [], [], []
        vl = ctx.view_layer
        faces_of = {}
        for c in colls:
            for o in c.all_objects:
                if not o.visible_get(view_layer=vl):
                    continue
                kind = o.get('pd_nav')
                if o.type == 'MESH':
                    me = o.data
                    mw = o.matrix_world
                    co = [mw @ v.co for v in me.vertices]
                    if kind == 'LINKS':
                        for e in me.edges:
                            links_ += [co[e.vertices[0]], co[e.vertices[1]]]
                    else:
                        for e in me.edges:
                            faces += [co[e.vertices[0]], co[e.vertices[1]]]
                        faces_of[o.name] = [sum((co[i] for i in p.vertices), co[0] * 0) / max(1, p.loop_total)
                                            for p in me.polygons]
        centres = next(iter(faces_of.values()), [])
        for c in colls:
            for o in c.all_objects:
                if o.get('pd_nav') == 'JUMP' and o.visible_get(view_layer=vl):
                    for p in str(o.get('pd_jump_pads', '')).split(','):
                        if p.strip().isdigit() and int(p) < len(centres):
                            jumps += [centres[int(p)], o.matrix_world.translation.copy()]
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('LESS_EQUAL')
        shader.bind()
        if poly:
            region = ctx.region
            shader.uniform_float('viewportSize', (region.width, region.height))
        for pts, colour, width in ((faces, PINK, 2.0), (links_, LINK_PINK, 1.5), (jumps, JUMP_COLOUR, 2.0)):
            if not pts:
                continue
            if poly:
                shader.uniform_float('lineWidth', width)
            shader.uniform_float('color', colour)
            batch_for_shader(shader, 'LINES', {'pos': [tuple(p) for p in pts]}).draw(shader)
    except Exception as e:                            # never break the viewport
        if not _gpu.get('_reported'):
            print('Phantom Dust nav mesh: drawing failed:', e)
            _gpu['_reported'] = True
    finally:
        try:
            import gpu
            gpu.state.depth_test_set('NONE')
            gpu.state.blend_set('NONE')
        except Exception:
            pass


def draw_settings(layout, context):
    s = context.scene
    col = layout.column(align=True)
    col.label(text='AI Nav Mesh')
    row = col.row(align=True)
    row.operator(PDSTAGE_OT_generate_nav_mesh.bl_idname, icon='MOD_MESHDEFORM')
    row.prop(s, 'pd_show_nav', text='', icon='HIDE_OFF' if s.pd_show_nav else 'HIDE_ON')
    c = counts(s)
    if c and c[0]:
        col.label(text='Nav mesh present (kept; delete it to regenerate)', icon='CHECKMARK')


classes = (PDSTAGE_OT_generate_nav_mesh,)


def register():
    global _handle
    for c in classes:
        try:
            bpy.utils.register_class(c)
        except ValueError:
            bpy.utils.unregister_class(getattr(bpy.types, c.__name__))
            bpy.utils.register_class(c)
    bpy.types.Scene.pd_show_nav = BoolProperty(
        name='Show Nav Mesh', default=True,
        description='Draw the AI nav mesh in pink (quads, links in light pink, jump pad landings in orange)')
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_VIEW')


def unregister():
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        _handle = None
    _gpu.clear()
    for c in reversed(classes):
        try:
            bpy.utils.unregister_class(c)
        except RuntimeError:
            pass
    if hasattr(bpy.types.Scene, 'pd_show_nav'):
        del bpy.types.Scene.pd_show_nav
