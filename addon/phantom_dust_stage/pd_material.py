"""The PD Stage Shader: a node group with exactly the settings Phantom Dust's stage shaders have.

Read from the game's own compiled shaders (SD/SBTS/SDREFS/SBTSREFS *.cso) and the material entries of every
map (see FORMATS.md, "Stage materials"):
  Diffuse          texture slot 0, multiplied by the lighting
  Normal Map       tangent-space map (switches the surface to the game's bump shader sbts); its alpha also
                   masks the highlight
  Normal Strength  the game has no strength setting: the exporter rescales the normal map's pixels instead
  Reflection Map   sphere map added on top (shader *refs), scaled by its alpha, the Shine Mask and the light
  Specular Color   colour of the sun's shine (black = none)
  Shininess        specular power: which face angles shine (the game's shine is per vertex)
  Shine Mask       where the shine / reflection show (stored as the vertex colour's alpha)
  Reflection Strength  stored in the reflection map's alpha
  Baked Light      vertex colour the game multiplies the lit texture by
The stage shaders have no roughness, metalness or emission inputs.

Game Preview (Scene.pd_game_preview, on by default): the group shows what the game draws, worked out like the
game's shader (SD_vs/SD_ps): saturate(texture * baked light * (sun colour * N.L + ambient)), plus
specular colour * (N.H)^shininess * shine mask * (1 - N.V), with H and V fixed per frame (the game uses one
half-vector and one eye vector, so a flat face shines evenly), in the game's gamma space. The sun direction and
colours come from the scene (Sun object and Phantom Dust Lighting), synced by a timer. Off: Blender's own
lighting (Principled BSDF), which Bake Lighting needs.
"""
import math

import bpy
from mathutils import Vector

GROUP = 'PD Stage Shader'
SPHERE_GROUP = 'PD Sphere Map'
GROUP_VERSION = 13
LIGHT_LAYER = 'PD_Light'
SHINE_LAYER = 'PD_Shine'
MAPS = ('Diffuse', 'Normal Map', 'Reflection Map', 'Emission Map')
GAMMA = 2.2

# (panel, name, socket type, default, min, max, description)
SOCKETS = (
    ('Maps', 'Diffuse', 'NodeSocketColor', (0.3, 0.3, 0.3, 1.0), None, None,
     'Base texture. Link an Image Texture node (the exporter writes its image), or set a colour'),
    ('Maps', 'Diffuse Color', 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0), None, None,
     'Multiplies the diffuse texture (white = the texture as it is). The export bakes it into the texture'),
    ('Maps', 'Normal Map', 'NodeSocketColor', (0.5, 0.5, 1.0, 1.0), None, None,
     'Tangent-space normal map, OpenGL style (green = up), like Blender\'s Normal Map node. Linking an image '
     'switches the surface to the game\'s bump shader. Set the image to Non-Color. Its alpha also masks the '
     'shine'),
    ('Maps', 'Normal Strength', 'NodeSocketFloat', 1.0, 0.0, 4.0,
     'How strong the bumps look. The game has no such setting, so the exporter rescales the normal map\'s '
     'pixels (1 = the image as painted)'),
    ('Maps', 'Reflection Map', 'NodeSocketColor', (0.0, 0.0, 0.0, 1.0), None, None,
     'Sphere map reflected on the surface (game shaders sdrefs / sbtsrefs). Link an Image Texture node'),
    ('Maps', 'Emission Map', 'NodeSocketColor', (0.0, 0.0, 0.0, 1.0), None, None,
     'Glow: where and in what colour the surface lights up by itself (black = none). Link an Image Texture '
     'node or set a colour. In game it needs Bake Lighting: it is stored in the light map (whose alpha the '
     'game adds as glow), and it also lights the surfaces around it in the bake'),
    ('Maps', 'Emission Color', 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0), None, None,
     'Multiplies the emission map (white = the map as it is)'),
    ('Maps', 'Emission Strength', 'NodeSocketFloat', 1.0, 0.0, 10.0,
     'How bright the glow is (the game shows up to full white)'),
    ('Highlight', 'Specular Color', 'NodeSocketColor', (0.0, 0.0, 0.0, 1.0), None, None,
     'Colour and strength of the sun\'s shine. Black = none, like most of the game\'s own surfaces. The game '
     'uses dark to mid grey (about 0.1-0.5): full colours are very strong. In game the shine fills whole faces '
     'evenly (it is worked out per vertex), so curved or bevelled shapes show it best'),
    ('Highlight', 'Shininess', 'NodeSocketFloat', 20.0, 1.0, 127.0,
     'How exactly a face must face the sun\'s reflection to shine (the game\'s specular power): low = most '
     'sunlit faces glow, high = only faces at the right angle. Not a spot size: a face shines evenly. '
     'The game uses 2-80'),
    ('Highlight', 'Shine Mask', 'NodeSocketFloat', 1.0, 0.0, 1.0,
     'Where the shine and reflection show: a value for the whole material, or link a Color Attribute '
     '(Paint Shine Mask) to paint it. Stored as the vertex colour\'s alpha'),
    ('Highlight', 'Reflection Strength', 'NodeSocketFloat', 1.0, 0.0, 1.0,
     'How strongly the reflection map shows (stored in the reflection map\'s alpha)'),
    ('Lighting', 'Baked Light', 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0), None, None,
     'Light baked into the vertex colours, multiplied with the texture in game. Link the PD_Light colour '
     'attribute (Bake Lighting fills it). Normal-mapped surfaces use only its red channel, as shade'),
    ('Lighting', 'Light Map', 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0), None, None,
     'Lighting from Bake Lighting (sun, lamps, bounces, shadows; the stage ambient is added on top, as in game), '
     'on the PD_LightUV map. Show Baked Lighting links it'),
    ('Lighting', 'Light Map Amount', 'NodeSocketFloat', 0.0, 0.0, 1.0,
     '1 = show the texture lit by the Light Map and the stage ambient, as the game draws a light-mapped surface'),
)
FACTOR = ('Shine Mask', 'Reflection Strength', 'Light Map Amount')
# hidden nodes inside the group that the add-on keeps in step with the scene (see sync_preview)
SUN_DIR, VIEW_DIR, SUN_COL, AMB_COL, PREVIEW = 'pd_sun_dir', 'pd_view_dir', 'pd_sun_col', 'pd_ambient_col', 'pd_preview'


# ---------------------------------------------------------------- the node group

def sock(sockets, identifier):
    """A node socket by identifier (the Mix node has several sockets named A, B, Factor, Result)."""
    return next(x for x in sockets if x.identifier == identifier)


def _interface(ng):
    """Create the group's sockets, or add the ones an older version lacks (links into existing ones stay)."""
    iface = ng.interface
    have = {i.name: i for i in iface.items_tree}
    added = []
    if not any(getattr(i, 'in_out', None) == 'OUTPUT' for i in iface.items_tree):
        iface.new_socket('Shader', in_out='OUTPUT', socket_type='NodeSocketShader')
    panels = {i.name: i for i in iface.items_tree if i.item_type == 'PANEL'}
    for k, (panel, name, stype, default, lo, hi, desc) in enumerate(SOCKETS):
        if panel not in panels:
            panels[panel] = iface.new_panel(panel)
        s = have.get(name)
        if s is None or getattr(s, 'item_type', '') != 'SOCKET':
            s = iface.new_socket(name, in_out='INPUT', socket_type=stype, parent=panels[panel])
            s.default_value = default
            added.append((name, default))
            pos = [x[1] for x in SOCKETS if x[0] == panel].index(name)
            try:
                iface.move_to_parent(s, panels[panel], pos)
            except (AttributeError, TypeError, RuntimeError):
                pass
        s.description = desc
        if lo is not None:
            s.min_value, s.max_value = lo, hi
        if name in FACTOR:
            try:
                s.subtype = 'FACTOR'              # slider display; cosmetic
            except (AttributeError, TypeError):
                pass
    return added


