"""Custom sky: Scene Properties > Phantom Dust Sky (and the sidebar).

Off: the replaced map's own sky stays. On: the sky model is rebuilt from the replaced map's sky layers and these
settings (pdstage/sky_build.py): a gradient dome (four colours by height, shown in game exactly as picked: the dome
shader is unlit), the cloud layers with your textures and speeds, and the sun glow turned to the scene's Sun.
Presets fill the settings from any game map's sky. The preview is one big inverted sphere ("PD Sky Preview", made by
New Map Setup or Preview Sky) whose shader shows the gradient with the clouds scrolling over it (press Play).
"""
import math
import os

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatVectorProperty, IntVectorProperty, PointerProperty, \
    StringProperty

from . import convert as cv
from ._lib import sky_build

# elevations (degrees) of the four dome colours
STOPS = (('pd_sky_top', 90.0), ('pd_sky_upper', 35.0), ('pd_sky_horizon', 0.0), ('pd_sky_bottom', -90.0))
SPEED_PROPS = ('pd_cloud_speed_colour', 'pd_cloud_speed_shape_a', 'pd_cloud_speed_shape_b')
TEX_PROPS = ('pd_cloud_texture', 'pd_cloud_texture_shape_a', 'pd_cloud_texture_shape_b')
LAYER_NAMES = ('Clouds', 'Shape A', 'Shape B')
WORLD_PREFIX = 'pd_sky_'


def _byte(x):
    return int(round(max(0.0, min(1.0, x)) * 255))


def dome_stops(scene):
    return [(e, tuple(_byte(c) for c in getattr(scene, p))) for p, e in STOPS]


def sun_direction(scene):
    """Unit vector (game space) from the map towards the scene's Sun, or None without one."""
    sun = getattr(scene, 'pd_sun', None)
    if sun is None or sun.type != 'LIGHT':
        return None
    from mathutils import Vector
    d = sun.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))     # a light shines down its -Z: the sun is up its +Z
    if d.length < 1e-9:
        return None
    d.normalize()
    return (d.x, d.z, d.y)                                     # Blender -> game axes (convert.py)


def settings(scene, textures):
    """Keyword arguments for sky_build.build_sky from the scene (textures: visuals_export.Textures)."""
    texs = {}
    for k, p in enumerate(TEX_PROPS):
        img = getattr(scene, p)
        if img is None:
            continue
        if img.get('pd_tex_map') == scene.pd_game_original and 'pd_tex_index' in img:
            texs[k] = ('base', int(img['pd_tex_index']))       # the replaced map's own texture: reuse it as is
        else:
            texs[k] = textures.ref(img)
    return dict(dome_stops=dome_stops(scene), keep_dome=False, dome_shape='GAME_ORIGINAL', clouds='CUSTOM',
                cloud_speeds=[tuple(getattr(scene, p)) for p in SPEED_PROPS], cloud_textures=texs or None,
                sun=True, sun_direction=sun_direction(scene))


def _linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


# ---------------------------------------------------------------- viewport background (scene world)

