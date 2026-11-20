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
                co = [cv.to_game(mw @ v.co, scale) for v in me.vertices]
                for lt in me.loop_triangles:
                    a, b, c3 = (co[i] for i in lt.vertices)
                    # the mirror to game space reverses winding; a mirrored object reverses it once more
                    tris.append((a, b, c3, ost) if flip else (a, c3, b, ost))
            finally:
                ev.to_mesh_clear()
    return tris


COLLISION_GUIDE = 10000  # collision triangles: the game's maps use 2,700-9,300; a 52k one crashed on load
CARRIED_MODELS = {}      # (home map, MD00 slot) -> (new .alr root, model name), from the last export_models


def export_models(context, game_original_alr, out_alr_path, scale, background_and_sky=False, shadows=True,
                  compress_textures=False, texture_budget_mb=12, lightmap_budget_mb=16):
    """Write the .alr from Visuals and Objects collections.

    Returns (report string, objects, placements) for the .dat, or (None, None, None) when the scene has
    neither Visuals nor Objects (the base model file is then not needed)."""
    from . import objects_export as ox
    from . import visuals_export as vx
    global CARRIED_MODELS
    CARRIED_MODELS = {}
    scene = context.scene
    vis_cols = collections_with_role(scene, 'VISUALS')
    obj_cols = collections_with_role(scene, 'OBJECTS')
    if not vis_cols and not obj_cols and not scene.pd_sky_custom:
        return None, None, None
    if not os.path.isfile(game_original_alr):
        raise ExportError('game original model not found: %s (%s)' % (game_original_alr, missing_hint(
            os.path.dirname(os.path.dirname(game_original_alr)))))
    base = open(game_original_alr, 'rb').read()
    textures = vx.Textures(vx.alr.textures(base), compress=compress_textures)
    report = []
    try:
        replace, vstats = vx.gather(context, vis_cols, scale, textures) if vis_cols else ({}, dict(clamped_uv=0))
        types, ostats = ox.gather(context, obj_cols, scale, textures) if obj_cols else ([], dict(clamped_uv=0))
    except (vx.VisualsError, ox.ObjectsError) as e:
        raise ExportError(str(e))
    if not background_and_sky:
        replace = {k: v for k, v in replace.items() if k == 0}
    if scene.pd_sky_custom:
        from . import sky
        from ._lib import sky_build
        built_sky = sky_build.build_sky(base, **sky.settings(scene, textures))
        for m in replace.get(2, []):                         # Sky collection meshes (if exported) on top,
            m['node'] = built_sky['extra_node']              # on the sky's own untransformed node
        built_sky['meshes'] = built_sky['meshes'] + list(replace.get(2, []))
        replace[2] = built_sky
        report.append('custom sky%s: gradient dome, clouds, sun %s' % (
            ' (%s)' % scene.pd_sky_preset if scene.pd_sky_preset else '',
            'turned to the scene Sun' if sky.sun_direction(scene) else 'as the replaced map has it'))
    if vis_cols and not replace:
        raise ExportError('the Visuals collection has no mesh triangles for the stage')
    add_models = [m for t in types for m in t['models'] if m is not None]
    # effect models of imported effects from another map (Storm Refinery's sea...): copied in as extra roots
    from . import effects_export
    fx_models, fx_keys, fx_names = effects_export.foreign_models(
        scene, os.path.dirname(os.path.dirname(game_original_alr)), len(vx.alr.textures(base)), textures.new)
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
    data, built = vx.alr_build.rebuild(base, replace=replace, textures=textures.new,
                                       add_models=add_models + fx_models,
                                       shadows_for=(0,) if shadows and 0 in replace else ())
    with open(out_alr_path, 'wb') as f:
        f.write(data)
    def meshes_of(model):                                    # a list of meshes, or dict(meshes, nodes, ...)
        return model['meshes'] if isinstance(model, dict) else model

    def tris_of(m):                                          # a written mesh, or one carried over as is (raw)
        return m['raw']['tris'] if 'raw' in m else m['tris']

    if replace:
        written = sum(len(tris_of(m)) for model in replace.values() for m in meshes_of(model))
        report.append('model: %d triangles' % written + (', character shadows on' if shadows and 0 in replace else ''))
        stage_tris = sum(len(tris_of(m)) for m in meshes_of(replace[0])) if 0 in replace else 0
        if stage_tris > 500000:                              # tested in game: 1M flickers and loses shadows
            print('Phantom Dust export warning: the stage has %d triangles; above 500,000 the game may flicker '
                  '(colours and shapes) and lose its shadows' % stage_tris)
            report.append('WARNING: %dk stage triangles, above 500k the game may flicker and lose shadows'
                          % (stage_tris // 1000))
    kinds = {}
    for model in list(replace.values()) + list(add_models):
        for m in meshes_of(model):
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
    if obj_cols:
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
    (presets read from game_data)."""
    if not os.path.isfile(base_path):
        raise ExportError('game original file not found: %s (set the game data folder in the export options)' % base_path)
    if os.path.abspath(out_path) == os.path.abspath(base_path):
        raise ExportError('choose a different output file than the game original (back it up and copy over it afterwards)')
    scene = context.scene
    b = bytearray(open(base_path, 'rb').read())
    report = []

    sp = collections_with_role(scene, 'SPAWNS')
    if len(sp) > 1:
        raise ExportError('more than one Spawn Points collection: %s' % ', '.join(c.name for c in sp))
    if sp:
        base_layouts = dat.spawn_layouts(b)
        got = gather_spawns(sp[0], scale)
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
                s.pos, s.yaw, s.orbs = entries[k % len(entries)]
                dat.write_spawn(b, s)
        for w in warn:
            print('Phantom Dust export warning:', w)
        if warn:
            report.append('spawn warnings: %d (see System Console)' % len(warn))
        report.append('%d layouts from the scene into %d slots' % (len(got), len(base_layouts)))
    else:
        report.append('no Spawn Points collection: kept the base spawns')

    if collision_collections(scene):
        tris = gather_collision(context, scale)
        if not tris:
            raise ExportError('the Colliders collection (and Visuals used as collision) has no mesh triangles')
        block, stats = collision_build.build_block(tris)
        b = bytearray(collision_build.append_collision(bytes(b), block))
        report.append('%d collision triangles' % stats['triangles'] + (' (%d degenerate skipped)' % stats['skipped'] if stats['skipped'] else ''))
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

    if remove_objects:
        n = dat.clear_placements(b)
        m = dat.clear_effects(b)
        report.append('clean slate: removed %d placed objects and %d effects of the game original' % (n, m))
    if objects:
        from ._lib import objects_build
        b = bytearray(objects_build.add_objects(bytes(b), objects, placements))

    eff_cols = collections_with_role(scene, 'EFFECTS')
    if eff_cols:
        from . import effects_export
        from ._lib import effects_build
        try:
            carried = {}
            if CARRIED_MODELS:                               # give each copied effect model a free MD00 slot
                md = dat.md00(bytes(b))
                if md is not None:
                    names, anims, pairs = list(md[0]), list(md[1]), list(md[2])
                    free = [i for i in range(20) if pairs[i][0] < 0]
                    for key, (root, name) in sorted(CARRIED_MODELS.items()):
                        if not free:
                            print('Phantom Dust export warning: no free model slot for %s %s' % key)
                            continue
                        i = free.pop(0)
                        names[i], anims[i], pairs[i] = name, 'NOUSE', (root, -1)
                        carried[key] = i
                    b = bytearray(dat.set_md00(bytes(b), names, anims, pairs))
            entries, counts = effects_export.gather(context, eff_cols, scale,
                                                    game_data or os.path.dirname(os.path.dirname(base_path)), carried)
        except effects_export.EffectsError as e:
            raise ExportError(str(e))
        keep = [] if remove_objects else [bytes(b[e['offset']:e['offset'] + effects_build.ENTRY]) for e in dat.effects(b)]
        b = bytearray(effects_build.set_effects(bytes(b), keep + entries))
        report.append('%d effects (%s)' % (len(entries), ', '.join('%d %s' % (n, k.lower()) for k, n in counts.items())))

    from . import lightbake
    baked = getattr(scene, 'pd_bake_use', False) and any(
        lightbake.baked_light(o) is not None for o in scene.objects if o.type == 'MESH')
    if getattr(scene, 'pd_light_custom', False) or baked:
        # with baked light maps the lighting always comes from the scene: the Sun's direction (characters'
        # shadows fall the same way as the baked ones) and the Phantom Dust Lighting colours (the game adds the
        # stage ambient to every light map, which was baked for that ambient)
        msg = apply_lighting(scene, b, colours=True)
        b = bytearray(msg[0])
        report.append(msg[1])

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
    script = maplight.script_of(bytes(b))
    if script is None:
        raise ExportError('the game original has no lighting script')
    sets = maplight.describe(script)['sets']
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
    return maplight.write(bytes(b), script), ('custom lighting (%s)' % src if colours else
                                              'sun direction %s for the baked lighting' % src)
