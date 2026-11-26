"""Scale guides drawn in the 3D view only: the game's own player model (Edgar, `player` in charaset) T-posing
as a wireframe on every spawn point, and the game's aura capsule (Map\\st00.alr, the shared stage models) glowing
on every orb point. They are viewport overlays (a draw handler), not objects: nothing is exported, baked or saved.

The player model is read in its bind pose, which is a T-pose (about 18.9 units tall, arms out to +-9.6), feet at
the spawn point, facing the spawn empty's +Y. The capsule is st00 root 4 (textures e3o_aura03, e1n_ecp02f,
e1n_ecry06; the game loads it with Map\\st00 for every stage): a sphere of radius 4.5 units with two camera-facing
glow rings. The game colours the sphere with lighting constants set in code, so the colour here is a setting.
Both are read from the game data folder (add-on preferences); without it simple stand-ins are drawn.
"""

import math

import bpy
from bpy.props import BoolProperty, FloatVectorProperty
from mathutils import Matrix

PLAYER_FOLDER = 'pc00a'          # charaset record 0: model folder pc00a, name "player" (Edgar)
CAPSULE_ROOT = 4                 # st00.alr: the aura capsule (vkcap02 sphere + vkcapm2a / vkcapm2mm2 rings)
HIT_RADIUS, PLAYER_HEIGHT = 5.0, 18.0
DUMMY_COLOUR = (0.45, 0.8, 1.0, 0.85)
HIT_COLOUR = (0.45, 0.8, 1.0, 0.25)

# game (x, y up, z) -> Blender (x, z, y): the add-on's mirror conversion (convert.to_blender)
GAME_TO_BLENDER = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))

_handle = None
_cache = {}          # key -> (game folder it came from, data)
_gpu = {}            # key -> (game folder, GPU batches / textures)


# ---------------------------------------------------------------- reading the game's models

def _game_folder():
    try:
        from . import scene_tools
        return bpy.path.abspath(scene_tools._prefs_game_data(bpy.context))
    except Exception:
        return ''


def _find(*parts):
    from . import exporter
    p = _game_folder()
    if not p:
        return None
    for name in parts:
        p = exporter._child(p, name)
        if p is None:
            return None
    return p


def _player_file():
    """The original player model: the add-on's backup if the character was replaced, else colour 1."""
    return (_find('Player', PLAYER_FOLDER, 'pd_addon_backup', PLAYER_FOLDER + '0.alr')
            or _find('Player', PLAYER_FOLDER, PLAYER_FOLDER + '0.alr'))


def player_edges():
    """Unique triangle edges of the player model's visible draws, game space: flat list of points (pairs)."""
    path = _player_file()
    if path is None:
        return None
    from .pdstage import alr, character as ch
    b = open(path, 'rb').read()
    roots = alr.header(b)['roots']
    pts, seen = [], set()
    for ri in ch.model_roots(b):
        model = ch.read_model(b, roots[ri])
        for d in model['draws']:
            m = model['materials'][d['material']] if d['material'] < len(model['materials']) else None
            if m is not None and m['shader'] in ch.HIDDEN_SHADERS:
                continue
            pos, _uv, _w, tris, _n = ch.draw_vertices(b, model, d)
            for t in tris:
                for i, j in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                    a, c = tuple(round(x, 3) for x in pos[i]), tuple(round(x, 3) for x in pos[j])
                    key = (a, c) if a < c else (c, a)
                    if key not in seen:
                        seen.add(key)
                        pts += [a, c]
    return pts