def sync_world(scene):
    """Show the gradient as the background camera rays see (behind the preview sphere); other rays (Bake Lighting)
    keep the world's own light. Idempotent; nodes are named pd_sky_*."""
    world = scene.world
    if world is None:
        return
    on = scene.pd_sky_custom
    if not world.use_nodes:
        if not on:
            return
        world.use_nodes = True
    nt = world.node_tree
    out = next((n for n in nt.nodes if n.type == 'OUTPUT_WORLD' and n.is_active_output), None) or \
        next((n for n in nt.nodes if n.type == 'OUTPUT_WORLD'), None)
    if out is None:
        return
    mix = nt.nodes.get(WORLD_PREFIX + 'mix')
    if mix is None:
        if not on:
            return
        src = out.inputs['Surface'].links[0].from_socket if out.inputs['Surface'].is_linked else None
        mix = nt.nodes.new('ShaderNodeMixShader')
        mix.name = mix.label = WORLD_PREFIX + 'mix'
        mix.location = (out.location.x - 200, out.location.y)
        lp = nt.nodes.new('ShaderNodeLightPath')
        lp.name = WORLD_PREFIX + 'lightpath'
        lp.location = (mix.location.x - 250, mix.location.y + 300)
        tc = nt.nodes.new('ShaderNodeTexCoord')
        tc.name = WORLD_PREFIX + 'coords'
        tc.location = (mix.location.x - 900, mix.location.y - 300)
        sep = nt.nodes.new('ShaderNodeSeparateXYZ')
        sep.name = WORLD_PREFIX + 'sep'
        sep.location = (mix.location.x - 700, mix.location.y - 300)
        fac = nt.nodes.new('ShaderNodeMath')
        fac.name = WORLD_PREFIX + 'fac'
        fac.operation = 'MULTIPLY_ADD'
        fac.inputs[1].default_value = 0.5
        fac.inputs[2].default_value = 0.5
        fac.location = (mix.location.x - 550, mix.location.y - 300)
        ramp = nt.nodes.new('ShaderNodeValToRGB')
        ramp.name = WORLD_PREFIX + 'ramp'
        ramp.location = (mix.location.x - 400, mix.location.y - 300)
        bg = nt.nodes.new('ShaderNodeBackground')
        bg.name = WORLD_PREFIX + 'background'
        bg.location = (mix.location.x - 150, mix.location.y - 300)
        links = nt.links
        links.new(tc.outputs['Generated'], sep.inputs['Vector'])
        links.new(sep.outputs['Z'], fac.inputs[0])
        links.new(fac.outputs[0], ramp.inputs['Fac'])
        links.new(ramp.outputs['Color'], bg.inputs['Color'])
        links.new(lp.outputs['Is Camera Ray'], mix.inputs['Fac'])
        if src is not None:
            links.new(src, mix.inputs[1])
        links.new(bg.outputs['Background'], mix.inputs[2])
        links.new(mix.outputs['Shader'], out.inputs['Surface'])
        els = ramp.color_ramp.elements
        while len(els) < 4:
            els.new(0.5)
    lp = nt.nodes.get(WORLD_PREFIX + 'lightpath')
    ramp = nt.nodes.get(WORLD_PREFIX + 'ramp')
    if lp is None or ramp is None:
        return
    if on:
        nt.links.new(lp.outputs['Is Camera Ray'], mix.inputs['Fac'])
    else:
        for l in list(mix.inputs['Fac'].links):
            nt.links.remove(l)
        mix.inputs['Fac'].default_value = 0.0
    els = ramp.color_ramp.elements
    for el, (prop, elev) in zip(els, reversed(STOPS)):
        el.position = 0.5 + 0.5 * math.sin(math.radians(elev))
        c = getattr(scene, prop)
        el.color = (_linear(c[0]), _linear(c[1]), _linear(c[2]), 1.0)


def _update(self, context):
    try:
        sync_world(context.scene)
        sync_sphere(context.scene)
    except Exception as e:                                   # the preview must never block a setting
        print('Phantom Dust Stage: sky preview:', e)


# ---------------------------------------------------------------- presets

def _game_data(context):
    try:
        return bpy.path.abspath(context.preferences.addons[__package__].preferences.game_data)
    except (KeyError, AttributeError):
        return ''


def _map_file(context, key):
    from . import exporter
    data = _game_data(context)
    path = exporter.game_original_alr(data, key) if data else ''
    if not path or not os.path.isfile(path):
        raise RuntimeError('Set the game data folder in the add-on preferences')
    return path


def _picture_samples(layer, img):
    """(elevation, (r, g, b) 0-255) samples of a picture dome: its texture at the vertices and triangle centres,
    times the vertex colours."""
    import numpy as np
    if img is None:
        return []
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    pts = list(zip(layer['pos'], layer['uv'], layer['col']))
    for t in layer['tris']:
        a, b, c = (pts[i] for i in t[:3])
        pts.append((tuple((a[0][k] + b[0][k] + c[0][k]) / 3 for k in range(3)),
                    tuple((a[1][k] + b[1][k] + c[1][k]) / 3 for k in range(2)),
                    tuple((a[2][k] + b[2][k] + c[2][k]) / 3 for k in range(4))))
    out = []
    for p, (u, v), col in pts:
        x = int((u % 1.0) * w) % w
        y = int(((1.0 - v) % 1.0) * h) % h                  # Blender's pixel rows run bottom-up
        r = math.sqrt(p[0] * p[0] + p[1] * p[1] + p[2] * p[2]) or 1.0
        el = math.degrees(math.asin(max(-1.0, min(1.0, p[1] / r))))
        out.append((el, tuple(px[y, x, k] * col[k] for k in range(3))))
    return out


