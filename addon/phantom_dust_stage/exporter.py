"""Export a Blender scene as an game_original .dat.

Works on any scene: collections are found by their Phantom Dust role (Collection Properties > Phantom Dust).
The exported file starts from a base game_original's .dat (the stage slot being replaced), which supplies the parts
not authored in Blender, then:

- Colliders: every mesh under a Colliders collection, modifiers applied, world space. Surface type comes from
  the nearest collection with a surface set (default 08). Written as a new collision block appended to the end
  of the file (confirmed in game). Without a Colliders collection the game original's collision is kept.
- Spawn Points: each child collection is a layout; each spawn is an empty whose +Y axis is the facing, with
  exactly 3 child empties as orb points. The base game_original fixes how many layouts there are and how many spawns
  each has (4 in most maps, some single-player layouts 1). Fewer layouts or spawns are repeated to fill, extra ones
  are left out (a warning in the System Console). Without a Spawn Points collection the game original's spawns are
  kept.
- Lighting (Scene Properties > Phantom Dust Lighting, when enabled): the light colours and sun direction for the
  stage (with objects and effects) and for characters, written into the game original's light script.
"""
import os
import struct

import numpy as np

from mathutils import Vector

from ._lib import dat, collision_build
from . import surfaces
from . import convert as cv


class ExportError(Exception):
    pass


def collections_with_role(scene, role):
    return [c for c in scene.collection.children_recursive if getattr(c, 'pd_role', 'NONE') == role]


BACKUP_DIR = 'pd_addon_backup'       # inside Assets\Data\Map: the game's own files, saved before an install


def _child(parent, name):
    """parent/name, matching the name in any letter case (Linux file systems are case-sensitive and the game's
    files may be MAP/ST03.ALR there), or None."""
    p = os.path.join(parent, name)
    if os.path.exists(p):
        return p
    try:
        low = name.lower()
        return next((os.path.join(parent, n) for n in os.listdir(parent) if n.lower() == low), None)
    except OSError:
        return None


def _resolve(path):
    """An existing path for `path` with each folder matched in any letter case (as typed on Windows), else as is."""
    if os.path.exists(path):
        return path
    head, parts = path, []
    while head and not os.path.exists(head):
        head, tail = os.path.split(head)
        if not tail:
            break
        parts.append(tail)
    cur = head
    for part in reversed(parts):
        cur = _child(cur, part) if cur else None
        if cur is None:
            return path
    return cur


def map_dir(game_data):
    """The game's Map folder for the data folder setting. Accepts Assets/Data (as asked), and also the game folder,
    Assets, or the Map folder itself; any letter case; ~ for the home folder."""
    gd = _resolve(os.path.abspath(os.path.expanduser((game_data or '').strip())))
    for parts in (('Map',), ('Data', 'Map'), ('Assets', 'Data', 'Map'), ()):
        d = gd
        for part in parts:
            d = _child(d, part) if d else None
        if d and os.path.isdir(d) and any(n.lower().endswith('.alr') for n in os.listdir(d)):
            return d
    return os.path.join(gd, 'Map')


def missing_hint(game_data):
    """Why the game's files can't be found, for error messages."""
    gd = _resolve(os.path.abspath(os.path.expanduser((game_data or '').strip())))
    if not os.path.isdir(gd):
        hint = 'the game data folder is not visible to Blender: %s' % gd
        if os.sep == '/':
            hint += ('. If Blender is a Flatpak (Bazzite, Steam Deck...), give it access: flatpak override --user '
                     '--filesystem=%s org.blender.Blender (then restart Blender)' % gd)
        return hint
    return 'no map files in %s (set the data folder to the game\'s Assets/Data)' % map_dir(game_data)


def original_path(game_data, filename):
    """The game's own copy of Map\\filename: the add-on's backup if a map was installed over it."""
    mdir = map_dir(game_data)
    bdir = _child(mdir, BACKUP_DIR)
    backup = _child(bdir, filename) if bdir else None
    if backup and os.path.isfile(backup):
        return backup
    return _child(mdir, filename) or os.path.join(mdir, filename)


def game_original_dat(game_data, game_original):
    return original_path(game_data, game_original + '.dat')


def game_original_alr(game_data, game_original):
    return original_path(game_data, game_original + '.alr')


def install(game_data, game_original, dat_path, alr_path):
    """Copy an exported map over the game original's files, backing up the originals once.
    Returns the files written."""
    import shutil
    mdir = map_dir(game_data)
    bdir = _child(mdir, BACKUP_DIR) or os.path.join(mdir, BACKUP_DIR)
    os.makedirs(bdir, exist_ok=True)
    done = []
    for src, name in ((dat_path, game_original + '.dat'), (alr_path, game_original + '.alr')):
        if src is None:                       # nothing new for this file: the game's own one belongs there
            src = os.path.join(bdir, name)
            if not os.path.isfile(src):
                continue
        dst = _child(mdir, name) or os.path.join(mdir, name)
        if not os.path.isfile(os.path.join(bdir, name)):
            shutil.copy2(dst, os.path.join(bdir, name))
        shutil.copyfile(src, dst)
        done.append(dst)
    return done


def restore(game_data, game_original):
    """Put the game original files back from the backup. Returns the files restored."""
    import shutil
    mdir = map_dir(game_data)
    done = []
    for name in (game_original + '.dat', game_original + '.alr'):
        b = os.path.join(mdir, BACKUP_DIR, name)
        if os.path.isfile(b):
            shutil.copyfile(b, _child(mdir, name) or os.path.join(mdir, name))
            done.append(name)
    return done


def _spawn_objects(layout_coll):
    obs = set(layout_coll.all_objects)
    return sorted((o for o in obs if o.type == 'EMPTY' and (o.parent is None or o.parent not in obs)),
                  key=lambda o: cv.natural_key(o.name))


def gather_spawns(sp_coll, scale):
    layouts = []
    children = sorted(sp_coll.children, key=lambda c: cv.natural_key(c.name))
    if not children:
        raise ExportError('%s has no layout collections; put the spawns in a child collection like LAYOUT_1'
                          % sp_coll.name)
    for lc in children:
        entries = []
        for s in _spawn_objects(lc):
            orbs = sorted(s.children, key=lambda o: cv.natural_key(o.name))
            if len(orbs) != 3:
                raise ExportError('%s has %d orb children; each spawn needs exactly 3' % (s.name, len(orbs)))
            mw = s.matrix_world
            entries.append((cv.to_game(mw.translation, scale),
                            cv.yaw_to_game(mw.to_euler('XYZ').z),
                            [cv.to_game(o.matrix_world.translation, scale) for o in orbs]))
        layouts.append((lc.name, entries))
    return layouts


SPAWN_TOLERANCE = 1e-3       # game units (0.1 mm): what float32 rounding through Blender's transforms leaves


def _same_spawn(s, pos, yaw, orbs):
    """The scene's spawn equals the file's entry s up to float rounding (yaw compared as an angle: the game's pi
    comes back from Blender as -pi)."""
    if any(abs(a - b) > SPAWN_TOLERANCE for a, b in zip(s.pos, pos)):
        return False
    if any(abs(a - b) > SPAWN_TOLERANCE for o, p in zip(s.orbs, orbs) for a, b in zip(o, p)):
        return False
    return abs(cv.wrap(s.yaw - yaw)) < 1e-5


def _tables(b, n):
    """The first n object names (NUL included), definitions and sound rows of a .dat, as bytes."""
    names, p = [], struct.unpack_from('<I', b, dat.H_NAMES)[0]
    for _ in range(n):
        e = bytes(b).index(b'\0', p)
        names.append(bytes(b[p:e + 1]))
        p = e + 1
    t, s = struct.unpack_from('<I', b, dat.H_OBJECTS)[0], struct.unpack_from('<I', b, dat.H_OBJECT_SOUNDS)[0]
    return (b''.join(names), bytes(b[t:t + 0x38 * n]),
            bytes(b[s:s + 16 * n]) if s != dat.NONE else b'\xff' * (16 * n))


def _add_object_types(b, objects):
    """Append object types after the game original's own: names, definitions and sound rows are copied into new
    tables (original entries first, unchanged, then the new ones, with their collision, effect and animation
    blocks); the placement lists stay where they are. Returns (bytearray, index of the first new type)."""
    from ._lib import objects_build
    n = struct.unpack_from('<I', b, dat.H_OBJECT_COUNT)[0]
    old_names, old_table, old_sounds = _tables(b, n)
    layout_words = bytes(b[dat.H_LAYOUT_SLOTS:dat.H_LAYOUT_SLOTS + 0x58])      # placement lists and counts
    # the new types' own blocks and tables as add_objects writes them (appended, so every offset stays valid)
    nb = bytearray(objects_build.add_objects(bytes(b), objects, []))
    m = len(objects)
    new_names, new_table, new_sounds = _tables(nb, m)
    nb[dat.H_LAYOUT_SLOTS:dat.H_LAYOUT_SLOTS + 0x58] = layout_words
    nb += b'\0' * (-len(nb) % 4)
    nb += b'NM00'
    struct.pack_into('<I', nb, dat.H_NAMES, len(nb))
    nb += old_names + new_names
    nb += b'\0' * (-len(nb) % 4)
    nb += b'OB00'
    struct.pack_into('<I', nb, dat.H_OBJECTS, len(nb))
    nb += old_table + new_table
    nb += b'OS00'
    struct.pack_into('<I', nb, dat.H_OBJECT_SOUNDS, len(nb))
    nb += old_sounds + new_sounds
    struct.pack_into('<I', nb, dat.H_OBJECT_COUNT, n + m)
    struct.pack_into('<I', nb, dat.H_FILE_SIZE, len(nb))
    return nb, n


def _f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def _import_scale(scale):
    """The scale the import used (importer.import_stage keeps it as typed; the scene property holds a float32)."""
    return float('%.6g' % scale)


def _from_file(old, now, scale):
    """A moved position written as the file's value plus how far it moved from where the import put it (a 32-bit
    float of value * scale in Blender): moving it back gives the file's value again, not float noise."""
    s = _import_scale(scale)
    return tuple(o + (n - _f32(o * s) / scale) for o, n in zip(old, now))