def capsule_parts():
    """The aura capsule's meshes: list of dict(pos (game space), uv, tris, rgba (w, h, bytes top row first),
    billboard). The rings (vkcapm2*) are billboards: their x/y plane faces the camera."""
    path = _find('Map', 'st00.alr')
    if path is None:
        return None
    from .pdstage import alr, character as ch
    b = open(path, 'rb').read()
    h = alr.header(b)
    texs = alr.textures(b)
    out = []
    for m in alr.meshes(b, h['roots'][CAPSULE_ROOT]):
        e = m['materials'][m['material']] if m['material'] < len(m['materials']) else None
        if e is None or m['vbuf'] >= len(m['vbufs']):
            continue
        pos, uv, _uv2 = alr.read_vertices(b, h['resource_offset'], m['vbufs'][m['vbuf']])
        tris = alr.triangles_from_indices(m['indices'], m['primitive'])
        t = e['textures'][0]
        rgba = ch.decode_texture(b, texs[t]) if t is not None and t < len(texs) else None
        if not tris or rgba is None:
            continue
        out.append(dict(pos=pos, uv=uv or [(0.0, 0.0)] * len(pos), tris=tris, rgba=rgba,
                        billboard=e['shader'] != 'vkcap02', shader=e['shader']))
    return out


def _cached(key, fn):
    folder = _game_folder()
    hit = _cache.get(key)
    if hit is not None and hit[0] == folder:
        return hit[1]
    try:
        data = fn()
    except Exception as e:                         # a broken or missing file: draw the stand-in instead
        print('Phantom Dust guides: %s not read (%s)' % (key, e))
        data = None
    _cache[key] = (folder, data)
    return data


# ---------------------------------------------------------------- stand-ins (no game folder)

def _box(c, s):
    x, y, z = c
    hx, hy, hz = s[0] / 2, s[1] / 2, s[2] / 2
    p = [(x + a * hx, y + b * hy, z + d * hz) for a in (-1, 1) for b in (-1, 1) for d in (-1, 1)]
    edges = ((0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7))
    return [q for i, j in edges for q in (p[i], p[j])]


def _ring(c, r, n=24):
    """A circle in the game's horizontal plane (x, z) at height c[1], as line pairs."""
    out = []
    for k in range(n):
        for t in (k, k + 1):
            a = 2 * math.pi * t / n
            out.append((c[0] + r * math.cos(a), c[1], c[2] + r * math.sin(a)))
    return out


def stand_in_edges():
    """A plain T-pose figure 18 units tall (game space: y up, facing +z)."""
    s = _box((0, 16.4, 0), (2.6, 3.2, 2.8)) + _box((0, 11.9, 0), (4.8, 4.6, 2.4)) + _box((0, 8.9, 0), (3.8, 1.6, 2.2))
    for sx in (-1, 1):
        s += _box((sx * 5.4, 13.6, 0), (7.5, 1.2, 1.2)) + _box((sx * 1.1, 4.3, 0), (1.5, 8.2, 1.6))
    return s


def hit_edges():
    s = _ring((0, 0.05, 0), HIT_RADIUS) + _ring((0, PLAYER_HEIGHT, 0), HIT_RADIUS)
    for k in range(8):
        a = 2 * math.pi * k / 8
        x, z = HIT_RADIUS * math.cos(a), HIT_RADIUS * math.sin(a)
        s += [(x, 0.05, z), (x, PLAYER_HEIGHT, z)]
    return s


# ---------------------------------------------------------------- GPU resources (built once per session)

def _line_shader():
    import gpu
    try:
        return gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR'), True
    except (ValueError, SystemError):
        return gpu.shader.from_builtin('UNIFORM_COLOR'), False


def _glow_shader():
    """Texture x colour, added on top (emission). UVs wrap in the shader (fract): the capsule's run past 1."""
    import gpu
    if 'glow' in _gpu:
        return _gpu['glow']
    info = gpu.types.GPUShaderCreateInfo()
    iface = gpu.types.GPUStageInterfaceInfo('pd_glow_iface')
    iface.smooth('VEC2', 'uvInterp')
    info.vertex_in(0, 'VEC3', 'pos')
    info.vertex_in(1, 'VEC2', 'uv')
    info.vertex_out(iface)
    info.push_constant('MAT4', 'ModelViewProjectionMatrix')
    info.push_constant('VEC4', 'tint')
    info.sampler(0, 'FLOAT_2D', 'image')
    info.fragment_out(0, 'VEC4', 'FragColor')
    info.vertex_source('void main() { uvInterp = uv; '
                       'gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0); }')
    info.fragment_source('void main() { vec4 t = texture(image, fract(uvInterp)); '
                         'FragColor = vec4(t.rgb * tint.rgb * tint.a, 1.0); }')
    sh = gpu.shader.create_from_info(info)
    _gpu['glow'] = sh
    return sh