def _contents(ng):
    """(Re)build the group's insides: Blender look and game look, picked by the pd_preview value."""
    ng.nodes.clear()
    nodes, links = ng.nodes, ng.links
    gi = nodes.new('NodeGroupInput')
    gi.location = (-1600, 0)
    go = nodes.new('NodeGroupOutput')
    go.location = (1000, 0)

    def node(kind, loc, name=None, **props):
        n = nodes.new(kind)
        n.location = loc
        if name:
            n.name = n.label = name
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def plug(sockt, v):
        if isinstance(v, (int, float)):
            sockt.default_value = v
        elif isinstance(v, tuple):
            sockt.default_value = v
        else:
            links.new(v, sockt)

    def math_(op, a, b=None, loc=(0, 0), clamp=False):
        n = node('ShaderNodeMath', loc, operation=op, use_clamp=clamp)
        plug(n.inputs[0], a)
        if b is not None:
            plug(n.inputs[1], b)
        return n.outputs[0]

    def vmath(op, a, b=None, loc=(0, 0), out=0):
        n = node('ShaderNodeVectorMath', loc, operation=op)
        plug(n.inputs[0], a)
        if b is not None:
            plug(n.inputs[1], b)
        return n.outputs[out]

    def mix(a, b, op='MIX', fac=1.0, loc=(0, 0), clamp=False):
        n = node('ShaderNodeMix', loc, data_type='RGBA', blend_type=op, clamp_result=clamp)
        plug(sock(n.inputs, 'Factor_Float'), fac)
        plug(sock(n.inputs, 'A_Color'), a)
        plug(sock(n.inputs, 'B_Color'), b)
        return sock(n.outputs, 'Result_Color')

    def gamma(c, g, loc):
        n = node('ShaderNodeGamma', loc)
        plug(n.inputs['Color'], c)
        n.inputs['Gamma'].default_value = g
        return n.outputs['Color']

    # values the add-on keeps in step with the scene
    diffuse = mix(gi.outputs['Diffuse'], gi.outputs['Diffuse Color'], 'MULTIPLY', loc=(-1800, 300))
    glow_col = mix(gi.outputs['Emission Map'], gi.outputs['Emission Color'], 'MULTIPLY', loc=(-1800, -300))
    sun_dir = node('ShaderNodeCombineXYZ', (-1600, -700), SUN_DIR)
    sun_dir.inputs[0].default_value, sun_dir.inputs[1].default_value, sun_dir.inputs[2].default_value = 0.3, -0.4, 0.87
    view_dir = node('ShaderNodeCombineXYZ', (-1600, -850), VIEW_DIR)
    view_dir.inputs[2].default_value = 1.0
    sun_col = node('ShaderNodeRGB', (-1600, -1000), SUN_COL)
    sun_col.outputs[0].default_value = (0.706, 0.686, 0.608, 1.0)
    amb_col = node('ShaderNodeRGB', (-1600, -1200), AMB_COL)
    amb_col.outputs[0].default_value = (0.424, 0.392, 0.373, 1.0)
    preview = node('ShaderNodeValue', (-1600, -1400), PREVIEW)
    preview.outputs[0].default_value = 1.0

    # ---- Blender look (Principled): what Bake Lighting and Cycles renders use
    bsdf = node('ShaderNodeBsdfPrincipled', (400, 400))
    lp = node('ShaderNodeLightPath', (-200, 750))
    base = diffuse                                               # Blender's lights do the lighting
    links.new(base, bsdf.inputs['Base Color'])
    links.new(glow_col, bsdf.inputs['Emission Color'])       # Blender's look: a real glow
    links.new(gi.outputs['Emission Strength'], bsdf.inputs['Emission Strength'])
    nmap = node('ShaderNodeNormalMap', (-1200, -300))
    links.new(gi.outputs['Normal Map'], nmap.inputs['Color'])
    links.new(gi.outputs['Normal Strength'], nmap.inputs['Strength'])
    links.new(nmap.outputs['Normal'], bsdf.inputs['Normal'])
    sep = node('ShaderNodeSeparateColor', (-1200, 300))
    links.new(gi.outputs['Specular Color'], sep.inputs['Color'])
    peak = math_('MAXIMUM', math_('MAXIMUM', sep.outputs[0], sep.outputs[1], loc=(-1000, 300)), sep.outputs[2], loc=(-850, 300))
    links.new(math_('ADD', math_('MULTIPLY', math_('MULTIPLY', peak, gi.outputs['Shine Mask'], loc=(-700, 300)), 1.5,
                                 loc=(-550, 300)), 0.5, loc=(-450, 300)),
              bsdf.inputs['Specular IOR Level'])                 # Blender's default 0.5, more with a highlight
    links.new(gi.outputs['Specular Color'], bsdf.inputs['Specular Tint'])
    rough = math_('POWER', math_('DIVIDE', 2.0, math_('ADD', gi.outputs['Shininess'], 2.0, loc=(-1000, 150)),
                                 loc=(-850, 150)), 0.5, loc=(-700, 150))
    links.new(rough, bsdf.inputs['Roughness'])
    rsep = node('ShaderNodeSeparateColor', (-1200, 0))           # a coat only where there is a reflection map
    links.new(gi.outputs['Reflection Map'], rsep.inputs['Color'])
    rpeak = math_('MAXIMUM', math_('MAXIMUM', rsep.outputs[0], rsep.outputs[1], loc=(-1000, 0)), rsep.outputs[2], loc=(-850, 0))
    links.new(math_('MULTIPLY', math_('MULTIPLY', gi.outputs['Reflection Strength'], gi.outputs['Shine Mask'],
                                      loc=(-700, 0)), rpeak, loc=(-550, 0), clamp=True),
              bsdf.inputs['Coat Weight'])
    bsdf.inputs['Coat Roughness'].default_value = 0.05

    # ---- game look, in the game's gamma space (it does its maths on the stored bytes)
    g_tex = gamma(diffuse, 1 / GAMMA, (-1200, -1600))
    g_bake = gamma(gi.outputs['Baked Light'], 1 / GAMMA, (-1200, -1750))
    g_spec = gamma(gi.outputs['Specular Color'], 1 / GAMMA, (-1200, -1900))
    g_refl = gamma(gi.outputs['Reflection Map'], 1 / GAMMA, (-1200, -2050))
    n = nmap.outputs['Normal']                                   # world-space normal (normal map applied)
    ndl = math_('MAXIMUM', vmath('DOT_PRODUCT', n, sun_dir.outputs[0], loc=(-1000, -700), out=1), 0.0, loc=(-850, -700))
    sun_term = vmath('SCALE', sun_col.outputs[0], None, loc=(-700, -950))              # sun colour * N.L
    links.new(ndl, sun_term.node.inputs['Scale'])
    light = vmath('ADD', sun_term, amb_col.outputs[0], loc=(-550, -950))                # sun * N.L + ambient
    lit = mix(mix(g_tex, g_bake, 'MULTIPLY', loc=(-900, -1600)), light, 'MULTIPLY', loc=(-400, -1500), clamp=True)
    # shine: (N.H)^power with H fixed per frame, times (1 - N.V), shine mask and specular colour
    half = vmath('NORMALIZE', vmath('ADD', sun_dir.outputs[0], view_dir.outputs[0], loc=(-1300, -2300)), loc=(-1150, -2300))
    ndh = math_('MAXIMUM', vmath('DOT_PRODUCT', n, half, loc=(-1000, -2300), out=1), 0.0, loc=(-850, -2300))
    pw = math_('POWER', ndh, gi.outputs['Shininess'], loc=(-700, -2300))
    ndv = math_('MAXIMUM', vmath('DOT_PRODUCT', n, view_dir.outputs[0], loc=(-1000, -2450), out=1), 0.0, loc=(-850, -2450))
    view_term = math_('SUBTRACT', 1.0, ndv, loc=(-700, -2450), clamp=True)
    shine = math_('MULTIPLY', math_('MULTIPLY', pw, view_term, loc=(-550, -2350)), gi.outputs['Shine Mask'], loc=(-400, -2350))
    spec = vmath('SCALE', g_spec, None, loc=(-250, -2100))
    links.new(shine, spec.node.inputs['Scale'])
    # reflection: map * strength * shine mask * view term * sun light on the face * 4
    rscale = math_('MULTIPLY', math_('MULTIPLY', gi.outputs['Reflection Strength'], gi.outputs['Shine Mask'],
                                     loc=(-700, -2650)), view_term, loc=(-550, -2650))
    rscale = math_('MULTIPLY', rscale, 4.0, loc=(-400, -2650))
    refl = vmath('SCALE', vmath('MULTIPLY', g_refl, vmath('MULTIPLY', sun_term, g_bake, loc=(-550, -2800)),
                               loc=(-400, -2800)), None, loc=(-250, -2700))
    links.new(rscale, refl.node.inputs['Scale'])
    game_g = vmath('ADD', vmath('ADD', lit, spec, loc=(-100, -1800)), refl, loc=(50, -1800))
    game = gamma(game_g, GAMMA, (200, -1800))
    emit = node('ShaderNodeEmission', (400, -1400))
    links.new(game, emit.inputs['Color'])

    pick = node('ShaderNodeMixShader', (700, 0))
    links.new(preview.outputs[0], pick.inputs['Fac'])
    links.new(bsdf.outputs['BSDF'], pick.inputs[1])
    links.new(emit.outputs['Emission'], pick.inputs[2])
    # like the game's lbts shader: texture x (stage ambient + light map), the light map holding sun and lamps only
    # (in the game's gamma space, like the game look: texture x (ambient + light map), then back to linear)
    # the export clips the light map to 0-1 (an 8-bit texture): so does the preview (Blender's bake is HDR)
    lm_clip = mix(gi.outputs['Light Map'], (1.0, 1.0, 1.0, 1.0), 'MULTIPLY', loc=(100, -400), clamp=True)
    lm_amb = mix(lm_clip, amb_col.outputs[0], 'ADD', loc=(250, -400))
    # light above white: the export puts it into the light map's alpha, which the game adds on top untextured
    # (light map x alpha, alpha = the part above white / the stored light, at most 1)
    sep_over = node('ShaderNodeSeparateColor', (100, -550))
    links.new(mix(gi.outputs['Light Map'], lm_clip, 'SUBTRACT', loc=(0, -550)), sep_over.inputs[0])
    sep_lm = node('ShaderNodeSeparateColor', (100, -650))
    links.new(lm_clip, sep_lm.inputs[0])
    over = math_('MAXIMUM', math_('MAXIMUM', sep_over.outputs[0], sep_over.outputs[1], loc=(180, -550)),
                 sep_over.outputs[2], loc=(240, -550))
    peak = math_('MAXIMUM', math_('MAXIMUM', sep_lm.outputs[0], sep_lm.outputs[1], loc=(180, -650)),
                 sep_lm.outputs[2], loc=(240, -650))
    hot_a = math_('DIVIDE', over, math_('MAXIMUM', peak, 0.0001, loc=(300, -650)), loc=(340, -600), clamp=True)
    hot = mix(lm_clip, hot_a, 'MULTIPLY', loc=(380, -560))
    lm = gamma(mix(mix(gamma(diffuse, 1 / GAMMA, (250, -250)), lm_amb, 'MULTIPLY', loc=(400, -400)), hot, 'ADD',
                   loc=(440, -420), clamp=True), GAMMA, (480, -400))
    glow = mix(glow_col, gi.outputs['Emission Strength'], 'MULTIPLY', loc=(400, -600))
    lm = mix(lm, glow, 'ADD', loc=(520, -450))                   # the light map's glow, added as the game does
    lm_emit = node('ShaderNodeEmission', (650, -400))
    links.new(lm, lm_emit.inputs['Color'])
    final = node('ShaderNodeMixShader', (800, 0))
    links.new(gi.outputs['Light Map Amount'], final.inputs['Fac'])
    links.new(pick.outputs['Shader'], final.inputs[1])
    links.new(lm_emit.outputs['Emission'], final.inputs[2])
    links.new(final.outputs['Shader'], go.inputs['Shader'])


