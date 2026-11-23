"""Objects collections -> placed objects (props, breakables, jump pads).

  Objects                 role Objects
    Crate                 one child collection per object type (Collection Properties > Phantom Dust):
                          preset (how it behaves), "debris stays", surface type for its collider
      Crate, Crate.001    every mesh directly in the type collection is one placement: its location, rotation
                          about Z and scale are used. Any number of them: copies (Shift+D), linked duplicates
                          (Alt+D), even different meshes. Each distinct mesh/scale becomes one game object type
                          with the collection's settings; the mesh around its own origin is the intact model.
      Broken...           optional child collection: each mesh is one piece of the broken model
      Debris...           optional child collection: the debris model
      Collider...         optional child collection: the collision shape (default: a box around the model)
  Broken, Debris and Collider meshes are modelled around the world origin (= the object's own origin) at scale 1;
  a scaled placement scales them with it.
"""
import math
import re

from mathutils import Matrix

from ._lib import alr_build, objects_build
from .objects_import import part_kind
from . import convert as cv
from .visuals_export import mesh_parts, resolve, to_meshes


class ObjectsError(Exception):
    pass


def _child(coll, prefix):
    return next((c for c in coll.children if c.name.lower().startswith(prefix)), None)


def _box(lo, hi, surface):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    c = lambda i: (x1 if i & 1 else x0, y1 if i & 2 else y0, z1 if i & 4 else z0)
    quads = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    out = []
    for q in quads:
        a, b, cc, d = (c(i) for i in q)
        out += [(a, b, cc, surface), (a, cc, d, surface)]
    # make every normal point outwards from the centre
    mid = [(lo[k] + hi[k]) / 2 for k in range(3)]
    fixed = []
    for a, b, cc, s in out:
        u = [b[k] - a[k] for k in range(3)]
        v = [cc[k] - a[k] for k in range(3)]
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        f = [(a[k] + b[k] + cc[k]) / 3 - mid[k] for k in range(3)]
        fixed.append((a, b, cc, s) if sum(n[k] * f[k] for k in range(3)) > 0 else (a, cc, b, s))
    return fixed


def _collider_tris(depsgraph, items, scale, surface):
    """items: [(object, matrix into the object type's local space)]. An object's own surface (pd_surface) wins."""
    tris = []
    for ob, mw in items:
        if ob.type != 'MESH':
            continue
        st = cv.surface_value(getattr(ob, 'pd_surface', ''), surface)
        ev = ob.evaluated_get(depsgraph)
        me = ev.to_mesh()
        try:
            me.calc_loop_triangles()
            co = [cv.to_game(mw @ v.co, scale) for v in me.vertices]
            flip = mw.determinant() < 0
            for lt in me.loop_triangles:
                a, b, c = (co[i] for i in lt.vertices)
                tris.append((a, b, c, st) if flip else (a, c, b, st))      # mirror: see convert.py
        finally:
            ev.to_mesh_clear()
    return tris


def _groups(tc):
    """Placements of one type collection, grouped by what they look like: objects that share a mesh and a scale
    become one game object type (the game stores one model per type). Copies (Shift+D), linked duplicates (Alt+D),
    other meshes and scaled copies can all sit in the same collection."""
    groups = {}
    for o in sorted((o for o in tc.objects if o.type == 'MESH' and not part_kind(o) and
                     not (o.parent is not None and (part_kind(o.parent) or o.parent.get('pd_part')))),
                    key=lambda o: cv.natural_key(o.name)):
        sc = tuple(round(x, 4) for x in o.matrix_world.to_scale())
        groups.setdefault((_mesh_key(o), sc), []).append(o)
    return list(groups.items())


def _mesh_key(o):
    """Same geometry = same model, even for separate copies (Shift+D) of one mesh."""
    me = o.data
    import hashlib
    h = hashlib.blake2b(digest_size=12)
    h.update(str((len(me.vertices), len(me.polygons), len(me.loops))).encode())
    for v in me.vertices:
        h.update(('%.4f %.4f %.4f;' % tuple(v.co)).encode())
    h.update(str([s.material.name if s.material else '' for s in o.material_slots]).encode())
    return h.hexdigest()