def _as_imported(now, scale):
    """For a new value read from Blender (value * scale held as a 32-bit float): the 32-bit float next to it that an
    import would put at exactly that Blender value, so a game value typed back in Blender comes back as it was."""
    import math
    s = _import_scale(scale)
    out = []
    for n in now:
        held = _f32(n * scale)                     # what Blender holds
        g = _f32(n)
        cands = [g] + [_f32(g + k * math.ulp(g or 1e-30)) for k in (-3, -2, -1, 1, 2, 3)]
        hits = [c for c in cands if _f32(c * s) == held]
        out.append(min(hits, key=lambda c: abs(c - n)) if hits else g)
    return tuple(out)


def _moved_spawn(s, pos, yaw, orbs, scale):
    """The values to write for a moved spawn s: its position from the file's value (_from_file); the yaw kept when
    it did not turn; an orb that moved along with its spawn moved by the same offset, else as the scene has it."""
    new_pos = _from_file(s.pos, pos, scale)
    d = [n - o for n, o in zip(new_pos, s.pos)]
    new_orbs = []
    for o_file, o_now in zip(s.orbs, orbs):
        along = tuple(o_file[k] + d[k] for k in range(3))
        new_orbs.append(along if all(abs(along[k] - o_now[k]) <= SPAWN_TOLERANCE for k in range(3)) else o_now)
    return new_pos, (s.yaw if abs(cv.wrap(s.yaw - yaw)) < 1e-5 else yaw), new_orbs


def _write_placement(b, off, p, scale=None):
    """Write a placement's position, turn (and spare bytes) into its .dat entry when they differ from the
    file's beyond float rounding; each only when it changed (a moved position as _from_file when the scale is
    given). Returns 1 when written."""
    import struct
    pos, rot = struct.unpack_from('<3f', b, off + 0x0C), struct.unpack_from('<3f', b, off + 0x18)
    extra = tuple(b[off + 6:off + 8])
    same_pos = all(abs(x - y) <= SPAWN_TOLERANCE for x, y in zip(pos, p['pos']))
    same_rot = all(abs(x - y) < 1e-5 for r, q in zip(cv._rot_game(rot), cv._rot_game(p['rot'])) for x, y in zip(r, q))
    same_extra = 'extra' not in p or tuple(p['extra']) == extra
    if same_pos and same_rot and same_extra:
        return 0
    if not same_pos:
        struct.pack_into('<3f', b, off + 0x0C, *(_from_file(pos, p['pos'], scale) if scale else p['pos']))
    if not same_rot:
        struct.pack_into('<3f', b, off + 0x18, *p['rot'])
    if not same_extra:
        b[off + 6:off + 8] = bytes(p['extra'])
    return 1


def _table_room(b, start):
    """Where the space of a placement list starting at `start` ends: the next section tag (the next list's PS0x,
    or NM00) on a 4-byte step after it. The game's lists are packed, so this is the end of the list itself unless
    an earlier export shortened it."""
    import re
    m = re.compile(rb'PS0.|NM00')
    end = min(len(b), start + 0x24 * 4096)
    for o in range(start, end - 3, 4):
        if m.match(bytes(b[o:o + 4])):
            return o
    return None


def _write_placement_table(b, kept, new, scale=None):
    """Objects added or deleted: the placement list they were imported from is written again with its own entries
    in their order (deleted ones left out), then the added ones (each a copy of a same-type entry with its own
    position and turn). Written where the list is when it fits (deleting only shortens it), else appended to the
    file with its tag; written back at its own place in the file when it fits there again (an added object deleted
    again), dropping an appended copy at the end of the file. The other placement lists, the object definitions
    and models stay. Returns (bytearray, report)."""
    keep = set(kept)
    slot = next(((s, off, cnt) for s, off, cnt in dat.placement_tables(b)
                 if any(off <= k < off + 0x24 * cnt for k in keep)), None)
    if slot is None:
        return b, 'objects: no placement list holds the imported objects: kept as they are'
    s, off, cnt = slot
    entries = [bytes(b[off + 0x24 * i:off + 0x24 * (i + 1)]) for i in range(cnt)]
    out = [e for i, e in enumerate(entries) if off + 0x24 * i in keep]
    removed = cnt - len(out)
    for p, tmpl in new:
        e = bytearray(b[tmpl:tmpl + 0x24])
        struct.pack_into('<3f', e, 0x0C, *(_as_imported(p['pos'], scale) if scale else p['pos']))
        struct.pack_into('<3f', e, 0x18, *(x + 0.0 for x in p['rot']))      # no -0.0 (the game's files have none)
        if 'extra' in p:
            e[6:8] = bytes(p['extra'])
        out.append(bytes(e))
    if not removed and not new:
        return b, 'objects: placements kept'
    body = b''.join(out)
    tag = bytes(b[off - 4:off])
    names = struct.unpack_from('<I', b, dat.H_NAMES)[0]
    home = bytes(b).find(tag, 0x13C, names) if names != dat.NONE else -1
    home = home + 4 if home >= 0 else None
    at_end = off + 0x24 * cnt == len(b) and home is not None and off > names     # a copy an earlier export appended
    where = None
    for cand in ([home] if home is not None and home != off else []) + [off]:
        room = _table_room(b, cand + (0x24 * cnt if cand == off else 0))
        if cand == off:
            room = len(b) if at_end else room
        if room is not None and cand + len(body) <= room:
            where = cand
            break
    if where is None:                             # longer than its space: appended with its tag
        if at_end:
            del b[off - 4:]
        where = len(b) + 4
        b += tag + body
        msg = 'appended to the file'
    else:
        b[where:where + len(body)] = body
        msg = 'in place' if where == off else 'back in its own place'
        if where != off and at_end:
            del b[off - 4:]                       # the copy an earlier export appended
    struct.pack_into('<I', b, dat.H_LAYOUT_SLOTS + 4 * s, where)
    struct.pack_into('<I', b, dat.H_LAYOUT_COUNTS + 4 * s, len(out))
    struct.pack_into('<I', b, dat.H_FILE_SIZE, len(b))
    return b, 'objects: %d added, %d deleted, the placement list written %s (%d entries); the rest kept as the '               'game original has it' % (len(new), removed, msg, len(out))


def _surface(owner, inherited):
    try:
        st = cv.surface_value(getattr(owner, 'pd_surface', ''), inherited)
    except ValueError:
        raise ExportError('%s: surface "%s" is not a hex number like 08' % (owner.name, owner.pd_surface))
    if not 0 <= st <= 0xFE:
        raise ExportError('%s: surface must be 00-FE' % owner.name)
    return st


def collision_collections(scene):
    """Collections whose meshes become collision, with their surface: everything under a Colliders collection,
    and Visuals collections (not their Sky / Background) with "Use as collision" on, inherited by children.
    Parents first."""
    from . import surfaces
    from .visuals_export import _slot_for
    found = []

    def walk(c, inherited):
        st = _surface(c, inherited)
        found.append((c, st))
        for ch in c.children:
            walk(ch, st)

    def walk_visuals(c, collide, inherited, slot):
        slot = _slot_for(c.name, slot)
        if slot != 0:                                 # the sky and background are never walkable
            return
        collide = collide or getattr(c, 'pd_collide', False)
        st = _surface(c, inherited) if collide else inherited
        if collide:
            found.append((c, st))
        for ch in c.children:
            walk_visuals(ch, collide, st, slot)

    default = surfaces.DEFAULT
    for c in collections_with_role(scene, 'COLLIDERS'):
        walk(c, default)
    for c in collections_with_role(scene, 'VISUALS'):
        walk_visuals(c, False, default, 0)
    return found


def floors_below_kill_height(tris):
    """Walkable collision triangles (facing up, not a wall-only surface) with a corner below the game's fall-out
    height."""
    n = 0
    for v0, v1, v2, st in tris:
        if st in surfaces.WALL_ONLY or min(v0[1], v1[1], v2[1]) >= surfaces.KILL_HEIGHT:
            continue
        u = [v1[k] - v0[k] for k in range(3)]
        w = [v2[k] - v0[k] for k in range(3)]
        ny = u[2] * w[0] - u[0] * w[2]
        ln = sum(c * c for c in (u[1] * w[2] - u[2] * w[1], ny, u[0] * w[1] - u[1] * w[0])) ** 0.5
        if ln > 0 and abs(ny) / ln > 0.5:
            n += 1
    return n


def gather_collision(context, scale):
    found = collision_collections(context.scene)
    depsgraph = context.evaluated_depsgraph_get()
    tris, seen = [], set()
    for coll, st in found:
        for ob in coll.objects:
            if ob.type != 'MESH' or ob.name in seen:
                continue
            seen.add(ob.name)
            ost = _surface(ob, st)                   # an object can override its collection's surface
            ev = ob.evaluated_get(depsgraph)
            me = ev.to_mesh()
            try:
                me.calc_loop_triangles()
                mw = ob.matrix_world
                flip = mw.determinant() < 0
                # in double precision (matrix @ vector in mathutils is single precision: a moved mesh came back
                # with more float noise than the file's own values have)
                v = np.empty(len(me.vertices) * 3, dtype=np.float32)
                me.vertices.foreach_get('co', v)
                m = np.array([list(r) for r in mw], dtype=np.float64)
                w = v.astype(np.float64).reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
                co = [cv.to_game(p, scale) for p in w.tolist()]
                for lt in me.loop_triangles:
                    a, b, c3 = (co[i] for i in lt.vertices)
                    # the mirror to game space reverses winding; a mirrored object reverses it once more
                    tris.append((a, b, c3, ost) if flip else (a, c3, b, ost))
            finally:
                ev.to_mesh_clear()
    return tris


RESOURCE_LIMIT = 20 * 1024 * 1024   # the game loads a model file's vertex + texture data into 20 MiB (see export_models)
COLLISION_GUIDE = 10000  # collision triangles: the game's maps use 2,700-9,300; a 52k one crashed on load
CARRIED_MODELS = {}      # (home map, MD00 slot) -> (new .alr root, model name), from the last export_models