def _sphere_group():
    """Sphere-map coordinates from the view reflection, for previewing a reflection map like the game."""
    ng = bpy.data.node_groups.get(SPHERE_GROUP)
    if ng is not None:
        return ng
    ng = bpy.data.node_groups.new(SPHERE_GROUP, 'ShaderNodeTree')
    ng.interface.new_socket('Vector', in_out='OUTPUT', socket_type='NodeSocketVector')
    nodes, links = ng.nodes, ng.links
    go = nodes.new('NodeGroupOutput')
    go.location = (600, 0)
    tc = nodes.new('ShaderNodeTexCoord')
    tc.location = (-600, 0)
    tf = nodes.new('ShaderNodeVectorTransform')          # reflection in camera space, as a sphere map expects
    tf.vector_type, tf.convert_from, tf.convert_to = 'VECTOR', 'WORLD', 'CAMERA'
    tf.location = (-400, 0)
    links.new(tc.outputs['Reflection'], tf.inputs['Vector'])
    sep = nodes.new('ShaderNodeSeparateXYZ')
    sep.location = (-200, 0)
    links.new(tf.outputs['Vector'], sep.inputs['Vector'])

    def m(op, a, b, loc):
        n = nodes.new('ShaderNodeMath')
        n.operation = op
        n.location = loc
        for i, v in enumerate((a, b)):
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                links.new(v, n.inputs[i])
        return n.outputs[0]
    # camera space looks down -Z: m = 2 * sqrt(x^2 + y^2 + (1 - z)^2), uv = xy / m + 0.5
    zz = m('SUBTRACT', 1.0, sep.outputs[2], (0, -200))
    s = m('ADD', m('ADD', m('MULTIPLY', sep.outputs[0], sep.outputs[0], (0, 100)),
                   m('MULTIPLY', sep.outputs[1], sep.outputs[1], (0, 0)), (150, 50)),
          m('MULTIPLY', zz, zz, (150, -200)), (300, 0))
    mm = m('MULTIPLY', m('SQRT', s, 0.0, (400, 0)), 2.0, (500, 0))
    u = m('ADD', m('DIVIDE', sep.outputs[0], mm, (600, 100)), 0.5, (700, 100))
    v = m('ADD', m('DIVIDE', sep.outputs[1], mm, (600, -100)), 0.5, (700, -100))
    comb = nodes.new('ShaderNodeCombineXYZ')
    comb.location = (850, 0)
    links.new(u, comb.inputs[0])
    links.new(v, comb.inputs[1])
    go.location = (1000, 0)
    links.new(comb.outputs[0], go.inputs['Vector'])
    return ng


def ensure_group():
    """The PD Stage Shader group, built or brought up to date (materials keep their links and values)."""
    ng = bpy.data.node_groups.get(GROUP)
    if ng is None or ng.bl_idname != 'ShaderNodeTree':
        ng = bpy.data.node_groups.new(GROUP, 'ShaderNodeTree')
        ng.description = 'Only the settings Phantom Dust\'s stage shaders support'
    if ng.get('pd_version') != GROUP_VERSION:
        old = ng.get('pd_version') or 0
        added = _interface(ng)
        _contents(ng)
        ng['pd_version'] = GROUP_VERSION
        _repair_new_inputs(ng, old, added)
        sync_preview(force=True)
    return ng


def _repair_new_inputs(ng, old, added=()):
    """Inputs added to the group appear on existing materials with the socket type's own default (black), not
    the group's: give them the group's default. Version 10 added Diffuse Color and Emission Color that way
    (black: every material went black), so they are reset to white where they were left black."""
    for mat in bpy.data.materials:
        if not mat.use_nodes or mat.node_tree is None:
            continue
        for n in mat.node_tree.nodes:
            if n.type != 'GROUP' or n.node_tree is not ng:
                continue
            for name, default in added:                  # new this time: the group's default
                inp = n.inputs.get(name)
                if inp is not None and not inp.is_linked:
                    inp.default_value = default
            if old < 11:                                 # left black by version 10
                for name in ('Diffuse Color', 'Emission Color'):
                    inp = n.inputs.get(name)
                    if inp is not None and not inp.is_linked and max(inp.default_value[:3]) == 0.0:
                        inp.default_value = (1.0, 1.0, 1.0, 1.0)


def group_node(mat):
    """The PD Stage Shader node of a material, or None."""
    if mat is None or not mat.use_nodes or mat.node_tree is None:
        return None
    return next((n for n in mat.node_tree.nodes if n.type == 'GROUP' and n.node_tree is not None
                 and n.node_tree.name.startswith(GROUP)), None)


# ---------------------------------------------------------------- keeping the preview in step with the scene

_last = {}


def _view_dir(scene):
    """Direction from the scene towards the viewer: the first 3D view (its camera if looking through one)."""
    try:
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type != 'VIEW_3D':
                    continue
                r3d = area.spaces.active.region_3d
                if r3d.view_perspective == 'CAMERA' and scene.camera is not None:
                    return scene.camera.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))
                return r3d.view_rotation @ Vector((0.0, 0.0, 1.0))
    except (AttributeError, ReferenceError):
        pass
    if scene.camera is not None:
        return scene.camera.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))
    return Vector((0.0, -0.7, 0.7))


def _sun_dir(scene):
    sun = getattr(scene, 'pd_sun', None)
    if sun is not None:
        return sun.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))      # towards the light
    for ob in scene.objects:
        if ob.type == 'LIGHT' and ob.data.type == 'SUN':
            return ob.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))
    return Vector((0.3, -0.4, 0.87))