def apply_preset(context, key):
    """Fill the sky settings from map `key`'s sky: dome colours (a picture dome sampled into the gradient), cloud
    speeds and cloud textures (none when it is the replaced map itself: its own are used)."""
    import tempfile
    from . import visuals
    from ._lib import alr
    scene = context.scene
    b = open(_map_file(context, key), 'rb').read()
    texs = alr.textures(b)
    layers = sky_build.preview_layers(b)
    info = sky_build.read_sky(b)
    with tempfile.TemporaryDirectory() as tmp:
        cache = {}

        def image(i, role):
            if i is None or i >= len(texs):
                return None
            name = 'PD %s %s' % (key, role)
            img = bpy.data.images.get(name)
            if img is None:
                img = visuals._image(b, texs[i], cache, tmp)
                if img is not None:
                    img.name = name
            if img is not None:
                img['pd_tex_map'] = key                     # where it came from: exported as that map's texture
                img['pd_tex_index'] = i
            return img

        samples = list(info['dome_colours'])
        dome = next((l for l in layers if l['kind'] == 'dome'), None)
        if info['dome'] == 'picture' and dome is not None and dome['textures']:
            samples = _picture_samples(dome, image(dome['textures'][0], 'dome'))
        if samples:
            for (prop, _e), c in zip(STOPS, sky_build.dome_colours_at(samples)):
                setattr(scene, prop, tuple(min(1.0, x / 255) for x in c))
        cl = next((l for l in layers if l['kind'] == 'clouds'), None)
        if cl is not None:
            v = cl['speeds']
            for k, p in enumerate(SPEED_PROPS):
                setattr(scene, p, (v[2 * k], v[2 * k + 1]))
            for k, p in enumerate(TEX_PROPS):
                t = cl['textures'][k] if k < len(cl['textures']) else None
                setattr(scene, p, image(t, LAYER_NAMES[k].lower()))
    scene.pd_sky_preset = dict(cv.GAME_ORIGINALS).get(key, key)
    scene.pd_sky_custom = True
    sync_world(scene)
    sync_sphere(scene)


class PDSTAGE_OT_sky_preset(bpy.types.Operator):
    """Start from a game map's sky: its dome colours, cloud textures and cloud speeds"""
    bl_idname = 'pdstage.sky_preset'
    bl_label = 'Sky Preset'
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = 'map'

    map: EnumProperty(name='Map', items=[(k, '%s (%s)' % (n, k), 'Start from %s\'s sky' % n)
                                         for k, n in cv.GAME_ORIGINALS])

    def execute(self, context):
        try:
            apply_preset(context, self.map)
        except (RuntimeError, OSError, ValueError) as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        if _sphere_object() is None:
            try:
                build_preview(context)
            except (RuntimeError, OSError, ValueError):
                pass
        return {'FINISHED'}


def setup_new(context):
    """New Map Setup: a custom sky started from the replaced map's own, and the preview sphere. Returns an error
    text or ''."""
    scene = context.scene
    scene.pd_sky_custom = True
    err = ''
    try:
        apply_preset(context, scene.pd_game_original)
    except (RuntimeError, OSError, ValueError) as e:
        err = str(e)
    try:
        build_preview(context)
    except (RuntimeError, OSError, ValueError) as e:
        err = err or str(e)
    sync_world(scene)
    return err


# ---------------------------------------------------------------- panel

def draw_sky(layout, scene):
    lay = layout
    if not scene.pd_sky_custom:
        lay.label(text='The replaced map keeps its own sky', icon='INFO')
        lay.operator('pdstage.sky_preview', text='Add Custom Sky', icon='ADD')
        return
    lay.operator_menu_enum(PDSTAGE_OT_sky_preset.bl_idname, 'map', icon='PRESET',
                           text='Preset: %s' % scene.pd_sky_preset if scene.pd_sky_preset else 'Presets')
    box = lay.box()
    box.label(text='Dome', icon='WORLD')
    col = box.column(align=True)
    for prop, _e in STOPS:
        col.prop(scene, prop)
    box = lay.box()
    box.label(text='Clouds', icon='OUTLINER_DATA_VOLUME')
    for name, tex, speed in zip(LAYER_NAMES, TEX_PROPS, SPEED_PROPS):
        col = box.column(align=True)
        col.label(text=name)
        col.template_ID(scene, tex, open='image.open')
        col.prop(scene, speed, text='Speed')
    box.label(text='Speed 0 = still, the sign = direction', icon='INFO')
    box = lay.box()
    box.label(text='Sun glow: follows the scene\'s Sun' if getattr(scene, 'pd_sun', None) is not None
              else 'Sun glow: where the replaced map has it (no scene Sun)', icon='LIGHT_SUN')
    row = lay.row(align=True)
    row.operator('pdstage.sky_preview', text='Rebuild Sky Sphere', icon='FILE_REFRESH')
    row.operator('pdstage.sky_preview_clear', text='', icon='X')
    lay.label(text='Exported into the map. Press Play to see the clouds move', icon='PLAY')


class PDSTAGE_PT_sky(bpy.types.Panel):
    bl_label = 'Phantom Dust Sky'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'scene'

    def draw(self, context):
        draw_sky(self.layout, context.scene)


classes = (PDSTAGE_OT_sky_preset, PDSTAGE_PT_sky)

SCENE_PROPS = ('pd_sky_custom', 'pd_sky_preset', 'pd_sky_top', 'pd_sky_upper', 'pd_sky_horizon', 'pd_sky_bottom') \
    + SPEED_PROPS + TEX_PROPS


def _colour(name, default, desc):
    return FloatVectorProperty(name=name, subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0, default=default,
                               description=desc, update=_update)