def _texture(rgba):
    import gpu
    import numpy as np
    w, h, px = rgba
    data = np.frombuffer(px, np.uint8).astype(np.float32) / 255.0
    buf = gpu.types.Buffer('FLOAT', w * h * 4, data.tolist())
    return gpu.types.GPUTexture((w, h), format='RGBA16F', data=buf)


def _player_batch():
    """(edges batch, hit-capsule batch, shader, polyline?) for the dummy, in local game space."""
    folder = _game_folder()
    if 'player' in _gpu and _gpu['player'][0] == folder:
        return _gpu['player'][1]
    from gpu_extras.batch import batch_for_shader
    pts = _cached('player', player_edges) or stand_in_edges()
    shader, poly = _line_shader()
    batch = batch_for_shader(shader, 'LINES', {'pos': pts})
    hit = batch_for_shader(shader, 'LINES', {'pos': hit_edges()})
    _gpu['player'] = (folder, (batch, hit, shader, poly))
    return _gpu['player'][1]


def _capsule_batches():
    """[(batch, texture, billboard)], or None without the game folder (a wire sphere stand-in is drawn)."""
    folder = _game_folder()
    if 'capsule' in _gpu and _gpu['capsule'][0] == folder:
        return _gpu['capsule'][1]
    from gpu_extras.batch import batch_for_shader
    parts = _cached('capsule', capsule_parts)
    out = None
    if parts:
        sh = _glow_shader()
        out = [(batch_for_shader(sh, 'TRIS', {'pos': p['pos'], 'uv': p['uv']}, indices=p['tris']),
                _texture(p['rgba']), p['billboard']) for p in parts]
    _gpu['capsule'] = (folder, out)
    return out


# ---------------------------------------------------------------- what to draw where

def spawns_and_orbs(scene):
    from . import exporter
    spawns, orbs = [], []
    for sp in exporter.collections_with_role(scene, 'SPAWNS'):
        for lc in sp.children:
            for s in exporter._spawn_objects(lc):
                if not s.visible_get():
                    continue
                spawns.append(s)
                orbs.extend(o for o in s.children if o.visible_get())
    return spawns, orbs


def _spawn_matrix(ob, unit):
    loc, rot, _scale = ob.matrix_world.decompose()
    # the player model faces game -z; turned half a turn so it looks along the spawn's +Y (its in-game facing)
    return (Matrix.Translation(loc) @ rot.to_matrix().to_4x4() @ Matrix.Rotation(math.pi, 4, 'Z')
            @ Matrix.Scale(unit, 4) @ GAME_TO_BLENDER)


def _draw():
    ctx = bpy.context
    scene = ctx.scene
    if scene is None or not getattr(scene, 'pd_show_guides', False):
        return
    space = ctx.space_data
    if space is None or getattr(space, 'type', '') != 'VIEW_3D' or not space.overlay.show_overlays:
        return
    try:
        spawns, orbs = spawns_and_orbs(scene)
    except Exception:
        return
    if not spawns and not orbs:
        return
    import gpu
    unit = scene.pd_scale
    region = ctx.region
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.depth_mask_set(False)
    try:
        if spawns:
            batch, hit, shader, poly = _player_batch()
            gpu.state.blend_set('ALPHA')
            shader.bind()
            if poly:
                shader.uniform_float('viewportSize', (region.width, region.height))
                shader.uniform_float('lineWidth', 1.0)
            for s in spawns:
                with gpu.matrix.push_pop():
                    gpu.matrix.multiply_matrix(_spawn_matrix(s, unit))
                    shader.uniform_float('color', DUMMY_COLOUR)
                    batch.draw(shader)
                    if scene.pd_show_hitbox:
                        shader.uniform_float('color', HIT_COLOUR)
                        hit.draw(shader)
        if orbs:
            _draw_capsules(ctx, scene, orbs, unit)
    except Exception as e:                                # never break the viewport
        if not _cache.get('_reported'):
            print('Phantom Dust guides: drawing failed:', e)
            _cache['_reported'] = True
    finally:
        gpu.state.depth_mask_set(True)
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('NONE')