def sync_preview(force=False):
    """Copy the scene's sun direction, view direction, light colours and the preview switch into the group."""
    ng = bpy.data.node_groups.get(GROUP)
    scene = getattr(bpy.context, 'scene', None)
    if ng is None or scene is None or SUN_DIR not in ng.nodes:
        return
    sd = _sun_dir(scene).normalized()
    vd = _view_dir(scene).normalized()
    cols = (tuple(getattr(scene, 'pd_stage_light', (0.706, 0.686, 0.608))),
            tuple(getattr(scene, 'pd_stage_ambient', (0.424, 0.392, 0.373))))
    on = 0.0 if _bake_hold else (1.0 if getattr(scene, 'pd_game_preview', True) else 0.0)
    state = (tuple(round(x, 4) for x in sd), tuple(round(x, 3) for x in vd), cols, on)
    if not force and _last.get(ng.name) == state:
        return
    _last[ng.name] = state
    for name, v in ((SUN_DIR, sd), (VIEW_DIR, vd)):
        for k in range(3):
            ng.nodes[name].inputs[k].default_value = v[k]
    # the colour properties are display (gamma) values: the game look works in gamma space, so store them as is
    ng.nodes[SUN_COL].outputs[0].default_value = (*cols[0], 1.0)
    ng.nodes[AMB_COL].outputs[0].default_value = (*cols[1], 1.0)
    ng.nodes[PREVIEW].outputs[0].default_value = on


_bake_hold = False


def set_preview(on):
    """Switch the game look on or off right away. Bake Lighting turns it off while it bakes: off stays off
    (the preview timer would switch it back on mid-bake, and the game look bakes black) until turned on."""
    global _bake_hold
    _bake_hold = not on
    ng = bpy.data.node_groups.get(GROUP)
    if ng is not None and PREVIEW in ng.nodes:
        ng.nodes[PREVIEW].outputs[0].default_value = 1.0 if on else 0.0
        _last.pop(ng.name, None)


def _sun_colour_sync():
    """Sun object colour -> Phantom Dust Lighting stage light (the other way is the property's update)."""
    scene = getattr(bpy.context, 'scene', None)
    sun = getattr(scene, 'pd_sun', None) if scene is not None else None
    if sun is None or sun.type != 'LIGHT' or sun.name not in scene.objects:
        return
    if any(abs(a - b) > 1e-4 for a, b in zip(sun.data.color, scene.pd_stage_light)):
        scene.pd_stage_light = tuple(sun.data.color)


def _timer():
    try:
        _sun_colour_sync()
        _sync_view_copies()
        sync_preview()
    except Exception:                                    # never let the timer die on an odd state
        pass
    return 0.2


@bpy.app.handlers.persistent
def _on_load(_dummy):
    if bpy.data.node_groups.get(GROUP) is not None:
        ensure_group()
    _last.clear()
    sync_preview(force=True)


def _transparency_changed(self, context):
    try:
        apply_alpha(self)
    except (AttributeError, RuntimeError, TypeError):
        pass


def register_props():
    bpy.types.Material.pd_transparent = bpy.props.BoolProperty(
        name='Transparent', default=False, update=_transparency_changed,
        description='Draw see-through in game (the blended shader, e.g. sdal): by the diffuse texture\'s alpha '
                    'and the Transparency slider. No light map on these meshes (the game has no blended '
                    'light-mapped shader)')
    bpy.types.Material.pd_transparency = bpy.props.FloatProperty(
        name='Transparency', default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=_transparency_changed,
        description='0: the texture\'s own alpha; 1: invisible. Baked into the exported texture\'s alpha')


    bpy.types.Material.pd_scroll = bpy.props.BoolProperty(
        name='Scrolling', default=False, update=_scroll_changed,
        description='Scroll the textures in game: the sky\'s cloud shader (sbtscloud3), lit by the map\'s light, '
                    'with a speed for the colour texture and for each of two normal maps. No light map, '
                    'reflection or highlight on these meshes')
    vec = dict(size=2, default=(0, 0), min=-32768, max=32767, soft_min=-3000, soft_max=3000,
               update=_scroll_changed)
    bpy.types.Material.pd_scroll_colour = bpy.props.IntVectorProperty(
        name='Diffuse Speed', description='X / Y scroll speed of the Diffuse texture (150 = a slow drift as the '
                                         'sky\'s clouds, 600 = clearly moving, 0 = still)', **vec)
    bpy.types.Material.pd_scroll_normal_a = bpy.props.IntVectorProperty(
        name='Normal Map Speed', description='X / Y scroll speed of the Normal Map texture', **vec)
    bpy.types.Material.pd_scroll_normal_b = bpy.props.IntVectorProperty(
        name='Normal Map 2 Speed', description='X / Y scroll speed of Normal Map 2, the texture picked below (added on top of the '
                                           'first: two layers moving apart make water ripple)', **vec)
    bpy.types.Material.pd_scroll_normal_b_image = bpy.props.PointerProperty(
        type=bpy.types.Image, name='Normal Map 2',
        description='The second normal map; none: the Normal Map again (at its own speed)')
    bpy.types.Material.pd_scroll_blend = bpy.props.EnumProperty(
        name='Draw', items=SCROLL_BLENDS, default='OPAQUE', update=_scroll_changed,
        description='How the scrolling surface is drawn')


def unregister_props():
    for k in ('pd_scroll', 'pd_scroll_colour', 'pd_scroll_normal_a', 'pd_scroll_normal_b',
              'pd_scroll_normal_b_image', 'pd_scroll_blend'):
        if hasattr(bpy.types.Material, k):
            delattr(bpy.types.Material, k)
    for k in ('pd_transparent', 'pd_transparency'):
        if hasattr(bpy.types.Material, k):
            delattr(bpy.types.Material, k)


def register_preview():
    if not bpy.app.timers.is_registered(_timer):
        bpy.app.timers.register(_timer, first_interval=0.5, persistent=True)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister_preview():
    if bpy.app.timers.is_registered(_timer):
        bpy.app.timers.unregister(_timer)
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)


# ---------------------------------------------------------------- building materials

def _image_node(nt, img, loc, non_color=False):
    n = nt.nodes.new('ShaderNodeTexImage')
    n.image = img
    n.location = loc
    if img is not None and non_color:
        try:
            img.colorspace_settings.name = 'Non-Color'
        except TypeError:
            pass
    return n


def add_map(mat, socket_name, img=None):
    """Link a new Image Texture node (optionally with an image) to one of the group's map inputs."""
    g = group_node(mat)
    nt = mat.node_tree
    y = {'Diffuse': 300, 'Normal Map': 0, 'Reflection Map': -300, 'Emission Map': -600}[socket_name]
    n = _image_node(nt, img, (g.location.x - 450, g.location.y + y), non_color=socket_name == 'Normal Map')
    n.label = socket_name
    nt.links.new(n.outputs['Color'], g.inputs[socket_name])
    if socket_name == 'Reflection Map':
        sp = nt.nodes.new('ShaderNodeGroup')
        sp.node_tree = _sphere_group()
        sp.location = (n.location.x - 220, n.location.y - 60)
        nt.links.new(sp.outputs['Vector'], n.inputs['Vector'])
        n.extension = 'EXTEND'
    return n


def remove_map(mat, socket_name):
    g = group_node(mat)
    for link in list(g.inputs[socket_name].links):
        node = link.from_node
        mat.node_tree.links.remove(link)
        if node.type == 'TEX_IMAGE' and not any(o.links for o in node.outputs):
            for l in list(node.inputs['Vector'].links):
                if l.from_node.type == 'GROUP' and l.from_node.node_tree is not None \
                        and l.from_node.node_tree.name.startswith(SPHERE_GROUP):
                    mat.node_tree.nodes.remove(l.from_node)
            mat.node_tree.nodes.remove(node)


def link_attribute(mat, socket_name, layer, output='Color'):
    g = group_node(mat)
    nt = mat.node_tree
    for link in list(g.inputs[socket_name].links):
        nt.links.remove(link)
    n = nt.nodes.new('ShaderNodeVertexColor')
    n.layer_name = layer
    n.label = socket_name
    n.location = (g.location.x - 450, g.location.y - {'Baked Light': 650, 'Shine Mask': 500}.get(socket_name, 600))
    nt.links.new(n.outputs[output], g.inputs[socket_name])
    return n


def setup(mat, diffuse=None, normal=None, reflection=None, specular=(0.0, 0.0, 0.0), shininess=20.0,
          shine=1.0, reflection_strength=1.0, light_layer=LIGHT_LAYER, shine_from_light_alpha=False,
          normal_strength=1.0):
    """Replace a material's nodes with the PD Stage Shader and its maps."""
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    out.location = (300, 0)
    g = nt.nodes.new('ShaderNodeGroup')
    g.node_tree = ensure_group()
    g.location = (0, 0)
    g.width = 240
    nt.links.new(g.outputs['Shader'], out.inputs['Surface'])
    g.inputs['Specular Color'].default_value = (*specular, 1.0)
    g.inputs['Shininess'].default_value = shininess
    g.inputs['Shine Mask'].default_value = shine
    g.inputs['Reflection Strength'].default_value = reflection_strength
    g.inputs['Normal Strength'].default_value = normal_strength
    if diffuse is None:
        g.inputs['Diffuse'].default_value = (0.3, 0.3, 0.3, 1.0)     # no texture: 30% grey
    if diffuse is not None:
        add_map(mat, 'Diffuse', diffuse)
    if normal is not None:
        add_map(mat, 'Normal Map', normal)
    if reflection is not None:
        add_map(mat, 'Reflection Map', reflection)
    if light_layer:
        link_attribute(mat, 'Baked Light', light_layer)
        if shine_from_light_alpha:
            link_attribute(mat, 'Shine Mask', light_layer, 'Alpha')
    if diffuse is not None:
        apply_alpha(mat, diffuse)
    if getattr(mat, 'pd_scroll', False):
        apply_scroll(mat)
    return mat