def gather(context, obj_colls, scale, textures):
    """Returns (types, stats). Each type: dict(name, models=[intact, broken, debris] (None if absent; model =
    dict(meshes, nodes)), collision, category, type, placements=[dict(pos, rot)]).
    One type collection gives one game object type per distinct mesh (and scale) among its objects."""
    depsgraph = context.evaluated_depsgraph_get()
    types, stats = [], dict(clamped_uv=0)
    for oc in obj_colls:
        for tc in oc.children:
            groups = _groups(tc)
            for g, ((_key, sc), insts) in enumerate(groups):
                name = tc.name if len(groups) == 1 else '%s_%d' % (tc.name, g + 1)
                t = _object_type(depsgraph, tc, name, insts, sc, scale, textures, stats)
                if t is None:
                    stats['skipped'] = stats.get('skipped', 0) + 1
                else:
                    types.append(t)
    return types, stats


def tc_scene(tc):
    import bpy
    return bpy.context.scene.pd_game_original


def _object_type(depsgraph, tc, name, insts, sc, scale, textures, stats):
    if any(x <= 0 for x in sc):
        raise ObjectsError('%s is mirrored (negative scale); apply the scale (Ctrl+A) first' % insts[0].name)
    preset = getattr(tc, 'pd_preset', 'SOLID')
    category, typ, _desc, _states = objects_build.PRESETS[preset]
    if preset == 'GAME':                                   # kept from an imported map
        category, typ = int(tc.pd_category), int(tc.pd_type)
    from . import surfaces
    surface = cv.surface_value(getattr(tc, 'pd_surface', ''), surfaces.default_for(tc_scene(tc)))

    # Per-node values the game reads (see FORMATS.md): intact root value 3 = hits to break (min 1); value 2 =
    # damage, on the debris root when there is debris (else on the intact root); debris root value 1 = 2 makes
    # the debris go away after breaking, 0 leaves it lying there. Broken roots are all zero in the game's files.
    # "dmg:N" in the collection name sets the damage (the importer names collections that way).
    hits = max(1, min(255, int(getattr(tc, 'pd_hits', 1))))
    tag = re.search(r'dmg:\s*(\d+)', tc.name, re.I)
    damage = max(0, min(255, int(tag.group(1)) if tag else int(getattr(tc, 'pd_damage', 2))))

    # intact model: the shared mesh around its own origin, with the placements' scale built in
    size = Matrix.Diagonal((sc[0], sc[1], sc[2], 1.0))
    no_model = any(o.get('pd_no_model') for o in insts)    # e.g. the game's jump pads: only a trigger collider
    if preset == 'JUMP_PAD' and not getattr(tc, 'pd_pad_visible', False):
        no_model = True                                     # an invisible trigger: the mesh only sets its shape
    intact = [] if no_model else resolve(to_meshes(mesh_parts(depsgraph, insts[0], size, scale, textures, stats)))
    models = [None if no_model else
              dict(meshes=intact, nodes=[dict(flags=0x0004, values=_root_values(
                  insts, 0, (0, 0, hits if hits > 1 else 0, 0)))]),
              None, None]

    # Parts: objects parented to a placement, in that placement's own space, recognised by their name prefix
    # (collider_, collider_broken_, collider_debris_, break_, stay_, debris_; pd_part as set by the importer is
    # the fallback); else the type collection's Broken / Debris / Collider child collections, modelled around the
    # world origin.
    owner = next((o for o in insts if any(part_kind(c) for c in o.children)), None)
    inv = owner.matrix_world.inverted() if owner is not None else Matrix.Identity(4)

    def parts(kind):
        if owner is not None:
            return [(c, size @ inv @ c.matrix_world) for c in sorted(owner.children, key=lambda c: cv.natural_key(c.name))
                    if part_kind(c) == kind]
        coll = _child(tc, kind)
        return [(o, size @ o.matrix_world) for o in coll.all_objects if o.parent is None or
                o.parent.name not in coll.all_objects] if coll is not None else []

    # Broken model: node 0 = root (damage), then one node per piece (child of the root) followed by its own
    # children's nodes (shadow, detail: they move with the piece). Piece values as in the game's files: value 1
    # = the flying piece can hurt players (the game's pieces use 2-4), marker STAY_MARKER = the piece stays.
    hurt = getattr(tc, 'pd_pieces_hurt', True)
    pieces = [(o, m) for o, m in parts('broken') if o.type == 'MESH']
    if pieces:
        meshes, nodes = [], [dict(flags=0x0000, values=_root_values(insts, 1, (0, 0, 0, 0)))]
        for p, m in pieces:
            k = len(nodes)
            v = (int(p.get('pd_piece_value', 0) or 0) or 4) if hurt else 0     # the game's pieces use 2-4
            stay = p.name.lower().startswith('stay_') or (not p.name.lower().startswith('break_') and p.get('pd_stay'))
            own = resolve(to_meshes(mesh_parts(depsgraph, p, m, scale, textures, stats), node=k))
            nodes.append(dict(flags=0x0004, parent=0, values=(v, 0, 0, 0), box=_mass_box(own, p),
                              marker=alr_build.STAY_MARKER if stay else 0xFFFFFFFF))
            meshes += own
            for c in sorted((c for c in p.children_recursive if c.type == 'MESH'), key=lambda c: cv.natural_key(c.name)):
                nodes.append(dict(flags=0x0004, parent=k))
                meshes += resolve(to_meshes(mesh_parts(depsgraph, c, size @ inv @ c.matrix_world if owner else
                                                       size @ c.matrix_world, scale, textures, stats), node=len(nodes) - 1))
        if meshes:
            models[1] = dict(meshes=meshes, nodes=nodes)
    debris = [(o, m) for o, m in parts('debris') if o.type == 'MESH']
    if debris:
        dparts = {}
        for p, m in debris:
            mesh_parts(depsgraph, p, m, scale, textures, stats, dparts)
        meshes = resolve(to_meshes(dparts))
        if meshes:
            stays = getattr(tc, 'pd_debris_stays', False)
            models[2] = dict(meshes=meshes, nodes=[dict(flags=0x0004, box=_mass_box(meshes, debris[0][0]),
                                                        values=_root_values(insts, 2, (0 if stays else 2, damage, 0, 0)))])

    if models[0] is not None:                               # damage on the intact root when there is no debris
        models[0]['nodes'][0]['values'] = _root_values(
            insts, 0, (0, damage if models[2] is None else 0, hits if hits > 1 else 0, 0),
            known=(1, 2) if models[2] is None else (2,))

    if no_model:
        collision = _collider_tris(depsgraph, [(insts[0], size)], scale, surface)
    else:
        collision = _collider_tris(depsgraph, parts('collider'), scale, surface)
    if not collision and intact:
        pts = [v[0] for m in intact for v in m['verts']]
        lo = tuple(min(p[k] for p in pts) for k in range(3))
        hi = tuple(max(p[k] for p in pts) for k in range(3))
        collision = _box(lo, hi, surface)
    collisions = [collision] + [_collider_tris(depsgraph, parts(k), scale, surface) or None
                                for k in ('collider_broken', 'collider_debris')]
    if models[1] is None:
        collisions[1] = None
    if models[2] is None:
        collisions[2] = None

    # the object's own effects (dust when it breaks...), kept from an imported map: only valid in that map
    effects = None
    src = next((o for o in insts if o.get('pd_object_effects')), None)
    if src is not None and src.get('pd_object_effects_map', '') == tc_scene(tc):
        effects = [bytes.fromhex(x) if x else None for x in src['pd_object_effects']]
        if models[1] is None:
            effects[1] = None
        if models[2] is None:
            effects[2] = None

    placements = []
    for o in insts:
        mw = o.matrix_world
        rot = cv.rot_to_game([list(r) for r in mw.to_3x3().normalized()])     # any rotation, as the game's own
        p = dict(pos=cv.to_game(mw.translation, scale), rot=rot)
        if o.get('pd_extra'):                              # spare placement bytes kept from an imported map
            p['extra'] = tuple(int(x) for x in o['pd_extra'])
        placements.append(p)
    if preset == 'JUMP_PAD':
        # The game's jump pads put the jump strength in the first spare placement byte (100-250).
        power = max(1, min(255, int(getattr(tc, 'pd_jump_power', 150))))
        for p in placements:
            p['extra'] = (power, 0)
    anims = None
    src = next((o for o in insts if o.get('pd_object_anims')), None)
    if src is not None:
        anims = [bytes.fromhex(x) if x else None for x in src['pd_object_anims']]
        for k in (1, 2):
            if models[k] is None:
                anims[k] = None
    if (category, typ) in objects_build.NEEDS_ANIMATION and not (anims and any(anims)):
        print('Phantom Dust export warning: %s (game type %d-%d) moves by an animation it no longer has; '
              'left out (the game would crash)' % (tc.name, category, typ))
        return None
    sounds = [0xFFFF] * 8                                  # kept from an imported map, else none
    src = next((o for o in insts if o.get('pd_object_sounds')), None)
    if src is not None:
        sounds = [int(x) for x in src['pd_object_sounds']][:8] + [0xFFFF] * 8
    for k, prop in ((1, 'pd_break_sound'), (2, 'pd_piece_sound')):
        choice = getattr(tc, prop, 'KEEP')
        if choice != 'KEEP':
            sounds[k] = int(choice, 16)
    return dict(name=name, models=models, collision=collision, collisions=collisions, effects=effects, anims=anims,
                sounds=sounds, category=category, type=typ, placements=placements, preset=preset)