def _speed(name, default, desc):
    return IntVectorProperty(name=name, size=2, default=default, min=-32768, max=32767, soft_min=-600, soft_max=600,
                             description=desc + ' (X, Y). 0 = still, the sign = direction; the game uses about '
                                                '-300 to 300 (much more wraps)')


def register_props():
    S = bpy.types.Scene
    S.pd_sky_custom = BoolProperty(
        name='Custom sky', default=False, update=_update,
        description='Build the sky from these settings (off: the replaced map\'s own sky stays)')
    S.pd_sky_preset = StringProperty(name='Preset', default='', description='The last preset applied')
    S.pd_sky_top = _colour('Top', (0.16, 0.27, 0.55), 'Colour straight up')
    S.pd_sky_upper = _colour('Upper sky', (0.36, 0.55, 0.85), 'Colour about a third of the way up')
    S.pd_sky_horizon = _colour('Horizon', (0.86, 0.76, 0.62), 'Colour at the horizon')
    S.pd_sky_bottom = _colour('Bottom', (0.22, 0.22, 0.25), 'Colour straight down (seen from high places)')
    S.pd_cloud_speed_colour = _speed('Clouds', (150, -75), 'Scroll speed of the cloud picture')
    S.pd_cloud_speed_shape_a = _speed('Shape A', (200, -100), 'Scroll speed of the first shape layer that cuts the '
                                                             'clouds\' outline')
    S.pd_cloud_speed_shape_b = _speed('Shape B', (90, 0), 'Scroll speed of the second shape layer')
    S.pd_cloud_texture = PointerProperty(
        name='Cloud texture', type=bpy.types.Image, update=_update,
        description='The cloud picture (colour; alpha = where clouds are). Empty: the replaced map\'s own')
    S.pd_cloud_texture_shape_a = PointerProperty(
        name='Shape A texture', type=bpy.types.Image, update=_update,
        description='First shape layer (its alpha cuts the clouds). Empty: the replaced map\'s own')
    S.pd_cloud_texture_shape_b = PointerProperty(
        name='Shape B texture', type=bpy.types.Image, update=_update,
        description='Second shape layer (its alpha cuts the clouds). Empty: the replaced map\'s own')


def unregister_props():
    for p in SCENE_PROPS:
        if hasattr(bpy.types.Scene, p):
            try:
                delattr(bpy.types.Scene, p)
            except (AttributeError, RuntimeError):
                pass


# ---------------------------------------------------------------- 3D preview of the sky layers

PREVIEW = 'PD Sky Preview'
# Cloud scroll in the preview: speed value / 65536 texture widths per game frame at 60 fps (an estimate: it gives
# the game originals' clouds their slow drift; not yet measured against the game)
SCROLL_DIV = 65536.0
GAME_FPS = 60.0


def _preview_collection(scene):
    coll = bpy.data.collections.get(PREVIEW)
    if coll is None:
        coll = bpy.data.collections.new(PREVIEW)
    if coll.name not in scene.collection.children:
        scene.collection.children.link(coll)
    coll.pd_role = 'NONE'
    coll.hide_render = True                     # never part of a bake or render: a viewport preview only
    return coll


def _clear_preview():
    coll = bpy.data.collections.get(PREVIEW)
    if coll is None:
        return
    for ob in list(coll.objects):
        me = ob.data
        bpy.data.objects.remove(ob)
        if me is not None and me.users == 0:
            bpy.data.meshes.remove(me)


def _speed_driver(node_socket, index, base, scene, axis_sign):
    """Drive a Mapping node location channel: offset = speed * frame * 60 / (65536 * fps), the speed following the
    layer's Speed setting live (the replaced map's own speed while Custom sky is off)."""
    fc = node_socket.driver_add('default_value', index)
    d = fc.driver
    d.type = 'SCRIPTED'
    for name, path in (('c', 'pd_sky_custom'), ('fps', 'render.fps'),
                       ('av', '%s[%d]' % (SPEED_PROPS[base[0]], base[1]))):
        v = d.variables.new()
        v.name = name
        v.type = 'SINGLE_PROP'
        v.targets[0].id_type = 'SCENE'
        v.targets[0].id = scene
        v.targets[0].data_path = path
    d.expression = '%s(av if c else %d) * frame * %g / (%g * fps)' % (
        '-' if axis_sign < 0 else '', base[2], GAME_FPS, SCROLL_DIV)