ALPHA_NODE = 'PD Alpha'
ALPHA_SCALE_NODE = 'PD Alpha Scale'
ADD_NODE = 'PD Glow Add'
ADD_NONE_NODE = 'PD Glow None'
ADD_CLEAR_NODE = 'PD Alpha Clear'


def alpha_kind(img):
    """How an image uses its alpha: 'NONE', 'CLIP' (cut-outs: road lines, fences, all 0 or 1) or 'BLEND' (glass).
    Worked out once from the pixels and kept on the image (pd_alpha)."""
    if img is None:
        return 'NONE'
    kind = img.get('pd_alpha')
    if kind in ('NONE', 'CLIP', 'BLEND'):
        return kind
    kind = 'NONE'
    try:
        import numpy as np
        w, h = img.size
        if w and h and img.channels == 4:
            px = np.empty(w * h * 4, dtype=np.float32)
            img.pixels.foreach_get(px)
            a = px[3::4]
            if (a < 0.5).mean() > 0.002:                    # a real see-through part, not stray texels
                kind = 'BLEND' if ((a > 0.1) & (a < 0.9)).mean() > 0.02 else 'CLIP'
    except (RuntimeError, ValueError, ImportError):
        pass
    try:
        img['pd_alpha'] = kind
    except (TypeError, AttributeError):
        pass
    return kind


def apply_alpha(mat, img=None):
    """Show the diffuse texture's see-through parts in Blender (Material Preview and renders): the game cuts out
    or blends them, so road markings and glass would otherwise show their black background. Display only: the
    shader group and what the export reads are unchanged."""
    nt = mat.node_tree
    g = group_node(mat)
    if g is None:
        return
    old = nt.nodes.get(ALPHA_NODE)
    if old is not None:
        tr = next((l.from_node for l in old.inputs[1].links), None)
        nt.nodes.remove(old)
        if tr is not None:
            nt.nodes.remove(tr)
    for name in (ALPHA_SCALE_NODE, ADD_NODE, ADD_NONE_NODE, ADD_CLEAR_NODE):
        old = nt.nodes.get(name)
        if old is not None:
            nt.nodes.remove(old)
    out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'), None)
    tex = image_node(mat, 'Diffuse')
    img = img if img is not None else (tex.image if tex is not None else None)
    see = transparency(mat)
    if getattr(mat, 'pd_scroll', False) and mat.pd_scroll_blend != 'OPAQUE':
        see = dict(transparent=True, transparency=see['transparency'])
    kind = 'BLEND' if see['transparent'] else alpha_kind(img)
    if out is None or (tex is None and not see['transparent']) or kind == 'NONE':
        nt.links.new(g.outputs['Shader'], out.inputs['Surface']) if out is not None else None
        return
    tr = nt.nodes.new('ShaderNodeBsdfTransparent')
    tr.name = tr.label = ADD_CLEAR_NODE
    tr.location = (g.location.x + 300, g.location.y + 150)
    mx = nt.nodes.new('ShaderNodeMixShader')
    mx.name = mx.label = ALPHA_NODE
    mx.location = (g.location.x + 300, g.location.y - 100)
    out.location = (g.location.x + 520, g.location.y)
    if see['transparent']:                              # the slider: alpha x (1 - transparency), as exported
        sc = nt.nodes.new('ShaderNodeMath')
        sc.operation = 'MULTIPLY'
        sc.name = sc.label = ALPHA_SCALE_NODE
        sc.location = (g.location.x + 120, g.location.y - 260)
        sc.inputs[0].default_value = 1.0
        sc.inputs[1].default_value = 1.0 - see['transparency']
        if tex is not None:
            nt.links.new(tex.outputs['Alpha'], sc.inputs[0])
        nt.links.new(sc.outputs['Value'], mx.inputs['Fac'])
    else:
        nt.links.new(tex.outputs['Alpha'], mx.inputs['Fac'])
    nt.links.new(g.outputs['Shader'], mx.inputs[2])
    if getattr(mat, 'pd_scroll', False) and mat.pd_scroll_blend == 'ADD':
        # Glow as the game draws it (src x alpha + what is behind): the surface x alpha, added to a clear surface
        none = nt.nodes.new('ShaderNodeEmission')
        none.name = none.label = ADD_NONE_NODE
        none.inputs['Strength'].default_value = 0.0
        none.location = (g.location.x + 120, g.location.y + 150)
        nt.links.new(none.outputs['Emission'], mx.inputs[1])
        add = nt.nodes.new('ShaderNodeAddShader')
        add.name = add.label = ADD_NODE
        add.location = (g.location.x + 420, g.location.y + 50)
        tr.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)
        nt.links.new(tr.outputs['BSDF'], add.inputs[0])
        nt.links.new(mx.outputs['Shader'], add.inputs[1])
        nt.links.new(add.outputs['Shader'], out.inputs['Surface'])
        out.location = (g.location.x + 640, g.location.y)
        kind = 'BLEND'
    else:
        nt.links.new(tr.outputs['BSDF'], mx.inputs[1])
        nt.links.new(mx.outputs['Shader'], out.inputs['Surface'])
    for attr, val in (('surface_render_method', 'BLENDED' if kind == 'BLEND' else 'DITHERED'),
                      ('blend_method', 'BLEND' if kind == 'BLEND' else 'CLIP')):
        try:
            setattr(mat, attr, val)
        except (AttributeError, TypeError):
            pass
    try:
        mat.use_backface_culling = False
    except AttributeError:
        pass


def make_material(name, diffuse=None, **kw):
    """A new material using the PD Stage Shader (reuses an existing material of that name)."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    return setup(bpy.data.materials.new(name), diffuse=diffuse, **kw)


def first_image(mat):
    """The image a non-PD material shows (Base Color chain first, else any Image Texture)."""
    if mat is None or not mat.use_nodes or mat.node_tree is None:
        return None
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is not None and bsdf.inputs['Base Color'].is_linked:
        img = _upstream_image(bsdf.inputs['Base Color'])
        if img is not None:
            return img
    return next((n.image for n in nt.nodes if n.type == 'TEX_IMAGE' and n.image is not None), None)


# ---------------------------------------------------------------- reading a material for export

def _upstream(socket, types):
    """First node of one of `types` feeding `socket` (through any nodes), with the output socket it used on
    the way."""
    todo, seen = [(l.from_node, l.from_socket) for l in socket.links], set()
    while todo:
        n, out = todo.pop(0)
        if n.name in seen:
            continue
        seen.add(n.name)
        if n.type in types:
            return n, out
        for inp in n.inputs:
            for l in inp.links:
                todo.append((l.from_node, l.from_socket))
    return None, None


def _upstream_image(socket):
    n, _ = _upstream(socket, ('TEX_IMAGE',))
    return n.image if n is not None else None


def image_node(mat, socket_name):
    g = group_node(mat)
    if g is None:
        return None
    n, _ = _upstream(g.inputs[socket_name], ('TEX_IMAGE',))
    return n


def _attribute_source(socket):
    """('attr', name, channel) for a socket fed by a Color Attribute / Attribute node, else None.
    channel: 'A' (alpha), 'F' (float value or colour brightness) or 'RGB'."""
    n, out = _upstream(socket, ('VERTEX_COLOR', 'ATTRIBUTE'))
    if n is None:
        return None
    name = n.layer_name if n.type == 'VERTEX_COLOR' else n.attribute_name
    channel = {'Alpha': 'A', 'Fac': 'F'}.get(out.name, 'RGB')
    return ('attr', name, channel)


def _byte(x):
    return int(round(max(0.0, min(1.0, x)) * 255))


def _srgb(c):
    """Linear (as stored in colour sockets) -> sRGB, so the bytes match the colour picker's display."""
    return ((c * 12.92) if c <= 0.0031308 else (1.055 * c ** (1 / 2.4) - 0.055)) if c > 0 else 0.0