def model_inputs(context, base, game_data, scale, background_and_sky=True, shadows=True, compress_textures='ALL'):
    """What the .alr export reads from the scene, before anything is written: dict(replace (visual roots), types
    (objects), textures, fx_models/fx_keys/fx_names (effect models of other maps), casters, report, ...).
    Also used by the import to record the scene's starting point (roundtrip.py)."""
    from . import objects_export as ox
    from . import visuals_export as vx
    scene = context.scene
    vis_cols = collections_with_role(scene, 'VISUALS')
    obj_cols = collections_with_role(scene, 'OBJECTS')
    textures = vx.Textures(vx.alr.textures(base), compress=compress_textures)
    report = []
    try:
        replace, vstats = vx.gather(context, vis_cols, scale, textures) if vis_cols else ({}, dict(clamped_uv=0))
    except vx.VisualsError as e:
        raise ExportError(str(e))
    if not background_and_sky:
        replace = {k: v for k, v in replace.items() if k == 0}
    if scene.pd_sky_custom:
        from . import sky
        from ._lib import sky_build
        built_sky = sky_build.build_sky(base, **sky.settings(scene, textures))
        extra = replace.get(2, [])
        if isinstance(extra, dict):                          # the game's dome with its joints: in world space
            extra = [m for m in extra['meshes'] if m.get('node', 0) == 0] if extra['nodes'] else []
        for m in extra:                                      # Sky collection meshes (if exported) on top,
            m['node'] = built_sky['extra_node']              # on the sky's own untransformed node
        built_sky['meshes'] = built_sky['meshes'] + list(extra)
        replace[2] = built_sky
        report.append('custom sky%s: gradient dome, clouds, sun %s' % (
            ' (%s)' % scene.pd_sky_preset if scene.pd_sky_preset else '',
            'turned to the scene Sun' if sky.sun_direction(scene) else 'as the replaced map has it'))
    from . import realtime
    casters = realtime.shadow_meshes(context, scale) if shadows and 0 in replace else []
    # the visuals' part of the new textures (objects add theirs after): what the visuals digest covers
    vis_textures = [dict(t) for t in textures.new]
    try:
        types, ostats = ox.gather(context, obj_cols, scale, textures) if obj_cols else ([], dict(clamped_uv=0))
    except ox.ObjectsError as e:
        raise ExportError(str(e))
    # effect models of imported effects from another map (Storm Refinery's sea...): copied in as extra roots
    from . import effects_export
    fx_models, fx_keys, fx_names = effects_export.foreign_models(scene, game_data, len(vx.alr.textures(base)),
                                                                 textures.new)
    placement_type = {}
    placed = ox.placed_entries(obj_cols, scale, placement_type) if obj_cols else None
    import bpy
    sources = {}                                  # object name -> [[root, mesh index], ...] in the game file
    for name in {m.get('object') for k in (0, 1) for m in _model_meshes(replace.get(k))} | {c['name'] for c in casters}:
        ob = bpy.data.objects.get(name or '')
        if ob is not None and (ob.get('pd_mesh') or ob.get('pd_meshes')):
            src = [list(ob['pd_mesh'])] if ob.get('pd_mesh') else [list(x) for x in ob['pd_meshes']]
            sources[name] = [[int(r), int(i)] for r, i in src]
    return dict(vis_cols=vis_cols, obj_cols=obj_cols, textures=textures, replace=replace, vstats=vstats, placed=placed,
                sources=sources, placement_type=placement_type,
                types=types, ostats=ostats, casters=casters, vis_textures=vis_textures, fx_models=fx_models,
                fx_keys=fx_keys, fx_names=fx_names, report=report, sky=bool(scene.pd_sky_custom),
                compress=compress_textures, background_and_sky=background_and_sky, shadows=shadows)


def _new_texture_refs(x, out):
    """Indices of the new textures a model refers to (refs are ('new', i) tuples anywhere in its dicts)."""
    if isinstance(x, tuple) and len(x) == 2 and x[0] == 'new' and isinstance(x[1], int):
        out.add(x[1])
    elif isinstance(x, dict):
        for v in x.values():
            _new_texture_refs(v, out)
    elif isinstance(x, (list, tuple)):
        for v in x:
            _new_texture_refs(v, out)
    return out


def _image_digest(img):
    import numpy as np
    from . import roundtrip
    px = np.empty(len(img.pixels), dtype=np.float32)
    img.pixels.foreach_get(px)
    return roundtrip.digest(img.name, tuple(img.size), px.tobytes())


def model_digests(inp, texture_budget_mb=24, lightmap_budget_mb=16):
    """Digests of model_inputs: 'visual_0' / 'visual_1' / 'visual_2' (stage with its shadow casters, background,
    sky: each model with the new textures it uses and the texture options) and 'objects' (object types with
    their models and placements; effect models of other maps)."""
    from . import roundtrip
    textures = inp['textures']
    lightmaps = {id(t): (img, amb, glow) for t, img, amb, glow in textures.lightmaps}
    out = {}
    for slot in (0, 1, 2):
        model = inp['replace'].get(slot)
        used = []
        for i in sorted(_new_texture_refs(model, set())):
            t = inp['vis_textures'][i] if i < len(inp['vis_textures']) else None
            lm = lightmaps.get(id(textures.new[i])) if i < len(textures.new) else None
            used.append((t, None if lm is None else (_image_digest(lm[0]), lm[1], lm[2] and _image_digest(lm[2]))))
        out['visual_%d' % slot] = roundtrip.digest(
            model, used, inp['casters'] if slot == 0 else None, inp['sky'] if slot == 2 else None, inp['compress'],
            inp['background_and_sky'], inp['shadows'], texture_budget_mb, lightmap_budget_mb)
    out['objects'] = roundtrip.digest(inp['types'], inp['fx_keys'], inp['compress'])
    out['fx_keys'] = roundtrip.digest(inp['fx_keys'])           # effect models of other maps (the town's)
    # per object of the stage and background, and per shadow caster: an edited stage keeps every game mesh whose
    # object was not edited exactly as the game has it (its shader, vertex format and bytes)
    per = {}
    for slot in (0, 1):
        for m in _model_meshes(inp['replace'].get(slot)):
            per.setdefault((slot, m.get('object')), []).append(m)
    vis_obj = {}
    for (slot, name), ms in per.items():
        if name in inp['sources']:
            used = [inp['vis_textures'][i] if i < len(inp['vis_textures']) else None
                    for i in sorted(_new_texture_refs(ms, set()))]
            vis_obj[name] = roundtrip.digest(slot, ms, used, inp['sources'][name], inp['compress'])
    out['visual_objects'] = vis_obj
    out['caster_objects'] = {c['name']: roundtrip.digest(c, inp['sources'][c['name']])
                             for c in inp['casters'] if c['name'] in inp['sources']}
    # the objects without where they stand, and which of the file's placements the scene holds: when only
    # placements moved, they are written into their own entries and everything else stays
    out['objects_shape'] = roundtrip.digest([{k: v for k, v in t.items() if k != 'placements'} for t in inp['types']],
                                            inp['fx_keys'], inp['compress'])
    out['placement_ids'] = roundtrip.digest(sorted(off for off, _p in inp['placed'])) \
        if inp['placed'] is not None else None
    # each object type on its own: an edited type is added as a new one, the others keep the game's definitions
    out['object_types'] = {t['name']: roundtrip.digest({k: v for k, v in t.items() if k != 'placements'},
                                                       inp['compress'])
                           for t in inp['types']}
    return out


def scene_digests(context, scale, dat_path, alr_path, game_data):
    """Digest of every exported part as the export would read it now, with the export's default options
    (see roundtrip.py)."""
    from . import roundtrip
    scene = context.scene
    out = {}
    sp = collections_with_role(scene, 'SPAWNS')
    out['spawns'] = roundtrip.digest(gather_spawns(sp[0], scale)) if len(sp) == 1 else None
    out['collision'] = roundtrip.digest(gather_collision(context, scale)) if collision_collections(scene) else None
    eff_cols = collections_with_role(scene, 'EFFECTS')
    if eff_cols:
        from . import effects_export
        out['effects'] = roundtrip.digest(effects_export.gather(context, eff_cols, scale, game_data, {})[0])
    else:
        out['effects'] = None
    if alr_path and os.path.isfile(alr_path):
        base = open(alr_path, 'rb').read()
        out.update(model_digests(model_inputs(context, base, game_data, scale)))
        out['visual_shapes'] = visual_shapes(scene)
        out['object_shapes'] = object_shapes(scene)
    return out


def _model_meshes(model):
    """The mesh dicts of a gathered model: a list, or dict(meshes, nodes) when it has joints (visuals_export.gather);
    [] for anything else (a kept model, None)."""
    if isinstance(model, dict):
        return model.get('meshes') or []
    return model if isinstance(model, list) else []


def _visual_objects(scene):
    """Mesh objects of the stage and background imported from a game mesh (pd_mesh), by name."""
    from .visuals_export import _slot_for
    found = {}

    def walk(c, slot):
        slot = _slot_for(c.name, slot)
        if slot in (0, 1):
            for ob in c.objects:
                if ob.type == 'MESH' and 'pd_mesh' in ob:
                    found[ob.name] = ob
        for ch in c.children:
            walk(ch, slot)
    for c in collections_with_role(scene, 'VISUALS'):
        walk(c, 0)
    return found


def _shape(me):
    """What the export reads from a mesh except where its vertices are: vertex count, faces, UVs, colours,
    materials (the values a shape digest is made of)."""
    import numpy as np
    loops = np.empty(len(me.loops), dtype=np.int32)
    me.loops.foreach_get('vertex_index', loops)
    starts = np.empty(len(me.polygons), dtype=np.int32)
    me.polygons.foreach_get('loop_start', starts)
    uv = np.zeros(len(me.loops) * 2, dtype=np.float32)
    if me.uv_layers.active is not None:
        me.uv_layers.active.data.foreach_get('uv', uv)
    cols = []
    for a in me.color_attributes:
        c = np.empty(len(a.data) * 4, dtype=np.float32)
        a.data.foreach_get('color', c)
        cols.append((a.name, a.domain, c.tobytes()))
    mats = np.empty(len(me.polygons), dtype=np.int32)
    me.polygons.foreach_get('material_index', mats)
    return [len(me.vertices), loops.tobytes(), starts.tobytes(), uv.tobytes(), cols, mats.tobytes(),
            [m.name if m else None for m in me.materials]]