def _flat_material(name, img, additive):
    """Unlit material for the sun / glow layer: the picture (or the vertex colours) added on top like the game's
    glow when additive, else opaque."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    try:
        mat.surface_render_method = 'BLENDED' if additive else 'DITHERED'
    except (AttributeError, TypeError):
        pass
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    emit = nt.nodes.new('ShaderNodeEmission')
    if img is not None:
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = img
        nt.links.new(tex.outputs['Color'], emit.inputs['Color'])
    else:
        col = nt.nodes.new('ShaderNodeVertexColor')
        col.layer_name = 'PD_Col'
        nt.links.new(col.outputs['Color'], emit.inputs['Color'])
    if additive:
        add = nt.nodes.new('ShaderNodeAddShader')
        clear = nt.nodes.new('ShaderNodeBsdfTransparent')
        nt.links.new(clear.outputs[0], add.inputs[0])
        nt.links.new(emit.outputs[0], add.inputs[1])
        nt.links.new(add.outputs[0], out.inputs['Surface'])
    else:
        nt.links.new(emit.outputs[0], out.inputs['Surface'])
    return mat


def _layer_mesh(name, layer, scale):
    from . import convert as cv
    me = bpy.data.meshes.new(name)
    me.from_pydata([cv.to_blender(p, scale) for p in layer['pos']], [], [cv.flip_winding(t) for t in layer['tris']])
    uvl = me.uv_layers.new(name='UVMap')
    col = me.color_attributes.new('PD_Col', 'BYTE_COLOR', 'POINT')
    for i, c in enumerate(layer['col']):
        col.data[i].color_srgb = tuple(x / 255 for x in c)
    for li, loop in enumerate(me.loops):
        u, v = layer['uv'][loop.vertex_index]
        uvl.data[li].uv = (u, 1.0 - v)
    me.update()
    return me


HORIZON_K = 0.3            # cloud projection: horizontal direction / (height + K), like a cloud plane overhead
SPHERE_KIND = 'sky'


def _solve3(m, r):
    """Solve the 3x3 system m x = r (Cramer); None if singular."""
    def det(a):
        return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
                + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    d = det(m)
    if abs(d) < 1e-12:
        return None
    out = []
    for c in range(3):
        a = [row[:] for row in m]
        for i in range(3):
            a[i][c] = r[i]
        out.append(det(a) / d)
    return out


def _directions(layer):
    """Unit directions of a layer's vertices, in Blender axes (x, y, z up)."""
    out = []
    for gx, gy, gz in layer['pos']:
        bx, by, bz = gx, gz, gy                                 # game -> Blender axes (convert.py)
        n = (bx * bx + by * by + bz * bz) ** 0.5 or 1.0
        out.append((bx / n, by / n, bz / n))
    return out