def read(mat):
    """Export settings of a material. Non-PD materials keep the old behaviour: their image as the texture,
    baked light from PD_Light (or the active colour attribute), no highlight."""
    g = group_node(mat)
    if g is None:
        return dict(pd=False, diffuse=first_image(mat), normal=None, reflection=None, specular=(0, 0, 0, 0),
                    reflection_strength=1.0, normal_strength=1.0, shine=('const', 1.0), light=None,
                    **transparency(mat), **scrolling(mat))
    ins = g.inputs
    sc = ins['Specular Color'].default_value
    spec = tuple(_byte(_srgb(sc[k])) for k in range(3)) + (int(round(ins['Shininess'].default_value)),)
    shine = _attribute_source(ins['Shine Mask']) or ('const', ins['Shine Mask'].default_value)
    light = _attribute_source(ins['Baked Light'])
    if light is None and not ins['Baked Light'].is_linked:
        light = ('const', tuple(_byte(_srgb(x)) for x in ins['Baked Light'].default_value[:3]))
    return dict(pd=True, diffuse=_upstream_image(ins['Diffuse']), normal=_upstream_image(ins['Normal Map']),
                reflection=_upstream_image(ins['Reflection Map']), specular=spec,
                reflection_strength=ins['Reflection Strength'].default_value,
                normal_strength=ins['Normal Strength'].default_value if 'Normal Strength' in ins else 1.0,
                shine=shine, light=light, **emission(mat), **diffuse_colour(mat), **transparency(mat),
                **scrolling(mat))


SCROLL_BLENDS = (('OPAQUE', 'Solid', 'Drawn solid'),
                 ('ALPHA', 'See-through', 'See-through by the colour texture\'s alpha (and the Transparency slider)'),
                 ('ADD', 'Glow', 'Added on top of what is behind it, like the sky\'s clouds and glowing energy'))
SCROLL_PROPS = ('pd_scroll_colour', 'pd_scroll_normal_a', 'pd_scroll_normal_b')
SCROLL_NODE = 'PD Scroll '
# preview speed: value / 65536 texture widths per game frame at 60 fps (as the sky preview; an estimate)
SCROLL_DIV = 65536.0
GAME_FPS = 60.0


def scrolling(mat):
    """{'scroll': drawn with the scrolling shader (the sky's cloud shader sbtscloud3), 'scroll_speeds': (x, y) for
    the colour texture, normal map A and normal map B, 'scroll_blend', 'normal_b': the second normal map image}."""
    on = bool(getattr(mat, 'pd_scroll', False)) if mat is not None else False
    if not on:
        return dict(scroll=False)
    speeds = tuple(int(v) for p in SCROLL_PROPS for v in getattr(mat, p))
    return dict(scroll=True, scroll_speeds=speeds, scroll_blend=mat.pd_scroll_blend,
                normal_b=getattr(mat, 'pd_scroll_normal_b_image', None))


def apply_scroll(mat):
    """Preview: a Mapping node in front of the Diffuse and Normal Map image nodes, its offset driven by the frame
    (press Play) and the material's speeds. Normal map B is not previewed (the shader preview has one normal map)."""
    if mat is None or mat.node_tree is None:
        return
    nt = mat.node_tree
    for n in [n for n in nt.nodes if n.name.startswith(SCROLL_NODE)]:
        nt.nodes.remove(n)
    if not getattr(mat, 'pd_scroll', False) or group_node(mat) is None:
        return
    fps = (bpy.context.scene.render.fps / bpy.context.scene.render.fps_base) if bpy.context.scene else 24.0
    for slot, prop in (('Diffuse', 'pd_scroll_colour'), ('Normal Map', 'pd_scroll_normal_a')):
        img = image_node(mat, slot)
        if img is None:
            continue
        uv = nt.nodes.new('ShaderNodeTexCoord')
        uv.name = uv.label = SCROLL_NODE + slot + ' UV'
        uv.location = (img.location.x - 420, img.location.y)
        mp = nt.nodes.new('ShaderNodeMapping')
        mp.name = mp.label = SCROLL_NODE + slot
        mp.location = (img.location.x - 220, img.location.y)
        nt.links.new(uv.outputs['UV'], mp.inputs['Vector'])
        nt.links.new(mp.outputs['Vector'], img.inputs['Vector'])
        loc = mp.inputs['Location']
        # game UV + speed x time; Blender's v runs the other way, so y is negated
        for axis, sign in ((0, ''), (1, '-')):
            fc = loc.driver_add('default_value', axis)
            drv = fc.driver
            drv.type = 'SCRIPTED'
            v = drv.variables.new()
            v.name = 's'
            v.type = 'SINGLE_PROP'
            v.targets[0].id_type = 'MATERIAL'
            v.targets[0].id = mat
            v.targets[0].data_path = '%s[%d]' % (prop, axis)
            drv.expression = '%ss * frame * %g / (%g * %g)' % (sign, GAME_FPS, SCROLL_DIV, fps)


def _scroll_changed(self, context):
    try:
        apply_scroll(self)
        apply_alpha(self)
    except (AttributeError, RuntimeError, TypeError):
        pass


def transparency(mat):
    """{'transparent': drawn with the blended shader (sdal...: see-through by the diffuse alpha), 'transparency':
    0 = the texture's own alpha, 1 = invisible}."""
    on = bool(getattr(mat, 'pd_transparent', False)) if mat is not None else False
    if mat is not None and getattr(mat, 'pd_scroll', False):       # scrolling: its own blend setting
        see = mat.pd_scroll_blend == 'ALPHA'
        return dict(transparent=False, transparency=float(mat.pd_transparency) if see else 0.0)
    return dict(transparent=on, transparency=float(getattr(mat, 'pd_transparency', 0.0)) if on else 0.0)


def diffuse_colour(mat):
    """{'diffuse_tint': Diffuse Color, 'diffuse_colour': the Diffuse colour when no texture is linked}, both as
    sRGB 0-1 (what the texture's bytes hold)."""
    g = group_node(mat)
    if g is None:
        return dict(diffuse_tint=(1.0, 1.0, 1.0), diffuse_colour=(1.0, 1.0, 1.0))
    ins = g.inputs
    tint = tuple(_srgb(x) for x in ins['Diffuse Color'].default_value[:3]) if 'Diffuse Color' in ins \
        else (1.0, 1.0, 1.0)
    col = tuple(_srgb(x) for x in ins['Diffuse'].default_value[:3])
    return dict(diffuse_tint=tint, diffuse_colour=col)


def emission(mat):
    """{'emission': image or None, 'emission_colour': (r, g, b) when no image, 'emission_strength'} of a PD
    material (nothing glows: emission None and colour black)."""
    g = group_node(mat)
    if g is None or 'Emission Map' not in g.inputs:
        return dict(emission=None, emission_colour=(0.0, 0.0, 0.0), emission_tint=(1.0, 1.0, 1.0),
                    emission_strength=0.0)
    ins = g.inputs
    img = _upstream_image(ins['Emission Map'])
    col = (0.0, 0.0, 0.0) if ins['Emission Map'].is_linked else tuple(ins['Emission Map'].default_value[:3])
    tint = tuple(ins['Emission Color'].default_value[:3]) if 'Emission Color' in ins else (1.0, 1.0, 1.0)
    if img is None:
        col = tuple(c * t for c, t in zip(col, tint))
    return dict(emission=img, emission_colour=col, emission_tint=tint,
                emission_strength=ins['Emission Strength'].default_value)


def glows(mat):
    e = emission(mat)
    return e['emission_strength'] > 0 and (max(e['emission_tint']) > 0 if e['emission'] is not None
                                           else max(e['emission_colour']) > 0)


def game_shader(settings):
    if settings.get('scroll'):
        return 'sbtscloud3'
    return {(False, False): 'sd', (True, False): 'sbts', (False, True): 'sdrefs', (True, True): 'sbtsrefs'}[
        (settings['normal'] is not None, settings['reflection'] is not None)] + \
        ('al' if settings.get('transparent') else '')


# ---------------------------------------------------------------- operators and panel

def draw_preview_toggle(layout, context):
    """Game Preview switch, with a hint when colour management would change the colours."""
    scene = context.scene
    col = layout.column(align=True)
    col.prop(scene, 'pd_game_preview', icon='HIDE_OFF' if scene.pd_game_preview else 'HIDE_ON')
    if scene.pd_game_preview:
        if scene.view_settings.view_transform != 'Standard':
            col.prop(scene.view_settings, 'view_transform', text='Use Standard', icon='ERROR')