def _mass_box(meshes, ob):
    """One box around the whole piece, written on every mesh of it: the game weighs a piece (and gives it its
    physics shape) by the box of one of its meshes, so a piece split into several meshes would come out too light."""
    pts = [v[0] for m in meshes for v in m.get('verts', ())]
    if not pts:
        return None
    return [min(p[k] for p in pts) for k in range(3)], [max(p[k] for p in pts) for k in range(3)]


def _root_values(insts, state, values, known=None):
    """A state's root node values: the settings the add-on knows (hits, damage, debris stays) over the ones an
    imported object came with (pd_root_values), so values without a setting survive the round trip."""
    src = next((o for o in insts if o.get('pd_root_values')), None)
    if src is None:
        return tuple(values)
    try:
        kept = [float(x) for x in src['pd_root_values'][state]]
    except (IndexError, TypeError, ValueError):
        return tuple(values)
    known = known if known is not None else {0: (2,), 1: (), 2: (0, 1)}[state]
    return tuple(values[k] if k in known else kept[k] for k in range(4))


def add_to_files(types, alr_add_models, alr_added_roots):
    """After the .alr is built (models added in order), turn types into objects_build inputs."""
    objects, placements = [], []
    k = 0
    for t in types:
        roots = []
        for m in t['models']:
            if m is None:
                roots.append(None)
            else:
                roots.append(alr_added_roots[k])
                k += 1
        idx = len(objects)
        objects.append(dict(name=t['name'][:31], roots=tuple(roots), collision=t['collision'],
                            collisions=t.get('collisions'), effects=t.get('effects'), anims=t.get('anims'),
                            sounds=t.get('sounds')))
        for p in t['placements']:
            placements.append(dict(object=idx, category=t['category'], type=t['type'], pos=p['pos'], rot=p['rot'],
                                   extra=p.get('extra', (0, 0))))
    return objects, placements