def _draw_capsules(ctx, scene, orbs, unit):
    import gpu
    parts = _capsule_batches()
    tint = tuple(scene.pd_capsule_colour)
    if not parts:                                    # stand-in: a wire sphere of the capsule's radius
        from gpu_extras.batch import batch_for_shader
        shader, poly = _line_shader()
        ring = _ring((0, 0, 0), 4.5, 32)
        pts = ring + [(p[0], p[2], p[1]) for p in ring] + [(p[1], p[0], p[2]) for p in ring]
        batch = batch_for_shader(shader, 'LINES', {'pos': pts})
        gpu.state.blend_set('ALPHA')
        shader.bind()
        if poly:
            shader.uniform_float('viewportSize', (ctx.region.width, ctx.region.height))
            shader.uniform_float('lineWidth', 1.5)
        shader.uniform_float('color', tint + (1.0,))
        for o in orbs:
            with gpu.matrix.push_pop():
                gpu.matrix.multiply_matrix(Matrix.Translation(o.matrix_world.translation) @ Matrix.Scale(unit, 4))
                batch.draw(shader)
        return
    sh = _glow_shader()
    view = ctx.region_data.view_rotation.to_matrix().to_4x4()   # camera right, up, towards the viewer
    gpu.state.blend_set('ADDITIVE')
    gpu.state.face_culling_set('NONE')
    sh.bind()
    for o in orbs:
        at = Matrix.Translation(o.matrix_world.translation) @ Matrix.Scale(unit, 4)
        for batch, tex, billboard in parts:
            with gpu.matrix.push_pop():
                # the sphere upright in game space; the rings' x/y plane facing the camera, as the game draws them
                gpu.matrix.multiply_matrix(at @ (view if billboard else GAME_TO_BLENDER))
                sh.uniform_sampler('image', tex)
                sh.uniform_float('tint', tint + (0.75 if billboard else 1.0,))
                batch.draw(sh)


# ---------------------------------------------------------------- UI and registration

def _redraw(self, context):
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def draw_settings(layout, context):
    s = context.scene
    row = layout.row(align=True)
    row.prop(s, 'pd_show_guides', text='Scale Guides', icon='ARMATURE_DATA', toggle=True)
    sub = row.row(align=True)
    sub.active = s.pd_show_guides
    sub.prop(s, 'pd_show_hitbox', text='', icon='MESH_CYLINDER', toggle=True)
    sub.prop(s, 'pd_capsule_colour', text='')
    if s.pd_show_guides and not _game_folder():
        layout.label(text='Set the game data folder for the real models', icon='INFO')


def register():
    global _handle
    bpy.types.Scene.pd_show_guides = BoolProperty(
        name='Scale Guides', default=True, update=_redraw,
        description='Draw the game\'s player model (T-pose wireframe) on every spawn point and the aura capsule '
                    'on every orb point. Viewport only: never exported or baked')
    bpy.types.Scene.pd_show_hitbox = BoolProperty(
        name='Hit Capsule', default=False, update=_redraw,
        description='Also draw the fighter\'s hit capsule (radius 5, 18 tall) around the dummies')
    bpy.types.Scene.pd_capsule_colour = FloatVectorProperty(
        name='Capsule Colour', subtype='COLOR', size=3, min=0.0, soft_max=1.0, default=(1.0, 0.85, 0.35),
        update=_redraw, description='Glow colour of the drawn capsules (the game sets it in code)')
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_VIEW')


def unregister():
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        _handle = None
    _gpu.clear()
    _cache.clear()
    for k in ('pd_show_guides', 'pd_show_hitbox', 'pd_capsule_colour'):
        if hasattr(bpy.types.Scene, k):
            try:
                delattr(bpy.types.Scene, k)
            except AttributeError:
                pass