def _fit_uv(layer):
    """Fit the game original's cloud UVs as u, v = a . (px, py, 1) with p = (x, y) / (z + K): the same projection the
    sphere shader uses, so the clouds keep the game's tiling and direction. Returns ((a0, a1, a2), (b0, b1, b2))."""
    rows, us, vs = [], [], []
    for (x, y, z), (u, v) in zip(_directions(layer), layer['uv']):
        if z <= 0.02:
            continue
        q = 1.0 / (z + HORIZON_K)
        rows.append((x * q, y * q, 1.0))
        us.append(u)
        vs.append(1.0 - v)                      # Blender V runs upwards
    if len(rows) < 3:
        return (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    m = [[sum(r[i] * r[j] for r in rows) for j in range(3)] for i in range(3)]
    fit = []
    for vals in (us, vs):
        rhs = [sum(r[i] * t for r, t in zip(rows, vals)) for i in range(3)]
        fit.append(tuple(_solve3(m, rhs) or (1.0, 0.0, 0.0)))
    return fit[0], fit[1]


def _alpha_profile(layer, bins=12):
    """The cloud mesh's vertex alpha (its fade toward the horizon) by height: [(ramp position 0..1, alpha 0..1)]."""
    pts = [(0.5 + 0.5 * d[2], c[3] / 255.0) for d, c in zip(_directions(layer), layer['col'])]
    if not pts:
        return [(0.0, 0.0), (1.0, 1.0)]
    lo, hi = min(p for p, _a in pts), max(p for p, _a in pts)
    step = (hi - lo) / bins or 1.0
    out = [(max(0.0, lo - 0.01), 0.0)]
    for k in range(bins):
        sel = [a for p, a in pts if lo + k * step <= p <= lo + (k + 1) * step]
        if sel:
            out.append((min(1.0, lo + (k + 0.5) * step), sum(sel) / len(sel)))
    if hi < 0.995:
        out.append((min(1.0, hi + 0.01), out[-1][1]))
    return out


def _set_ramp(ramp, stops):
    """stops: [(position, (r, g, b, a))] sorted by position."""
    els = ramp.color_ramp.elements
    while len(els) > len(stops):
        els.remove(els[-1])
    while len(els) < len(stops):
        els.new(1.0)
    for el, (pos, col) in zip(els, stops):
        el.position = pos
        el.color = col


def _sphere_material(name, clouds, scene):
    """One opaque, unlit material: the dome gradient (ramp by height) with the cloud layers mixed over it.
    clouds: [dict(images, speeds, fit, profile, light)]. Live: colours / texture / on-off follow the settings
    (sync_sphere), speeds follow drivers."""
    from .pd_material import sock
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    L = nt.links

    def node(kind, x, y, **kw):
        n = nt.nodes.new(kind)
        n.location = (x, y)
        for k, v in kw.items():
            setattr(n, k, v)
        return n

    def math_(op, a, b, x, y, c=None):
        n = node('ShaderNodeMath', x, y, operation=op)
        for i, s in enumerate((a, b, c)):
            if s is None:
                continue
            if isinstance(s, (int, float)):
                n.inputs[i].default_value = s
            else:
                L.new(s, n.inputs[i])
        return n.outputs[0]

    out = node('ShaderNodeOutputMaterial', 1800, 0)
    tc = node('ShaderNodeTexCoord', -2200, 0)
    nrm = node('ShaderNodeVectorMath', -2000, 0, operation='NORMALIZE')
    L.new(tc.outputs['Object'], nrm.inputs[0])
    sep = node('ShaderNodeSeparateXYZ', -1800, 0)
    L.new(nrm.outputs[0], sep.inputs[0])
    height = math_('MULTIPLY_ADD', sep.outputs['Z'], 0.5, -1600, 200, 0.5)     # 0 straight down .. 1 straight up
    dome = node('ShaderNodeVertexColor', -1400, 300, name='pd_sky_colours', label='Dome colours (PD_Dome)')
    dome.layer_name = DOME_LAYER                       # painted per vertex like the game (sync_sphere)
    colour = dome.outputs['Color']

    # cloud projection (shared by every layer): p = (x, y) / (z + K)
    q = math_('DIVIDE', 1.0, math_('MAXIMUM', math_('ADD', sep.outputs['Z'], HORIZON_K, -1600, -200), 0.02,
                                    -1450, -200), -1300, -200)
    pxy = node('ShaderNodeCombineXYZ', -1100, -200)
    L.new(math_('MULTIPLY', sep.outputs['X'], q, -1300, -350), pxy.inputs['X'])
    L.new(math_('MULTIPLY', sep.outputs['Y'], q, -1300, -450), pxy.inputs['Y'])
    pxy.inputs['Z'].default_value = 1.0

    y0 = -300
    for c, cloud in enumerate(clouds):
        yb = y0 - 1100 * c
        (a0, a1, a2), (b0, b1, b2) = cloud['fit']
        uv = node('ShaderNodeCombineXYZ', -700, yb)
        for axis, coef in (('X', (a0, a1, a2)), ('Y', (b0, b1, b2))):
            dot = node('ShaderNodeVectorMath', -900, yb + (0 if axis == 'X' else -150), operation='DOT_PRODUCT')
            L.new(pxy.outputs[0], dot.inputs[0])
            dot.inputs[1].default_value = coef
            L.new(dot.outputs['Value'], uv.inputs[axis])
        samples = []
        for k, img in enumerate(cloud['images']):
            mp = node('ShaderNodeMapping', -450, yb - 300 * k)
            L.new(uv.outputs[0], mp.inputs['Vector'])
            _speed_driver(mp.inputs['Location'], 0, (k, 0, cloud['speeds'][2 * k]), scene, +1)
            _speed_driver(mp.inputs['Location'], 1, (k, 1, cloud['speeds'][2 * k + 1]), scene, -1)
            tex = node('ShaderNodeTexImage', -200, yb - 300 * k, image=img)
            tex.name = 'pd_cloud_tex_%d_%d' % (c, k)
            tex.label = img.name if img else ''
            L.new(mp.outputs['Vector'], tex.inputs['Vector'])
            samples.append(tex)
        mask = node('ShaderNodeValToRGB', -200, yb + 300, name='pd_cloud_mask_%d' % c, label='Cloud fade by height')
        L.new(height, mask.inputs['Fac'])
        _set_ramp(mask, [(p, (a, a, a, 1.0)) for p, a in cloud['profile']])
        alpha = math_('MULTIPLY', samples[0].outputs['Alpha'], mask.outputs['Color'], 100, yb + 100)
        for k, s in enumerate(samples[1:]):
            alpha = math_('MULTIPLY', alpha, s.outputs['Alpha'], 250 + 150 * k, yb + 100)
        light = node('ShaderNodeRGB', 100, yb - 150, name='pd_cloud_light', label='Cloud light')
        light.outputs[0].default_value = cloud['light']
        tint = node('ShaderNodeMix', 350, yb - 100, data_type='RGBA', blend_type='MULTIPLY')
        sock(tint.inputs, 'Factor_Float').default_value = 1.0
        L.new(samples[0].outputs['Color'], sock(tint.inputs, 'A_Color'))
        L.new(light.outputs[0], sock(tint.inputs, 'B_Color'))
        over = node('ShaderNodeMix', 800, yb, data_type='RGBA', blend_type='MIX')
        L.new(alpha, sock(over.inputs, 'Factor_Float'))
        L.new(colour, sock(over.inputs, 'A_Color'))
        L.new(sock(tint.outputs, 'Result_Color'), sock(over.inputs, 'B_Color'))
        colour = sock(over.outputs, 'Result_Color')
    emit = node('ShaderNodeEmission', 1500, 0)
    L.new(colour, emit.inputs['Color'])
    L.new(emit.outputs[0], out.inputs['Surface'])
    return mat


DOME_LAYER = 'PD_Dome'


def _dome_mesh(name, layers, scale):
    """The dome the export writes: the replaced map's own dome mesh (its uneven triangles give the game's look),
    or, for maps whose dome is a picture, the sphere the export makes instead. Faces point inwards."""
    import struct
    verts, faces = [], []
    gradient = [l for l in layers if l['kind'] == 'dome' and l.get('shader') in ('svc', 'svcal')]
    if gradient:
        for l in gradient:
            base = len(verts)
            verts += [cv.to_blender(p, scale) for p in l['pos']]
            faces += [cv.flip_winding(tuple(base + i for i in t[:3])) for t in l['tris']]
    else:
        raw = sky_build.dome_mesh([(90.0, (0, 0, 0)), (-90.0, (0, 0, 0))])['raw']
        size = raw['vertex_size']
        data = raw['vertex_bytes']
        verts = [cv.to_blender(struct.unpack_from('<3f', data, k * size), scale) for k in range(len(data) // size)]
        faces = [cv.flip_winding(tuple(t)) for t in raw['tris'][::2]]          # one side of each pair
    seen, unique = set(), []
    for f in faces:                                   # double-sided domes list each triangle twice
        if len(set(f)) == 3 and frozenset(f) not in seen:
            seen.add(frozenset(f))
            unique.append(f)
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], unique)
    me.color_attributes.new(DOME_LAYER, 'BYTE_COLOR', 'POINT')
    me.validate()
    me.update()
    return me


def _sphere_object():
    coll = bpy.data.collections.get(PREVIEW)
    if coll is None:
        return None
    return next((o for o in coll.objects if o.get('pd_sky_kind') == SPHERE_KIND), None)


def sync_sphere(scene):
    """Push the Dome / Clouds settings into the sphere's shader (no rebuild needed)."""
    ob = _sphere_object()
    if ob is None or not ob.data.materials or ob.data.materials[0] is None:
        return
    nt = ob.data.materials[0].node_tree
    layer = ob.data.color_attributes.get(DOME_LAYER)
    if layer is not None:
        # the gradient painted on the dome's vertices by height, exactly as the export paints the game's dome
        if scene.pd_sky_custom:
            stops = dome_stops(scene)
        else:
            stops = [(e, tuple(c)) for (_p, e), c in zip(STOPS, ob.get('pd_game_dome', [(128, 150, 200)] * 4))]
        out = []
        for v in ob.data.vertices:
            x, y, z = v.co
            r = math.sqrt(x * x + y * y + z * z) or 1.0
            c = sky_build._gradient(stops, math.degrees(math.asin(max(-1.0, min(1.0, z / r)))))
            out += [min(1.0, c[0] / 255), min(1.0, c[1] / 255), min(1.0, c[2] / 255), 1.0]
        layer.data.foreach_set('color_srgb', out)
        ob.data.update()
    for n in nt.nodes:
        if n.name.startswith('pd_cloud_tex_'):
            k = int(n.name.rsplit('_', 1)[1])
            img = getattr(scene, TEX_PROPS[k]) if scene.pd_sky_custom and k < len(TEX_PROPS) else None
            n.image = img or bpy.data.images.get(n.label) or n.image


def build_preview(context):
    """(Re)build the sky preview: one sphere with the dome gradient and the game original's scrolling cloud layers in
    one shader, plus the sun / glow layer. Returns a short report."""
    import tempfile
    from . import exporter
    from . import visuals
    from ._lib import alr
    scene = context.scene
    data = _game_data(context)
    path = exporter.game_original_alr(data, scene.pd_game_original) if data else ''
    if path and os.path.isfile(path):
        b = open(path, 'rb').read()
        texs = alr.textures(b)
        layers = sky_build.preview_layers(b)
        info = sky_build.read_sky(b)
    else:                                                # no game data: the gradient alone
        b, texs, layers, info = b'', [], [], dict(dome_colours=[])
    _clear_preview()
    coll = _preview_collection(scene)
    s = scene.pd_scale
    c, a = scene.pd_stage_light, scene.pd_stage_ambient
    light = tuple(_linear(min(1.0, c[k] + a[k])) for k in range(3)) + (1.0,)
    cache, clouds, made = {}, [], []
    radius = 0.0
    with tempfile.TemporaryDirectory() as tmp:
        def image(i):
            return visuals._image(b, texs[i], cache, tmp) if i is not None and i < len(texs) else None
        for n, layer in enumerate(layers):
            if layer['kind'] == 'dome':
                continue
            for p in layer['pos']:
                radius = max(radius, (p[0] * p[0] + p[1] * p[1] + p[2] * p[2]) ** 0.5 * s)
            if layer['kind'] == 'clouds':
                imgs = [image(t) for t in layer['textures'][:3]]
                imgs = [i for i in imgs if i is not None]
                if imgs:
                    clouds.append(dict(images=imgs, speeds=layer['speeds'], fit=_fit_uv(layer),
                                       profile=_alpha_profile(layer), light=light))
                    made.append('clouds')
            elif layer['kind'] == 'sun':
                name = 'PD Sky Sun Glow'                 # the map's sun glow, turned to the scene's Sun
                me = _layer_mesh(name, layer, s)
                me.materials.append(_flat_material(name, image(layer['textures'][0]), True))
                ob = bpy.data.objects.new(name, me)
                ob['pd_sky_kind'] = 'sun'
                ob.hide_select = True
                coll.objects.link(ob)
                _follow_sun(ob, scene)
                made.append('sun')
    name = 'PD Sky Dome'
    me = _dome_mesh(name, layers, s)
    me.materials.append(_sphere_material(name, clouds, scene))
    ob = bpy.data.objects.new(name, me)
    ob['pd_sky_kind'] = SPHERE_KIND
    ob['pd_game_dome'] = [list(x) for x in sky_build.dome_colours_at(info['dome_colours'])] \
        if info['dome_colours'] else [[128, 150, 200]] * 4
    ob.hide_select = True
    try:
        ob.visible_shadow = False
    except AttributeError:
        pass
    coll.objects.link(ob)
    made.insert(0, 'dome')
    scene.pd_sky_custom = True                           # the sphere is the custom sky: exported with the map
    sync_sphere(scene)
    _far_clip()
    if scene.frame_end < 100000:
        scene.frame_end = 100000                         # long playback so the clouds keep scrolling
    return '%s: %s' % (scene.pd_game_original, ', '.join(made) if b else 'gradient only (no game data folder set)')


def _far_clip(distance=5000.0):
    """Push Clip End out in every 3D view of every workspace: the sky is about 1.2 km away, past Blender's
    default 1 km (the setting lives in the N sidebar > View tab > Clip End)."""
    for screen in bpy.data.screens:
        for area in screen.areas:
            for sp in area.spaces:
                if sp.type == 'VIEW_3D' and sp.clip_end < distance:
                    sp.clip_end = distance


def _follow_sun(ob, scene):
    """Turn the sun glow so it sits straight up its object's +Z, then copy the scene Sun's rotation: the glow
    follows the Sun live (a light shines down its -Z, so the sun itself is up its +Z), as the export does."""
    sun = getattr(scene, 'pd_sun', None)
    if sun is None or sun.type != 'LIGHT':
        return
    me = ob.data
    pts = sky_build.rotate_towards([tuple(v.co) for v in me.vertices], (0.0, 0.0, 1.0))
    for v, p in zip(me.vertices, pts):
        v.co = p
    me.update()
    con = ob.constraints.new('COPY_ROTATION')
    con.target = sun


class PDSTAGE_OT_sky_preview(bpy.types.Operator):
    """Build the custom sky sphere (collection "PD Sky Preview"): the gradient with the clouds scrolling over it.
    Its settings are exported into the map's sky. Press Play to see the clouds move"""
    bl_idname = 'pdstage.sky_preview'
    bl_label = 'Build Sky Sphere'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        if not scene.pd_sky_custom and scene.pd_cloud_texture is None:
            try:                                         # first time: start from the replaced map's own sky
                apply_preset(context, scene.pd_game_original)
            except (RuntimeError, OSError, ValueError):
                pass
        try:
            msg = build_preview(context)
        except (RuntimeError, OSError, ValueError) as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, 'Sky preview: %s (press Play to see the clouds move)' % msg)
        return {'FINISHED'}


class PDSTAGE_OT_sky_preview_clear(bpy.types.Operator):
    """Remove the custom sky: the sphere goes and the exported map keeps the replaced map's own sky"""
    bl_idname = 'pdstage.sky_preview_clear'
    bl_label = 'Remove Sky Preview'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _clear_preview()
        coll = bpy.data.collections.get(PREVIEW)
        if coll is not None:
            bpy.data.collections.remove(coll)
        context.scene.pd_sky_custom = False             # no sky sphere: the replaced map keeps its own sky
        sync_world(context.scene)
        return {'FINISHED'}


classes = classes + (PDSTAGE_OT_sky_preview, PDSTAGE_OT_sky_preview_clear)