def ensure_light_layer(ob):
    """Give a mesh a white PD_Light (= no baked light yet: the texture shows as is) if it has none. Without it the
    material's Baked Light reads black. Returns True if one was added."""
    if ob is None or ob.type != 'MESH' or ob.data.color_attributes.get(LIGHT_LAYER) is not None:
        return False
    layer = ob.data.color_attributes.new(LIGHT_LAYER, 'BYTE_COLOR', 'POINT')
    white = [1.0] * (4 * len(layer.data))
    layer.data.foreach_set('color', white)
    ob.data.update()
    return True


def _uses_light_layer(mat):
    g = group_node(mat)
    if g is None:
        return False
    return any(getattr(l.from_node, 'layer_name', '') == LIGHT_LAYER for l in g.inputs['Baked Light'].links)


def _active_material(context):
    """The material to edit: while Show Baked Lighting shows a temporary copy, the original behind it (edits on
    the copy would be lost when the preview ends)."""
    ob = context.object
    mat = ob.active_material if ob is not None else None
    if mat is not None and mat.get('pd_view_of'):
        return bpy.data.materials.get(mat['pd_view_of']) or mat
    return mat


def _sync_view_copies():
    """Show Baked Lighting copies follow their original's settings (the panel edits the original)."""
    for c in bpy.data.materials:
        src = c.get('pd_view_of')
        if not src:
            continue
        m = bpy.data.materials.get(src)
        gc, gm = group_node(c), group_node(m) if m is not None else None
        if gc is None or gm is None:
            continue
        for inp in gm.inputs:
            if inp.name in ('Light Map', 'Light Map Amount') or inp.name not in gc.inputs:
                continue
            other = gc.inputs[inp.name]
            if hasattr(inp, 'default_value') and not other.is_linked:
                a, b = inp.default_value, other.default_value
                if (tuple(a) if hasattr(a, '__len__') else a) != (tuple(b) if hasattr(b, '__len__') else b):
                    other.default_value = a


class PDSTAGE_OT_make_material(bpy.types.Operator):
    """Turn this material into a Phantom Dust material (PD Stage Shader), keeping its image as the Diffuse
    texture. Its other node settings are replaced"""
    bl_idname = 'pdstage.make_material'
    bl_label = 'Make Phantom Dust Material'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ob = context.object
        if ob is None or ob.type != 'MESH':
            self.report({'ERROR'}, 'Select a mesh object')
            return {'CANCELLED'}
        mat = ob.active_material
        if mat is None:
            mat = bpy.data.materials.new('PD_Material')
            if ob.material_slots:
                ob.material_slots[ob.active_material_index].material = mat
            else:
                ob.data.materials.append(mat)
            setup(mat)
        elif group_node(mat) is None:
            setup(mat, diffuse=first_image(mat))
        added = sum(ensure_light_layer(o) for o in {ob, *context.selected_objects}
                    if o.type == 'MESH' and any(sl.material == mat for sl in o.material_slots))
        if added:
            self.report({'INFO'}, 'Added a white PD_Light (no baked light yet) to %d object%s; Bake Lighting fills it'
                        % (added, '' if added == 1 else 's'))
        return {'FINISHED'}


def _source_maps(mat):
    """(diffuse image, normal image, base colour) of a non-PD material: what feeds the Principled BSDF's Base
    Color and Normal, else any image node (Non-Color ones taken as the normal map)."""
    diffuse = normal = None
    colour = tuple(mat.diffuse_color)
    if mat.use_nodes and mat.node_tree is not None:
        nt = mat.node_tree
        bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf is not None:
            diffuse = _upstream_image(bsdf.inputs['Base Color'])
            normal = _upstream_image(bsdf.inputs['Normal'])
            colour = tuple(bsdf.inputs['Base Color'].default_value)
        for n in nt.nodes:
            if n.type != 'TEX_IMAGE' or n.image is None or n.image in (diffuse, normal):
                continue
            if n.image.colorspace_settings.name == 'Non-Color' or 'normal' in n.image.name.lower():
                normal = normal or n.image
            else:
                diffuse = diffuse or n.image
    return diffuse, normal, colour


class PDSTAGE_OT_make_all_materials(bpy.types.Operator):
    """Turn every material in the Visuals and Objects collections that is not a Phantom Dust material yet into
    one, keeping its texture as the Diffuse map and its normal map as the Normal Map (other node settings are
    replaced). Meshes without a material get a new one (30% grey)"""
    bl_idname = 'pdstage.make_all_materials'
    bl_label = 'Make All Phantom Dust Materials'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from . import exporter
        objs = {o for role in ('VISUALS', 'OBJECTS') for c in exporter.collections_with_role(context.scene, role)
                for o in c.all_objects if o.type == 'MESH'}
        made = 0
        for o in objs:                                   # no material at all: a new one per mesh
            if not o.material_slots or all(sl.material is None for sl in o.material_slots):
                mat = bpy.data.materials.new(o.name)
                setup(mat)
                if o.material_slots:
                    for sl in o.material_slots:
                        sl.material = mat
                else:
                    o.data.materials.append(mat)
                ensure_light_layer(o)
                made += 1
        mats = {sl.material for o in objs for sl in o.material_slots
                if sl.material is not None and group_node(sl.material) is None}
        maps = 0
        for mat in mats:
            diffuse, normal, colour = _source_maps(mat)
            setup(mat, diffuse=diffuse, normal=normal)
            if diffuse is None:
                group_node(mat).inputs['Diffuse'].default_value = colour[:3] + (1.0,)
            maps += (diffuse is not None) + (normal is not None)
        for o in objs:
            if any(sl.material in mats for sl in o.material_slots):
                ensure_light_layer(o)
        self.report({'INFO'}, '%d materials made Phantom Dust materials (%d texture maps kept), %d new ones for '
                              'meshes without a material' % (len(mats), maps, made))
        return {'FINISHED'}


class PDSTAGE_OT_add_map(bpy.types.Operator):
    """Add an Image Texture for this map (open or pick an image in the panel afterwards)"""
    bl_idname = 'pdstage.add_map'
    bl_label = 'Add Map'
    bl_options = {'REGISTER', 'UNDO'}

    slot: bpy.props.StringProperty(name='Map', default='Diffuse')

    def execute(self, context):
        mat = _active_material(context)
        if group_node(mat) is None or self.slot not in MAPS:
            return {'CANCELLED'}
        add_map(mat, self.slot)
        return {'FINISHED'}


class PDSTAGE_OT_remove_map(bpy.types.Operator):
    """Remove this map from the material"""
    bl_idname = 'pdstage.remove_map'
    bl_label = 'Remove Map'
    bl_options = {'REGISTER', 'UNDO'}

    slot: bpy.props.StringProperty(name='Map', default='Diffuse')

    def execute(self, context):
        mat = _active_material(context)
        if group_node(mat) is None or self.slot not in MAPS:
            return {'CANCELLED'}
        remove_map(mat, self.slot)
        return {'FINISHED'}


class PDSTAGE_OT_paint_shine(bpy.types.Operator):
    """Paint where this material shines: adds a PD_Shine colour attribute (white = full shine, black = none) to
    the selected meshes, links it to Shine Mask and switches to Vertex Paint"""
    bl_idname = 'pdstage.paint_shine'
    bl_label = 'Paint Shine Mask'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mat = _active_material(context)
        if group_node(mat) is None:
            return {'CANCELLED'}
        obs = {o for o in context.selected_objects if o.type == 'MESH'} | {context.object}
        level = group_node(mat).inputs['Shine Mask'].default_value
        for o in obs:
            if o.type != 'MESH' or mat.name not in o.data.materials:
                continue
            attr = o.data.color_attributes.get(SHINE_LAYER)
            if attr is None:
                attr = o.data.color_attributes.new(SHINE_LAYER, 'BYTE_COLOR', 'POINT')
                for d in attr.data:
                    d.color_srgb = (level, level, level, 1.0)
            o.data.color_attributes.active_color = attr
        link_attribute(mat, 'Shine Mask', SHINE_LAYER, 'Color')
        if context.object.mode != 'VERTEX_PAINT':
            bpy.ops.object.mode_set(mode='VERTEX_PAINT')
        return {'FINISHED'}


class PDSTAGE_OT_unlink_input(bpy.types.Operator):
    """Use a single value for the whole material instead of the linked attribute"""
    bl_idname = 'pdstage.unlink_input'
    bl_label = 'Use One Value'
    bl_options = {'REGISTER', 'UNDO'}

    socket: bpy.props.StringProperty()

    def execute(self, context):
        mat = _active_material(context)
        g = group_node(mat)
        if g is None or self.socket not in g.inputs:
            return {'CANCELLED'}
        for link in list(g.inputs[self.socket].links):
            mat.node_tree.links.remove(link)
        return {'FINISHED'}