def visual_shapes(scene):
    """Per imported stage / background object: a digest of everything the export reads from it except where its
    vertices are (_shape, the turn and scale of the object, its source mesh). An object whose shape digest is
    unchanged had only its vertices moved: _patch_moved_meshes writes them in place."""
    from . import roundtrip
    out = {}
    for name, ob in _visual_objects(scene).items():
        m3 = [round(x, 6) for r in ob.matrix_world.to_3x3() for x in r]
        out[name] = roundtrip.digest(*_shape(ob.data), m3, list(ob['pd_mesh']),
                                     ob.modifiers[:] and [md.type for md in ob.modifiers])
    return out


def object_shapes(scene):
    """Per mesh of the imported placed objects (an object type's model, shared by its placements): a digest of
    _shape. _patch_moved_models writes a model whose shape is unchanged into the game's own meshes."""
    from . import roundtrip
    out = {}
    for oc in collections_with_role(scene, 'OBJECTS'):
        for ob in oc.all_objects:
            if ob.type == 'MESH' and 'pd_placement' in ob and ob.data.name not in out:
                out[ob.data.name] = roundtrip.digest(*_shape(ob.data))
    return out


def _import_vertices(tris):
    """The game vertex of each Blender vertex of a mesh made from `tris` as the import makes it
    (visuals.import_visuals): the used vertices in order, then a copy for each corner of a repeated face."""
    used = sorted({i for tr in tris for i in tr})
    remap = {o: k for k, o in enumerate(used)}
    seen = set()
    for tr in tris:
        f = cv.flip_winding(tuple(remap[i] for i in tr))
        if frozenset(f) in seen:
            f2 = []
            for k in f:
                used.append(used[k])
                f2.append(len(used) - 1)
            f = tuple(f2)
        seen.add(frozenset(f))
    return used


def _node_inverse(m):
    """(node matrix, inverse of its 3 x 3 part) of a mesh record, or None when it has no inverse."""
    import numpy as np
    from ._lib import alr
    mtx = alr.node_matrix(m['nodes'], m['node']) if m['node'] < len(m['nodes']) else alr._identity()
    try:
        return mtx, np.linalg.inv(np.array([r[:3] for r in mtx[:3]], dtype=np.float64))
    except np.linalg.LinAlgError:
        return None


def _write_moved(b, rb, h, writes, touched):
    """Write moved vertices {(buffer offset, vertex): position} into the file and each touched mesh record's centre,
    radius and box (node space) from them; touched: [(mesh, buffer, used vertices, rigid offset or None)]. False
    (nothing written) when another mesh shares a moved vertex (the game's meshes share big vertex buffers)."""
    from ._lib import alr
    mine = {m['offset'] for m, _vb, _u, _r in touched}
    for ri in range(len(h['roots'])):
        for m in alr.meshes(b, h['roots'][ri]):
            if m['vbuf'] >= len(m['vbufs']) or m['offset'] in mine:
                continue
            off = m['vbufs'][m['vbuf']]['offset']
            if any((off, i) in writes for i in set(m['indices'])):
                return False
    for (off, g), new in writes.items():
        vb = next(v for _m, v, _u, _r in touched if v['offset'] == off)
        struct.pack_into('<3f', b, rb + off + g * vb['vertex_size'], *new)
    for m, vb, used, rigid in touched:
        o = m['offset']
        if rigid is not None:
            c = struct.unpack_from('<3f', b, o + 0x08)
            lo, hi = struct.unpack_from('<3f', b, o + 0x18), struct.unpack_from('<3f', b, o + 0x24)
            struct.pack_into('<3f', b, o + 0x08, *(c[a] + rigid[a] for a in range(3)))
            struct.pack_into('<3f', b, o + 0x18, *(lo[a] + rigid[a] for a in range(3)))
            struct.pack_into('<3f', b, o + 0x24, *(hi[a] + rigid[a] for a in range(3)))
            continue
        ps = alr.read_vertices(b, rb, vb)[0]
        pts = [ps[g] for g in used]
        lo = [min(p[a] for p in pts) for a in range(3)]
        hi = [max(p[a] for p in pts) for a in range(3)]
        c = [(lo[a] + hi[a]) / 2 for a in range(3)]
        r = max(sum((p[a] - c[a]) ** 2 for a in range(3)) ** 0.5 for p in pts)
        struct.pack_into('<3f', b, o + 0x08, *c)
        struct.pack_into('<f', b, o + 0x14, r)
        struct.pack_into('<3f', b, o + 0x18, *lo)
        struct.pack_into('<3f', b, o + 0x24, *hi)
    return True


def _patch_moved_models(context, base, scale, was, alr_path, changed, placement_type):
    """Edited object types whose model only had vertices moved (object_shapes unchanged) are written into the
    game's own model meshes (the type's intact root), as _patch_moved_meshes does for the stage: moved vertices as
    the file's value plus their move since the import, the mesh records' centre, radius and box following. The
    object definitions and placements stay. Returns the new bytes, or None (the types are then added as new
    types)."""
    import numpy as np
    from ._lib import alr
    from ._lib import objects_build
    shapes_was = was.get('object_shapes') or {}
    dat_path = os.path.splitext(alr_path)[0] + '.dat'
    if not shapes_was or not os.path.isfile(dat_path):
        return None
    shapes_now = object_shapes(context.scene)
    _names, table, places = objects_build.read_objects(open(dat_path, 'rb').read())
    oid_at = {p['offset']: p['object'] for p in places}
    by_off = {int(o['pd_placement']): o for oc in collections_with_role(context.scene, 'OBJECTS')
              for o in oc.all_objects if o.type == 'MESH' and 'pd_placement' in o}
    b = bytearray(base)
    h = alr.header(b)
    rb = h['resource_offset']
    s_imp = _import_scale(scale)
    writes, touched = {}, []
    for name in changed:
        offs = [off for off, n in placement_type.items() if n == name and off in by_off]
        if not offs:
            return None
        mes = {by_off[off].data.name for off in offs}
        oids = {oid_at.get(off) for off in offs}
        if len(mes) != 1 or len(oids) != 1 or None in oids:
            return None
        me = by_off[offs[0]].data
        if shapes_now.get(me.name) is None or shapes_now.get(me.name) != shapes_was.get(me.name):
            return None
        entry = table[oids.pop()]
        if entry[0] is None or entry[0] == dat.NONE or entry[0] >= len(h['roots']):
            return None
        records = alr.meshes(b, h['roots'][entry[0]])
        owner = []                                # Blender vertex -> (record, game vertex), as visuals.build_mesh
        for m in records:
            ent = m['materials'][m['material']] if m['material'] < len(m['materials']) else None
            if (ent['shader'] if ent else '').startswith('sshadow') or m['vbuf'] >= len(m['vbufs']):
                continue
            tris = alr.triangles_from_indices(m['indices'], m['primitive'])
            if tris:
                owner += [(m, g) for g in _import_vertices(tris)]
        if len(owner) != len(me.vertices):
            return None
        co = np.empty(len(me.vertices) * 3, dtype=np.float32)
        me.vertices.foreach_get('co', co)
        co = co.reshape(-1, 3)
        cache, moved_by = {}, {}
        for k, (m, g) in enumerate(owner):
            if id(m) not in cache:
                ni = _node_inverse(m)
                if ni is None:
                    return None
                cache[id(m)] = ni + (alr.read_vertices(b, rb, m['vbufs'][m['vbuf']])[0],)
            mtx, inv, pos = cache[id(m)]
            then = np.array(cv.to_blender(alr.apply(mtx, pos[g]), s_imp), dtype=np.float32)
            own = co[k].astype(np.float64) - then.astype(np.float64)
            own[np.abs(own) <= 4 * np.spacing(np.abs(then)).astype(np.float64)] = 0.0
            if not own.any():
                continue
            dl = inv @ (np.array([own[0], own[2], own[1]]) / scale)       # Blender -> game axes, node space
            new = tuple(float(pos[g][a] + dl[a]) for a in range(3))
            vb = m['vbufs'][m['vbuf']]
            key = (vb['offset'], g)
            if key in writes and max(abs(x - y) for x, y in zip(writes[key], new)) > 1e-4:
                return None                       # two copies of one game vertex moved apart
            writes[key] = new
            moved_by.setdefault(id(m), (m, vb))
        for m, vb in moved_by.values():
            tris = alr.triangles_from_indices(m['indices'], m['primitive'])
            touched.append((m, vb, sorted({i for tr in tris for i in tr}), None))
    if not writes or not _write_moved(b, rb, h, writes, touched):
        return None
    return bytes(b)


def _patch_moved_meshes(context, base, scale, was, dg, slots):
    """Edited stage / background objects whose vertices only moved (same faces, UVs, colours, materials, turn and
    scale as imported: visual_shapes) are written into the game's own mesh: each moved vertex gets the file's value
    plus how far it moved since the import (so moving it back gives the file's value again), the mesh record's
    centre, radius and box follow. Everything else in the file keeps its bytes, the shader and material included.

    slots: the model slots (0 stage, 1 background) whose digest changed. Returns (new bytes, slots now written)
    or None when an edit there is more than moved vertices (new / deleted / reshaped objects, a vertex another
    mesh shares, shadow casters edited, ...): the slot is rebuilt then."""
    import numpy as np
    from ._lib import alr
    scene = context.scene
    was_vis, now_vis = was.get('visual_objects') or {}, dg.get('visual_objects') or {}
    shapes_was = was.get('visual_shapes') or {}
    if not shapes_was or set(was_vis) != set(now_vis) or (was.get('caster_objects') or {}) != dg.get('caster_objects'):
        return None
    obs = _visual_objects(scene)
    changed = [n for n in now_vis if now_vis[n] != was_vis.get(n)]
    if not changed or any(n not in obs for n in changed):
        return None
    shapes_now = visual_shapes(scene)
    if any(shapes_now.get(n) != shapes_was.get(n) for n in changed):
        return None
    b = bytearray(base)
    h = alr.header(b)
    rb = h['resource_offset']
    per_root = {}

    def meshes_of(ri):
        if ri not in per_root:
            per_root[ri] = alr.meshes(b, h['roots'][ri]) if ri < len(h['roots']) else []
        return per_root[ri]
    writes = {}                                  # (buffer offset, vertex) -> new local position
    touched = []                                 # (mesh, [vertex indices], rigid offset or None)
    for n in changed:
        ob = obs[n]
        ri, mi = (int(x) for x in ob['pd_mesh'])
        if ri not in slots:
            return None
        ms = meshes_of(ri)
        if mi >= len(ms) or ms[mi]['vbuf'] >= len(ms[mi]['vbufs']):
            return None
        m = ms[mi]
        vb = m['vbufs'][m['vbuf']]
        used = _import_vertices(alr.triangles_from_indices(m['indices'], m['primitive']))
        me = ob.data
        if len(me.vertices) != len(used):
            return None
        mw = np.array([list(r) for r in ob.matrix_world], dtype=np.float64)
        if np.abs(mw[:3, :3] - np.eye(3)).max() > 1e-6:
            return None                          # turned or scaled: the normals would change too
        ni = _node_inverse(m)
        if ni is None:
            return None
        mtx, inv = ni
        pos = alr.read_vertices(b, rb, vb)[0]
        co = np.empty(len(me.vertices) * 3, dtype=np.float32)
        me.vertices.foreach_get('co', co)
        then32 = np.array([cv.to_blender(alr.apply(mtx, pos[g]), _import_scale(scale)) for g in used],
                          dtype=np.float32)
        then = then32.astype(np.float64)          # where the import put each vertex
        own = co.astype(np.float64).reshape(-1, 3) - then
        # a vertex Blender keeps a step or two of float32 away from that is not an edit: the move is then exactly
        # the object's own (so moving the object back gives the file's values back)
        own[np.abs(own) <= 4 * np.spacing(np.abs(then32)).astype(np.float64)] = 0.0
        d = own + mw[:3, 3]
        dg_ = np.stack([d[:, 0], d[:, 2], d[:, 1]], axis=1) / scale     # Blender -> game axes (convert.to_game)
        dl = dg_ @ inv.T
        moved = []
        for k, g in enumerate(used):
            if not dl[k].any():
                continue
            new = tuple(float(pos[g][a] + dl[k][a]) for a in range(3))
            key = (vb['offset'], g)
            if key in writes and max(abs(x - y) for x, y in zip(writes[key], new)) > 1e-4:
                return None                      # two copies of one game vertex moved apart
            writes[key] = new
            moved.append(g)
        if moved:
            rigid = dl[0] if np.abs(dl - dl[0]).max() < 1e-6 and len({*used}) == len({*moved}) else None
            touched.append((m, vb, sorted({*used}), rigid))
    if writes and not _write_moved(b, rb, h, writes, touched):
        return None
    return bytes(b), set(slots)


KEPT_OBJECTS = False     # True after export_models kept the game original's objects (export_scene then keeps them too)
MOVED_PLACEMENTS = None  # [(offset in the .dat, placement)] when only placements of kept objects moved
ADDED_TYPES = None       # edited object types added to the kept ones: dict(objects, types, of_placement)
PLACEMENT_EDIT = None    # objects added / deleted, types as imported: dict(kept=[offsets], new=[(placement, template)])


def _carry_unedited(base, replace, casters, sources, was_vis, was_cast, dg):
    """In the stage and background models being rebuilt, put back every game mesh whose Blender object was not
    edited since the import (same digest): the game's own mesh record (shader, material, vertex format and
    bytes; node transform applied, as the rebuilt model has one node). The same for shadow casters (their game
    shadow meshes). Returns (replace, casters still to build, number of meshes carried)."""
    from ._lib import alr, alr_build
    h = alr.header(base)
    game = {}

    def game_mesh(root, index):
        if root not in game:
            game[root] = alr.meshes(base, h['roots'][root]) if root < len(h['roots']) else []
        ms = game[root]
        if index >= len(ms):
            return None
        m = alr_build.raw_mesh(base, ms[index], h['resource_offset'])
        # the game's meshes share big vertex buffers: keep only this mesh's own vertices
        r, size = m['raw'], m['raw']['vertex_size']
        used = sorted({i for t in r['tris'] for i in t})
        if not used:
            return None
        remap = {old: new for new, old in enumerate(used)}
        r['vertex_bytes'] = b''.join(r['vertex_bytes'][i * size:(i + 1) * size] for i in used)
        r['tris'] = [tuple(remap[i] for i in t) for t in r['tris']]
        return m

    n = 0
    out = dict(replace)
    for slot in (0, 1):
        model = replace.get(slot)
        if not isinstance(model, list):
            continue
        new, done = [], set()
        for m in model:
            name = m.get('object')
            src = sources.get(name)
            if src and name in was_vis and was_vis[name] == dg['visual_objects'].get(name) \
                    and all(r == slot for r, _i in src):
                if name not in done:
                    done.add(name)
                    raws = [game_mesh(r, i) for r, i in src]
                    if all(raws):
                        new += raws
                        n += len(raws)
                        continue
                    done.discard(name)
                else:
                    continue
            new.append(m)
        out[slot] = new
    keep_casters = []
    for c in casters:
        src = sources.get(c['name'])
        if src and c['name'] in was_cast and was_cast[c['name']] == dg['caster_objects'].get(c['name']):
            raws = [game_mesh(r, i) for r, i in src]
            if all(raws) and 0 in out and isinstance(out[0], list):
                out[0] = out[0] + raws
                n += len(raws)
                continue
        keep_casters.append(c)
    return out, keep_casters, n