class PDSTAGE_OT_add_light_layer(bpy.types.Operator):
    """Give the selected meshes a white PD_Light colour attribute (no baked light yet), so the material isn't black.
    Bake Lighting fills it with real light later"""
    bl_idname = 'pdstage.add_light_layer'
    bl_label = 'Add White PD_Light'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obs = {o for o in (context.object, *context.selected_objects) if o is not None}
        n = sum(ensure_light_layer(o) for o in obs)
        self.report({'INFO'}, 'PD_Light added to %d object%s' % (n, '' if n == 1 else 's'))
        return {'FINISHED'}


class PDSTAGE_OT_link_baked_light(bpy.types.Operator):
    """Use the PD_Light colour attribute (filled by Bake Lighting) as the baked light"""
    bl_idname = 'pdstage.link_baked_light'
    bl_label = 'Use PD_Light'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mat = _active_material(context)
        if group_node(mat) is None:
            return {'CANCELLED'}
        link_attribute(mat, 'Baked Light', LIGHT_LAYER)
        return {'FINISHED'}


class PDSTAGE_PT_material(bpy.types.Panel):
    bl_label = 'Phantom Dust Material'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'material'

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == 'MESH'

    def draw(self, context):
        lay = self.layout
        mat = _active_material(context)
        g = group_node(mat)
        if g is None:
            col = lay.column()
            col.label(text='Not a Phantom Dust material: exported with', icon='INFO')
            col.label(text='its image only and no highlight.')
            col.operator(PDSTAGE_OT_make_material.bl_idname, icon='MATERIAL')
            return
        s = read(mat)
        names = {'sd': 'simple (sd)', 'sbts': 'normal map (sbts)', 'sdrefs': 'reflection (sdrefs)',
                 'sbtsrefs': 'normal map + reflection (sbtsrefs)'}
        shader = game_shader(s)
        if s.get('scroll'):
            lay.label(text='Game shader: scrolling (sbtscloud3)', icon='SHADING_RENDERED')
        else:
            lay.label(text='Game shader: ' + names[shader[:-2] if s.get('transparent') else shader]
                      + (' + transparent (%s)' % shader if s.get('transparent') else ''), icon='SHADING_RENDERED')
            row = lay.row(align=True)
            row.prop(mat, 'pd_transparent', text='Transparent')
            sub = row.row(align=True)
            sub.active = mat.pd_transparent
            sub.prop(mat, 'pd_transparency', text='Transparency', slider=True)
            if mat.pd_transparent and getattr(context.scene, 'pd_bake_use', False):
                lay.label(text='Transparent meshes keep vertex light (no light map)', icon='INFO')
        box = lay.box()
        box.prop(mat, 'pd_scroll', text='Scrolling Textures', icon='UV_SYNC_SELECT')
        if mat.pd_scroll:
            col = box.column(align=True)
            col.prop(mat, 'pd_scroll_blend', text='Draw')
            if mat.pd_scroll_blend == 'ALPHA':
                col.prop(mat, 'pd_transparency', text='Transparency', slider=True)
            col = box.column(align=True)
            col.prop(mat, 'pd_scroll_colour', text='Diffuse X / Y')
            col.prop(mat, 'pd_scroll_normal_a', text='Normal Map X / Y')
            col.prop(mat, 'pd_scroll_normal_b', text='Normal Map 2 X / Y')
            col.template_ID(mat, 'pd_scroll_normal_b_image', open='image.open')
            if mat.pd_scroll_normal_b_image is None:
                col.label(text='Normal Map 2: none, uses the Normal Map', icon='INFO')
            box.label(text='150 = slow drift, 600 = moving; press Play to preview', icon='INFO')
            box.label(text='No light map, reflection or highlight here', icon='INFO')
        draw_preview_toggle(lay, context)
        ob = context.object
        if _uses_light_layer(mat) and ob.data.color_attributes.get(LIGHT_LAYER) is None:
            box = lay.box()
            box.label(text='This mesh has no PD_Light: shows black here', icon='ERROR')
            box.label(text='(the game uses white). Bake Lighting, or:')
            box.operator(PDSTAGE_OT_add_light_layer.bl_idname, icon='ADD')

        box = lay.box()
        box.label(text='Maps', icon='TEXTURE')
        for slot in MAPS:
            if slot not in g.inputs:                     # an older group, before it is rebuilt
                continue
            node = image_node(mat, slot)
            col = box.column(align=True)
            row = col.row(align=True)
            row.label(text=slot)
            if node is None:
                if g.inputs[slot].is_linked:
                    row.label(text='(linked, no image found)', icon='ERROR')
                else:
                    row.operator(PDSTAGE_OT_add_map.bl_idname, text='Add', icon='ADD').slot = slot
                if slot == 'Emission Map' and not g.inputs[slot].is_linked:
                    r2 = col.row(align=True)                 # a plain glow colour, without an image
                    r2.prop(g.inputs['Emission Map'], 'default_value', text='')
                    r2.prop(g.inputs['Emission Strength'], 'default_value', text='Strength')
                if slot == 'Diffuse' and not g.inputs[slot].is_linked:
                    col.prop(g.inputs['Diffuse'], 'default_value', text='Color')   # no texture: a plain colour
                continue
            row.operator(PDSTAGE_OT_remove_map.bl_idname, text='', icon='X').slot = slot
            col.template_ID(node, 'image', new='image.new', open='image.open')
            if slot == 'Normal Map':
                col.prop(g.inputs['Normal Strength'], 'default_value', text='Strength')
            if slot == 'Emission Map':
                r2 = col.row(align=True)                     # the map times a colour and a strength
                if 'Emission Color' in g.inputs:
                    r2.prop(g.inputs['Emission Color'], 'default_value', text='')
                r2.prop(g.inputs['Emission Strength'], 'default_value', text='Strength')
            if slot == 'Diffuse' and 'Diffuse Color' in g.inputs:
                col.prop(g.inputs['Diffuse Color'], 'default_value', text='Color (multiplies the texture)')
            if slot == 'Normal Map' and node.image is not None \
                    and node.image.colorspace_settings.name != 'Non-Color':
                col.prop(node.image.colorspace_settings, 'name', text='Color Space (use Non-Color)', icon='ERROR')

        box = lay.box()
        box.label(text='Highlight', icon='LIGHT_SUN')
        col = box.column()
        col.prop(g.inputs['Specular Color'], 'default_value', text='Specular Color')
        col.prop(g.inputs['Shininess'], 'default_value', text='Shininess')
        src = _attribute_source(g.inputs['Shine Mask'])
        if src is None:
            row = col.row(align=True)
            row.prop(g.inputs['Shine Mask'], 'default_value', text='Shine Mask')
            row.operator(PDSTAGE_OT_paint_shine.bl_idname, text='', icon='BRUSH_DATA')
        else:
            row = col.row(align=True)
            row.label(text='Shine Mask: painted (%s)' % (src[1] or 'active colour'), icon='VPAINT_HLT')
            row.operator(PDSTAGE_OT_unlink_input.bl_idname, text='', icon='X').socket = 'Shine Mask'
        if s['reflection'] is not None:
            col.prop(g.inputs['Reflection Strength'], 'default_value', text='Reflection Strength')
        if not any(s['specular'][:3]):
            col.label(text='Black = no shine (most game surfaces)', icon='INFO')
        else:
            col.label(text='In game whole faces shine evenly;', icon='INFO')
            col.label(text='the game uses dark to mid grey.')
            if max(s['specular'][:3]) > 140:
                col.label(text='Bright colour: expect strong shine', icon='ERROR')

        box = lay.box()
        box.label(text='Lighting', icon='LIGHT')
        col = box.column()
        src = _attribute_source(g.inputs['Baked Light'])
        if src is not None:
            row = col.row(align=True)
            row.label(text='Baked Light: %s' % (src[1] or 'active colour'), icon='GROUP_VCOL')
            row.operator(PDSTAGE_OT_unlink_input.bl_idname, text='', icon='X').socket = 'Baked Light'
        else:
            row = col.row(align=True)
            row.prop(g.inputs['Baked Light'], 'default_value', text='Baked Light')
            row.operator(PDSTAGE_OT_link_baked_light.bl_idname, text='', icon='GROUP_VCOL')
        if s['normal'] is not None:
            col.label(text='Normal map: the game lights it with the sun;', icon='INFO')
            col.label(text='the bake only adds shade (red channel).')


classes = (PDSTAGE_OT_make_material, PDSTAGE_OT_make_all_materials, PDSTAGE_OT_add_map, PDSTAGE_OT_remove_map, PDSTAGE_OT_paint_shine,
           PDSTAGE_OT_unlink_input, PDSTAGE_OT_add_light_layer, PDSTAGE_OT_link_baked_light, PDSTAGE_PT_material)