def export_models(context, game_original_alr, out_alr_path, scale, background_and_sky=False, shadows=True,
                  compress_textures=False, texture_budget_mb=12, lightmap_budget_mb=16):
    """Write the .alr from Visuals and Objects collections.

    Parts of an imported game original that were not edited are kept as the game has them (roundtrip.py):
    nothing edited = the game's own file, byte for byte; untouched objects keep their models and .dat tables
    (moved placements are written into their own entries); an untouched stage, background or sky keeps its model;
    in an edited one every game mesh whose Blender object was not edited is kept as the game has it.

    Returns (report string, objects, placements) for the .dat, or (None, None, None) when the scene has
    neither Visuals nor Objects (the base model file is then not needed)."""
    from . import roundtrip
    from . import visuals_export as vx
    global CARRIED_MODELS, KEPT_OBJECTS, MOVED_PLACEMENTS, ADDED_TYPES, PLACEMENT_EDIT
    CARRIED_MODELS = {}
    KEPT_OBJECTS = False
    MOVED_PLACEMENTS = None
    ADDED_TYPES = None
    PLACEMENT_EDIT = None
    scene = context.scene
    if not collections_with_role(scene, 'VISUALS') and not collections_with_role(scene, 'OBJECTS') \
            and not scene.pd_sky_custom:
        return None, None, None
    if not os.path.isfile(game_original_alr):
        raise ExportError('game original model not found: %s (%s)' % (game_original_alr, missing_hint(
            os.path.dirname(os.path.dirname(game_original_alr)))))
    base = open(game_original_alr, 'rb').read()
    game_data = os.path.dirname(os.path.dirname(game_original_alr))
    if os.path.basename(game_data).lower() == 'map':          # the backup copy: Map/pd_addon_backup/stNN.alr
        game_data = os.path.dirname(game_data)
    stage = os.path.splitext(os.path.basename(game_original_alr))[0].lower()
    src = roundtrip.source(scene, stage, 'alr', game_original_alr)
    if src:                       # imported from an earlier export of this slot: build on that file (roundtrip.py)
        game_original_alr = src
        base = open(src, 'rb').read()
    from . import effects_export
    effects_export.EXPORT_SLOT = stage
    inp = model_inputs(context, base, game_data, scale, background_and_sky, shadows, compress_textures)
    textures, replace, types = inp['textures'], inp['replace'], inp['types']
    vstats, ostats, casters = inp['vstats'], inp['ostats'], inp['casters']
    fx_models, fx_keys, fx_names = inp['fx_models'], inp['fx_keys'], inp['fx_names']
    report = list(inp['report'])
    dg = model_digests(inp, texture_budget_mb, lightmap_budget_mb)
    same_slots = {k for k in (0, 1, 2)
                  if roundtrip.unchanged(scene, stage, 'visual_%d' % k, dg['visual_%d' % k], alr_path=game_original_alr)}
    patched_slots = set()
    models_patched = 0
    if len(same_slots) < 3 and 2 in same_slots:
        was = roundtrip.recorded(scene, stage, alr_path=game_original_alr)
        if was:                                  # only vertices of game meshes moved: written into the meshes
            p = _patch_moved_meshes(context, base, scale, was, dg, {0, 1} - same_slots)
            if p is not None:
                base, patched_slots = p
                same_slots |= patched_slots
    vis_same = len(same_slots) == 3
    obj_same = roundtrip.unchanged(scene, stage, 'objects', dg['objects'], alr_path=game_original_alr)
    if not obj_same and inp['placed'] is not None \
            and roundtrip.unchanged(scene, stage, 'objects_shape', dg['objects_shape'], alr_path=game_original_alr) \
            and roundtrip.unchanged(scene, stage, 'placement_ids', dg['placement_ids'], alr_path=game_original_alr):
        MOVED_PLACEMENTS = inp['placed']                     # only placements moved: written in place
        obj_same = True
    changed_types = None
    if not obj_same and inp['placed'] is not None and not fx_keys \
            and roundtrip.unchanged(scene, stage, 'placement_ids', dg['placement_ids'], alr_path=game_original_alr):
        was_types = roundtrip.recorded(scene, stage, alr_path=game_original_alr).get('object_types') or {}
        if was_types and set(was_types) == set(dg['object_types']) \
                and set(inp['placement_type'].values()) <= set(dg['object_types']):
            # the same types and placements as imported: only the edited types are added (as new types), the
            # others keep the game's definitions, models and second-layout placements
            changed_types = [t for t in types if was_types[t['name']] != dg['object_types'][t['name']]]
            if changed_types:                                # only vertices of their models moved: in place
                p = _patch_moved_models(context, base, scale, roundtrip.recorded(
                    scene, stage, alr_path=game_original_alr), game_original_alr,
                    [t['name'] for t in changed_types], inp['placement_type'])
                if p is not None:
                    base, models_patched = p, len(changed_types)
                    changed_types = []
            if not changed_types:                            # no type edited: only placements to write
                changed_types = None
                MOVED_PLACEMENTS = inp['placed']
                obj_same = True
    if not obj_same and inp['obj_cols'] and (not fx_keys or roundtrip.unchanged(
            scene, stage, 'fx_keys', dg['fx_keys'], alr_path=game_original_alr)):
        # (effect models of other maps, the town's: when they are as imported they are in the file already)
        # objects added (copies of imported ones) or deleted, every object type as imported: the placement list
        # is written again with the same entries (export_scene, _write_placement_table); the game's definitions,
        # models and second object layout stay
        from . import objects_export as ox
        was_types = roundtrip.recorded(scene, stage, alr_path=game_original_alr).get('object_types') or {}
        kept, new = ox.placed_split(inp['obj_cols'], scale)
        kinds = {name: off for off, _p, name in kept}
        if was_types and kept and all(was_types.get(n) == d for n, d in dg['object_types'].items()) \
                and all(name in kinds or tmpl is not None for name, _p, tmpl in new):
            MOVED_PLACEMENTS = [(off, p) for off, p, _n in kept]
            PLACEMENT_EDIT = dict(kept=[off for off, _p, _n in kept],
                                  new=[(p, tmpl if tmpl is not None else kinds[name]) for name, p, tmpl in new])
            obj_same = True
    if vis_same and obj_same:
        with open(out_alr_path, 'wb') as f:                   # nothing in the model file was edited
            f.write(base)
        KEPT_OBJECTS = True
        if patched_slots or models_patched:
            what = [('stage', 'background')[k] for k in sorted(patched_slots)]
            what += ['%d object model%s' % (models_patched, 's' if models_patched > 1 else '')] if models_patched else []
            return ('moved vertices written into the game\'s own meshes (%s), the rest of %s as it is'
                    % (', '.join(what), os.path.basename(game_original_alr))), None, None
        return 'model file unchanged: the game original %s as it is' % os.path.basename(game_original_alr), None, None
    if same_slots:                                           # models not edited stay as the game has them
        replace = {k: v for k, v in replace.items() if k not in same_slots}
        if 0 in same_slots:
            casters = []
        kept = ', '.join(('stage', 'background', 'sky')[k] for k in sorted(same_slots))
        report = [r for r in report if not (2 in same_slots and r.startswith('custom sky'))]
        report.append('%s not edited: kept as the game original has %s' % (kept, 'it' if len(same_slots) == 1 else 'them'))
    carried_meshes = 0
    if 0 in replace or 1 in replace:
        was = roundtrip.recorded(scene, stage, alr_path=game_original_alr)
        replace, casters, carried_meshes = _carry_unedited(base, replace, casters, inp['sources'],
                                                           was.get('visual_objects') or {},
                                                           was.get('caster_objects') or {}, dg)
    if obj_same:                                             # stage edited: the game's own objects stay
        types, fx_models, fx_keys = [], [], []
        KEPT_OBJECTS = True
        report.append('objects not edited: kept as the game original has them')
    elif changed_types is not None:
        types = changed_types
        KEPT_OBJECTS = True
        MOVED_PLACEMENTS = inp['placed']
        report.append('objects: %d of %d types edited (added as new types), the others kept as the game original '
                      'has them' % (len(changed_types), len(inp['types'])))
    if inp['vis_cols'] and not inp['replace']:
        raise ExportError('the Visuals collection has no mesh triangles for the stage')
    obj_cols = inp['obj_cols'] if not obj_same else []
    leftovers = [t['name'] for t in vx.alr.textures(base) if t['name'].startswith(('pd_', 'pdlm'))]
    if leftovers:
        # the "game original" is an earlier export (copied into the game by hand before the add-on made its
        # backup): its added textures and models are carried along unused and take memory in game
        report.append('WARNING: the game original %s already holds an earlier export (%d of its textures, e.g. %s): '
                      'its unused parts are left out, but put the game\'s own %s back (verify the game files)'
                      % (os.path.basename(game_original_alr), len(leftovers), leftovers[0],
                         os.path.basename(game_original_alr)))
    add_models = [m for t in types for m in t['models'] if m is not None]
    if not roundtrip.ENABLED:
        # built from the scene: the texture table's other images (effect textures, sprite sheets: pd_texture_number)
        import bpy
        for img in bpy.data.images:
            if 'pd_texture_number' in img and img.size[0] > 0 and img.users:
                textures.ref(img)
        from . import stage_extras                      # the sprite types' textures (SP00 names them)
        for img in stage_extras.sprite_images(scene):
            textures.ref(img)
    shrunk = textures.finish_lightmaps(int(lightmap_budget_mb * 1024 * 1024))
    if textures.lightmaps:
        report.append('%d light maps, %.1f MB%s' % (len(textures.lightmaps), textures.lightmap_bytes / 1048576.0,
                                                   ' (%d made smaller to fit %d MB)' % (shrunk, lightmap_budget_mb)
                                                   if shrunk else ''))
    lm_ids = {id(t) for t, _i, _a, _g in textures.lightmaps}
    squeezed, halved = textures.finish(int(texture_budget_mb * 1024 * 1024), skip=lm_ids)
    if squeezed:
        report.append('%d biggest textures compressed to fit %d MB' % (squeezed, texture_budget_mb))
    if halved:
        report.append('textures made smaller %d times to fit %d MB' % (halved, texture_budget_mb))
    stripped = {}
    shadow_source = casters or None
    # every shadow caster carried over as the game has it: no shadow mesh is made
    shadows_kept = bool(inp['casters']) and not casters
    if carried_meshes:
        report.append('%d game meshes not edited: kept as the game original has them' % carried_meshes)
    if casters:
        report.append('shadow casters: %d meshes, %d triangles' % (len(casters), sum(len(m['tris']) for m in casters)))
        flat = [m['name'] for m in casters if not m['stretched']]
        if flat:
            report.append('WARNING: shadow casters not stretched yet (press Stretch/Fix Shadow Casters): %s'
                          % ', '.join(flat))

    # Built from the scene: when every object type is written new, the game's own object models (the roots its
    # object definitions use, not the stage's three, not those of its model list MD00) are emptied so the file
    # holds each model once; their vertex data then goes with strip_unused. Root numbers stay as they are.
    clear = ()
    if not roundtrip.ENABLED and obj_cols and types:
        base_dat = os.path.splitext(game_original_alr)[0] + '.dat'
        if os.path.isfile(base_dat):
            bd = open(base_dat, 'rb').read()
            if dat.layout_kind(bd) == 'stage':
                from ._lib import objects_build
                _names, table, _places = objects_build.read_objects(bd)
                md = dat.md00(bd)
                keep = {0, 1, 2} | ({r for r, _a in md[2] if r >= 0} if md else set())
                clear = tuple(sorted({r for e in table for r in e[:3] if r != dat.NONE and r not in keep
                                      and r < len(vx.alr.header(base)['roots'])}))
        if clear:
            report.append('%d game object models replaced by the scene\'s' % len(clear))

    def build():
        # then drop what nothing uses (the replaced models' old vertex data, an earlier export's leftover
        # textures), so it doesn't count toward the game's 20 MiB
        data, built = vx.alr_build.rebuild(base, replace=replace, textures=textures.new, clear=clear,
                                           replace_textures=textures.replaced,
                                           add_models=add_models + fx_models,
                                           shadows_for=(0,) if shadows and 0 in replace and not shadows_kept else (),
                                           shadow_source=shadow_source)
        data, st = vx.alr_build.strip_unused(data)
        stripped.update(st)
        return data, built

    data, built = build()
    # The game loads a model file's data (vertices + textures) into 20 MiB: anything past it shows as rainbow
    # textures or exploding geometry (tested: 15.5 MiB fine; 21.1, 21.3, 25.2, 29.0 MiB broken). Shrink the
    # biggest new textures (light maps included) until it fits.
    size = lambda t: sum(len(l) for l in t['levels'])
    fitted = 0
    while vx.alr.header(data)['resource_size'] > RESOURCE_LIMIT:
        excess = vx.alr.header(data)['resource_size'] - RESOURCE_LIMIT
        saved = 0
        while saved < excess:
            cands = [t for t in textures.new if len(t['levels']) > 1 and min(t['width'], t['height']) > 16]
            if not cands:
                break
            t = max(cands, key=size)
            before = size(t)
            t['levels'] = t['levels'][1:]
            t['width'], t['height'] = max(1, t['width'] // 2), max(1, t['height'] // 2)
            if 'mips' in t:
                t['mips'] = len(t['levels'])
            saved += before - size(t)
            fitted += 1
        if not saved:
            raise ExportError('the map\'s model data is %.1f MiB even with the smallest textures; the game only '
                              'loads %.0f MiB (more shows as broken geometry and textures): use fewer triangles%s'
                              % (vx.alr.header(data)['resource_size'] / 1048576.0, RESOURCE_LIMIT / 1048576.0,
                                 ', and put the game\'s own %s back (it holds an earlier export)'
                                 % os.path.basename(game_original_alr) if leftovers else ''))
        data, built = build()
    if fitted:
        report.append('textures made smaller %d times so the model data fits the game\'s %d MiB'
                      % (fitted, RESOURCE_LIMIT // 1048576))
    if stripped.get('saved', 0) > 65536:
        report.append('%.1f MiB of unused data left out%s' % (stripped['saved'] / 1048576.0,
                      ' (%d unused textures)' % stripped['textures'] if stripped['textures'] else ''))
    report.append('model data %.1f of %d MiB' % (vx.alr.header(data)['resource_size'] / 1048576.0,
                                                 RESOURCE_LIMIT // 1048576))
    if not roundtrip.ENABLED:
        # textures of the game file still in the written file as the game has them: not written from a Blender
        # image (replaced) and not dropped (strip_unused points dropped ones at one 4 x 4 texture)
        out_t = vx.alr.textures(data)
        dummy = [t['offset'] for t in out_t if t['width'] == 4 and t['height'] == 4 and t['format'] == 0x0C]
        kept = [t['name'] for t in out_t[:len(vx.alr.textures(base))]
                if t['index'] not in textures.replaced and not (dummy and t['offset'] == max(dummy))]
        report.append('%d game-file textures kept as they are%s' % (len(kept), (': ' + ', '.join(kept)) if kept else ''))
    with open(out_alr_path, 'wb') as f:
        f.write(data)
    def tris_of(m):                                          # a written mesh, or one carried over as is (raw)
        return m['raw']['tris'] if 'raw' in m else m['tris']

    if replace:
        written = sum(len(tris_of(m)) for model in replace.values() for m in _model_meshes(model))
        report.append('model: %d triangles' % written + (', character shadows on' if shadows and 0 in replace else ''))
        stage_tris = sum(len(tris_of(m)) for m in _model_meshes(replace[0])) if 0 in replace else 0
        if stage_tris > 500000:                              # tested in game: 1M flickers and loses shadows
            print('Phantom Dust export warning: the stage has %d triangles; above 500,000 the game may flicker '
                  '(colours and shapes) and lose its shadows' % stage_tris)
            report.append('WARNING: %dk stage triangles, above 500k the game may flicker and lose shadows'
                          % (stage_tris // 1000))
    kinds = {}
    for model in list(replace.values()) + list(add_models):
        for m in _model_meshes(model):
            if 'material' in m:
                k = vx.alr_build.shader_for(m['material'].get('normal') is not None,
                                            m['material'].get('reflection') is not None)
                kinds[k] = kinds.get(k, 0) + 1
    if kinds:
        report.append('shaders: ' + ', '.join('%d %s' % (n, k) for k, n in sorted(kinds.items())))
    report.append('%d new textures%s' % (len(textures.new), ' (%d copies of the same image shared)' % textures.shared
                                          if getattr(textures, 'shared', 0) else ''))
    roots = built['added_roots'][len(add_models):]
    CARRIED_MODELS = {key: (roots[k], fx_names[key]) for k, key in enumerate(fx_keys)}
    if fx_keys:
        report.append('%d effect models copied from %s' % (len(fx_keys), ', '.join(sorted({h for h, _s in fx_keys}))))
    objects = placements = None
    if changed_types is not None:
        from . import objects_export as ox
        objects, _placements = ox.add_to_files(types, add_models, built['added_roots'])
        index = {t['name']: k for k, t in enumerate(types)}
        ADDED_TYPES = dict(objects=objects, types=[(t['category'], t['type']) for t in types],
                           of_placement={off: index[name] for off, name in inp['placement_type'].items()
                                         if name in index})
        objects = placements = None
    elif obj_cols:
        from . import objects_export as ox
        objects, placements = ox.add_to_files(types, add_models, built['added_roots'])
        report.append('%d object types, %d placed' % (len(objects), len(placements)))
    clamped = vstats.get('clamped_uv', 0) + ostats.get('clamped_uv', 0)
    if clamped:
        report.append('%d UVs clamped: keep each triangle within 8 texture repeats' % clamped)
    return '; '.join(report), objects, placements


def export_scene(context, base_path, out_path, scale, remove_objects=False, objects=None, placements=None,
                 game_data=None):
    """Write the .dat. remove_objects = clean slate (no placed objects or effects from the game original).
    objects/placements (from export_models) become the stage's objects. Effects collections add effects
    (presets read from game_data). Parts of an imported game original that were not edited keep the file's own
    bytes (roundtrip.py); moved spawns, placements and effects are written into their own entries."""
    if not os.path.isfile(base_path):
        raise ExportError('game original file not found: %s (set the game data folder in the export options)' % base_path)
    if os.path.abspath(out_path) == os.path.abspath(base_path):
        raise ExportError('choose a different output file than the game original (back it up and copy over it afterwards)')
    from . import roundtrip
    scene = context.scene
    b = bytearray(open(base_path, 'rb').read())
    report = []
    stage = os.path.splitext(os.path.basename(base_path))[0].lower()
    game_data = game_data or os.path.dirname(os.path.dirname(base_path))
    src = roundtrip.source(scene, stage, 'dat', base_path)
    if src:                       # imported from an earlier export of this slot: build on that file (roundtrip.py)
        base_path = src
        b = bytearray(open(src, 'rb').read())
        report.append('built on %s (the file this scene was imported from)' % os.path.basename(src))

    # Built from the scene (the default): every section the scene holds is written new, and the game file's
    # section it replaces is removed afterwards (datfile.compact), so each section is in the file once
    from ._lib import datfile
    old_spans = None if roundtrip.ENABLED or dat.layout_kind(b) != 'stage' else datfile.spans(bytes(b))

    def same(part, value):
        """`part` not edited since it was imported from this very base file (roundtrip.py)"""
        return roundtrip.unchanged(scene, stage, part, roundtrip.digest(value), dat_path=base_path)

    sp = collections_with_role(scene, 'SPAWNS')
    eff_cols = collections_with_role(scene, 'EFFECTS')
    if dat.layout_kind(b) != 'stage':
        # st00 (a 0x28-byte header, never loaded by the game) and the town's area files have no collision,
        # spawns, objects or effects tables: writing them would overwrite other data
        if sp or collision_collections(scene) or objects or eff_cols:
            raise ExportError('%s is not a battle stage file (no collision, spawn, object or effect tables): only '
                              'its model file can be exported' % os.path.basename(base_path))
        from . import townlights
        stream = townlights.build_stream(scene, scale) if not roundtrip.ENABLED else None
        if stream is not None and townlights.stream_offset(bytes(b)) is not None:
            b = bytearray(townlights.put_stream(bytes(b), stream))
            with open(out_path, 'wb') as f:
                f.write(b)
            return 'town light list: %d lights from the scene\'s town lights; the rest of %s as it is' % (
                len(townlights.town_lights(scene)), os.path.basename(base_path))
        with open(out_path, 'wb') as f:
            f.write(b)
        return 'no stage tables in %s: kept as it is' % os.path.basename(base_path)
    if len(sp) > 1:
        raise ExportError('more than one Spawn Points collection: %s' % ', '.join(c.name for c in sp))
    if sp:
        base_layouts = dat.spawn_layouts(b)
        got = gather_spawns(sp[0], scale)
        if same('spawns', got):
            report.append('spawns not edited: kept as the game original has them')
            sp = None
    if sp:
        # The base map fixes how many layouts and spawns there are (single-player layouts can have only one).
        # A scene layout with fewer spawns is repeated to fill the slots, extra spawns or layouts are left out:
        # both only warn (System Console).
        warn = []
        if len(got) > len(base_layouts):
            warn.append('%d layouts in the scene, the game original has %d: %s left out'
                        % (len(got), len(base_layouts), ', '.join(n for n, _e in got[len(base_layouts):])))
        for i, layout in enumerate(base_layouts):
            name, entries = got[i % len(got)]
            if not entries:
                raise ExportError('%s has no spawns' % name)
            if len(entries) < len(layout):
                warn.append('%s has %d spawns for %d slots (game layout %d): its spawns are repeated'
                            % (name, len(entries), len(layout), i + 1))
            elif len(entries) > len(layout):
                warn.append('%s has %d spawns, game layout %d has %d slots: the rest are left out'
                            % (name, len(entries), i + 1, len(layout)))
            for k, s in enumerate(layout):
                pos, yaw, orbs = entries[k % len(entries)]
                if _same_spawn(s, pos, yaw, orbs):
                    continue                     # not moved: the game's own bytes (no float noise, yaw pi stays pi)
                s.pos, s.yaw, s.orbs = _moved_spawn(s, pos, yaw, orbs, scale)
                dat.write_spawn(b, s)
        for w in warn:
            print('Phantom Dust export warning:', w)
        if warn:
            report.append('spawn warnings: %d (see System Console)' % len(warn))
        report.append('%d layouts from the scene into %d slots' % (len(got), len(base_layouts)))
    elif sp is not None:
        report.append('no Spawn Points collection: kept the base spawns')

    if collision_collections(scene):
        tris = gather_collision(context, scale)
        if not tris:
            raise ExportError('the Colliders collection (and Visuals used as collision) has no mesh triangles')
    if collision_collections(scene) and same('collision', tris):
        report.append('collision not edited: kept as the game original has it')
    elif collision_collections(scene):
        patched = None
        if roundtrip.recorded(scene, stage, dat_path=base_path):
            # imported from this very file: the edits go into its own records (untouched ones keep their bytes)
            patched = collision_build.patch(bytes(b), tris, scale=scale)
        if patched is not None:
            b, stats = bytearray(patched[0]), patched[1]
            report.append('collision: %d triangles moved, %d added, %d removed, %d new vertices, written %s' % (
                stats['moved'], stats['added'], stats['removed'], stats['new_vertices'],
                'back into the game\'s own block (the copy an earlier export appended dropped)' if stats.get('back_home')
                else 'in place' if stats['in_place'] else 'into a copy of the block appended to the file'))
        else:
            block, stats = collision_build.build_block(tris)
            b = bytearray(collision_build.append_collision(bytes(b), block))
            report.append('%d collision triangles' % stats['triangles'] + (' (%d degenerate skipped)' % stats['skipped'] if stats.get('skipped') else ''))
        low = floors_below_kill_height(tris)
        if low:
            print('Phantom Dust export warning: %d walkable collision triangles are below the game\'s fall-out height '
                  '(%.0f in game units): players standing there are respawned' % (low, surfaces.KILL_HEIGHT))
            report.append('WARNING: %d floor triangles below the fall-out height: players there get respawned' % low)
        if stats['triangles'] > COLLISION_GUIDE:
            print('Phantom Dust export warning: %d collision triangles; the game\'s maps use far fewer (Visuals used '
                  'as collision count too): a simpler collider is safer' % stats['triangles'])
            report.append('WARNING: %d collision triangles (the game\'s maps use far fewer)' % stats['triangles'])
    else:
        report.append('no Colliders collection: kept the base collision')

    if old_spans is not None:
        # built from the scene: the sprite types (SP00), the stage model list (MD00) with its animation blobs and
        # the enter stream's light list (stage_extras); the game file's sections are removed by datfile.compact
        from . import stage_extras, townlights
        from .pdstage import enter as enter_mod, sp00 as sp00_mod
        sprites = stage_extras.gather_sprites(scene, scale)
        if sprites is not None:
            b = bytearray(sp00_mod.put(bytes(b), sp00_mod.build(sprites)))
            report.append('%d sprite types' % len(sprites))
        town = stage[2:4].isdigit() and int(stage[2:4]) % 10 == 9
        slots = stage_extras.gather_md00(scene, scale)
        if slots is not None:
            md, bl = stage_extras.build_md00(slots, town)
            b = bytearray(stage_extras.put_md00(bytes(b), md, bl))
            report.append('stage models: %d slots, %d animation blobs' % (
                len(slots), sum(1 for s in slots.values() if s['blob'] is not None)))
        if stage_extras.find_collection(scene, 'Enter Lights') is not None:
            lights = stage_extras.gather_enter_lights(scene, scale)
            b = bytearray(enter_mod.put(bytes(b), enter_mod.build(lights)))
            report.append('%d enter lights' % len(lights))
        elif townlights.town_lights(scene):
            pass                                             # the town: written below from Town_Lights
        else:                                                # no enter stream (an empty one places nothing either)
            for k in range(15):
                struct.pack_into('<I', b, enter_mod.H_ENTER + 4 * k, dat.NONE)

    # effects as the export would write them; untouched ones keep the game's own EF00 table
    entries = counts = None
    if eff_cols:
        from . import effects_export
        try:
            carried = {}
            if CARRIED_MODELS:                               # give each copied effect model a free MD00 slot
                md = dat.md00(bytes(b))
                if md is not None:
                    names, anims, pairs = list(md[0]), list(md[1]), list(md[2])
                    free = [i for i in range(min(20, len(pairs))) if pairs[i][0] < 0]
                    for key, (root, name) in sorted(CARRIED_MODELS.items()):
                        if not free:
                            print('Phantom Dust export warning: no free model slot for %s %s' % key)
                            continue
                        i = free.pop(0)
                        names[i], anims[i], pairs[i] = name, 'NOUSE', (root, -1)
                        carried[key] = i
                    b = bytearray(dat.set_md00(bytes(b), names, anims, pairs))
            entries, counts = effects_export.gather(context, eff_cols, scale, game_data, carried)
        except effects_export.EffectsError as e:
            raise ExportError(str(e))
    effects_same = eff_cols and not CARRIED_MODELS and same('effects', entries)
    if entries is not None and not effects_same and roundtrip.ENABLED and remove_objects:
        # the fallback: effects that did not move keep the base file's own entries, moved ones go into their places
        from ._lib import effects_build
        kept = effects_export.in_game_order(entries, [bytes(b[e['offset']:e['offset'] + effects_build.ENTRY])
                                                      for e in dat.effects(b)])
        entries = kept if kept is not None else entries
    table = struct.unpack_from('<I', b, dat.H_EF00)[0]          # the game's effect table, before any clearing
    table_size = struct.unpack_from('<H', b, table + 6)[0] \
        if table != dat.NONE and bytes(b[table:table + 4]) == b'EF00' else None

    if remove_objects and not KEPT_OBJECTS:
        n = dat.clear_placements(b)
        report.append('clean slate: removed %d placed objects of the game original' % n)
    if remove_objects and not effects_same:
        m = dat.clear_effects(b)
        report.append('clean slate: removed %d effects of the game original' % m)
    if KEPT_OBJECTS and ADDED_TYPES:
        b, first = _add_object_types(b, ADDED_TYPES['objects'])
        for off, k in ADDED_TYPES['of_placement'].items():    # the edited types' placements use the new types
            cat, typ = ADDED_TYPES['types'][k]
            struct.pack_into('<iBB', b, off, first + k, cat, typ)
    if KEPT_OBJECTS and MOVED_PLACEMENTS:
        n = sum(_write_placement(b, off, p, scale) for off, p in MOVED_PLACEMENTS)
        report.append('objects: %d moved placements written in place, the rest kept as the game original has it' % n)
    if KEPT_OBJECTS and PLACEMENT_EDIT:
        b, msg = _write_placement_table(b, PLACEMENT_EDIT['kept'], PLACEMENT_EDIT['new'], scale)
        report.append(msg)
    elif KEPT_OBJECTS:
        report.append('objects not edited: kept as the game original has them')
    elif objects:
        from ._lib import objects_build
        b = bytearray(objects_build.add_objects(bytes(b), objects, placements))

    if effects_same:
        report.append('effects not edited: kept as the game original has them')
    elif eff_cols:
        from ._lib import effects_build
        keep = [] if remove_objects else [bytes(b[e['offset']:e['offset'] + effects_build.ENTRY]) for e in dat.effects(b)]
        if remove_objects and table_size == effects_build.ENTRY * len(entries) \
                and struct.unpack_from('<I', b, dat.H_EF00)[0] == table:
            # as many effects as the game's table holds: written in its place (the file keeps its size)
            struct.pack_into('<HH', b, table + 4, len(entries), effects_build.ENTRY * len(entries))
            b[table + 8:table + 8 + effects_build.ENTRY * len(entries)] = b''.join(entries)
        else:
            b = bytearray(effects_build.set_effects(bytes(b), keep + entries))
        report.append('%d effects (%s)' % (len(entries), ', '.join('%d %s' % (n, k.lower()) for k, n in counts.items())))

    from . import lightbake, maplights
    baked = getattr(scene, 'pd_bake_use', False) and any(
        lightbake.baked_light(o) is not None for o in scene.objects if o.type == 'MESH')
    if old_spans is not None and maplights.scene_has_lights(scene):
        # the light script from the scene's light sets, point lights and worlds (maplights.py)
        b = bytearray(maplights.put_script(bytes(b), maplights.build_script(scene, scale, stage), stage))
        report.append('lighting: the 22-call light script from the scene\'s lights and worlds')
    elif getattr(scene, 'pd_light_custom', False) or baked:
        # with baked light maps the lighting always comes from the scene: the Sun's direction (characters'
        # shadows fall the same way as the baked ones) and the Phantom Dust Lighting colours (the game adds the
        # stage ambient to every light map, which was baked for that ambient)
        msg = apply_lighting(scene, b, colours=True)
        b = bytearray(msg[0])
        report.append(msg[1])

    if old_spans is not None:
        from . import townlights
        stream = townlights.build_stream(scene, scale)
        if stream is not None and townlights.stream_offset(bytes(b)) is not None:
            # the town's light list (st09.dat header 0xFC) from the scene's town lights
            b = bytearray(townlights.put_stream(bytes(b), stream))
            report.append('town light list: %d lights from the scene' % len(townlights.town_lights(scene)))
        data, removed = datfile.compact(bytes(b), old_spans)
        b = bytearray(data)
        if removed:
            report.append('%d bytes of replaced game sections left out' % removed)
    with open(out_path, 'wb') as f:
        f.write(b)
    return '; '.join(report)


def _byte_colour(c):
    return tuple(int(round(max(0.0, min(1.0, x)) * 255)) for x in c[:3])


def apply_lighting(scene, b, colours=True, baked=False):
    """Scene lighting settings -> the game original's light script (light set 0 = stage, objects and effects;
    set 1 = characters). The direction comes from the scene's Sun (pd_sun), else the game original's.
    Returns (new bytes, report text)."""
    from ._lib import maplight
    # the first light script of the map: variant 0's, or (st12-st15, st22-st25, st32 have none there) the first
    # variant slot that has one
    script = next((s for s in (maplight.script_of(bytes(b), v) for v in range(maplight.VARIANT_SLOTS))
                   if s is not None), None)
    if script is None:
        raise ExportError('the game original has no lighting script')
    sun = scene.pd_sun
    if sun is None or sun.type != 'LIGHT' or sun.name not in scene.objects:   # a deleted sun can linger here
        from . import lightbake
        sun = next((o for o in lightbake.lights(scene) if o.data.type == 'SUN'), None)
    if sun is not None and sun.type == 'LIGHT':
        d = sun.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))   # the way the light travels
        d = Vector(cv.to_game(d, 1.0)).normalized()
        direction, src = tuple(d), 'from %s' % sun.name
    else:
        direction, src = None, 'game original direction'
    if not colours and direction is None:
        return bytes(b), 'game original lighting'
    def edit(script):
        sets = maplight.describe(script)['sets']
        for i, (light, amb) in enumerate(((scene.pd_stage_light, scene.pd_stage_ambient),
                                          (scene.pd_char_light, scene.pd_char_ambient))):
            if colours:
                light, amb = _byte_colour(light), _byte_colour(amb)
            else:
                light, amb = sets[i]['diffuse'], sets[i]['ambient']
            d = direction or sets[i]['direction']
            if direction and i == 1:
                # characters (set 1, which also casts their real-time shadows) read the direction with its two
                # horizontal axes swapped: confirmed in game, the shadow then falls the way the scene Sun shines
                d = (direction[2], direction[1], direction[0])
            maplight.set_light(script, i, d, light, amb)
    text = ('custom lighting (%s)' % src if colours else 'sun direction %s for the baked lighting' % src)
    # every light script of the map (one per placement variant) edited where it is when it keeps its length:
    # only the changed words change and each variant keeps its own script
    out, ok = bytearray(b), True
    offsets = {}
    for v in range(maplight.VARIANT_SLOTS):
        o = struct.unpack_from('<I', out, maplight.H_SCRIPT + 4 * v)[0]
        if o != 0xFFFFFFFF and o not in offsets:
            offsets[o] = v
    for o, v in offsets.items():
        sv = maplight.script_of(bytes(b), v)
        if sv is None:
            ok = False
            break
        old_len = struct.unpack_from('<I', b, o + 4)[0] + 12
        edit(sv)
        new = maplight.build(sv)
        if len(new) != old_len:
            ok = False
            break
        out[o:o + len(new)] = new
    if ok and offsets:
        return bytes(out), text
    edit(script)
    return maplight.write(bytes(b), script), text
