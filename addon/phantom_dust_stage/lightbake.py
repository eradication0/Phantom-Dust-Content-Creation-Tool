"""Light baking into light maps.

The game has real light maps (shader lbts, from the underground hub; works on battle stages, FORMATS.md "Light
maps"): a mesh keeps its own texture on its own UV map (tiling is fine) and gets a light map on a second UV map,
drawn as texture x (stage ambient + light map). So the bake records the light alone (sun, lamps, bounces,
shadows; no texture, no ambient: the game adds the ambient itself) into one light map per mesh, on light map
UVs made with Smart UV Project (PD_LightUV, DENSITY pixels per metre, at most MAX_SIZE). The export writes those
meshes as lbts with their light map.

What takes part:
  lights      the scene Sun (Phantom Dust Lighting), every light in the Lighting collection and every other light
              visible in the viewport (point, spot and area lamps).
  casters and receivers
              the stage meshes under Visuals (not Sky/Background) and the objects under Objects (one bake per
              object model: placements share their model in the game, so the first placement's light is used).
  everything else (colliders, sky, spawns, broken pieces...) is hidden from the bake.
Meshes with see-through textures (fences, decals, glass) only cast.

The whole scene is baked in one Cycles bake (every mesh casts on every other) through temporary stand-in
materials in Blender's own shaders, with everything else hidden for renders meanwhile. Light maps are saved as
EXR (PDLight_) in Map/pd_lightmaps. Show Baked Lighting plugs them into the PD shader's Light Map input.
"""
import math
import time

import bpy

from . import exporter, pd_material

UV_NAME = 'PD_LightUV'
NODE_NAME = 'PD Bake Target'
IMAGE_PREFIX = 'PDBake_'          # the texture the export uses: texture x light
LIGHT_PREFIX = 'PDLight_'         # the light alone (the light map the PD shader shows)

MARGIN = 8              # px of colour bled past each UV island, so mip levels show no seams
MAX_SIZE = 1024         # the export writes textures up to 1024 (the export's light map budget can shrink them)
DENSITY = 16.0          # light map pixels per metre
UV_FILL = 0.55          # share of a light map the UV islands cover (gaps, margins, packing)
UV_GAP = 0.02           # space between islands in the light map UVs

_state = {}


# ---------------------------------------------------------------- settings

def register_props():
    S = bpy.types.Scene
    P = bpy.props
    S.pd_bake_max_size = P.EnumProperty(
        name='Max light map size', default='1024',
        items=[(str(n), '%d x %d' % (n, n), '') for n in (128, 256, 512, 1024)],
        description='Largest light map one mesh can get (big meshes are capped here: softer shadows, smaller '
                    'file). Meshes get 16 pixels per metre up to this')
    S.pd_bake_samples = P.IntProperty(name='Samples', default=64, min=1, max=8192,
                                      description='Render samples per texel: more = less noise, slower')
    S.pd_bake_bounces = P.IntProperty(name='Light bounces', default=3, min=0, max=32,
                                      description='How often light bounces off surfaces (0 = direct light only)')
    S.pd_bake_gpu = P.BoolProperty(name='Use GPU', default=True,
                                   description='Bake on the graphics card if Cycles has one set up')
    S.pd_bake_use = P.BoolProperty(name='Export baked lighting', default=True,
                                   description='Export baked meshes with their baked texture (off: their own '
                                               'textures and vertex light, as before)')
    S.pd_bake_show = P.BoolProperty(name='Show Baked Lighting', default=False, update=_show_update,
                                    description='Show each baked mesh with its baked texture (texture plus light and '
                                                'shadows, as it will look in game) in Material Preview')
    S.pd_bake_status = P.StringProperty(default='')
    S.pd_bake_progress = P.FloatProperty(default=0.0, min=0.0, max=1.0, subtype='FACTOR')


PROPS = ('pd_bake_max_size', 'pd_bake_samples', 'pd_bake_bounces', 'pd_bake_gpu',
         'pd_bake_use', 'pd_bake_show', 'pd_bake_status', 'pd_bake_progress')


# ---------------------------------------------------------------- what takes part

def lights(scene):
    """The lights that light the bake: the scene Sun (Phantom Dust Lighting), every light in a Lighting collection
    and every other light that is visible in the viewport (point, spot and area lamps included)."""
    out = []
    sun = getattr(scene, 'pd_sun', None)
    if sun is not None and sun.type == 'LIGHT' and sun.name in scene.objects:
        out.append(sun)
    for c in exporter.collections_with_role(scene, 'LIGHTING'):
        out.extend(o for o in c.all_objects if o.type == 'LIGHT' and o not in out)
    out.extend(o for o in scene.objects if o.type == 'LIGHT' and o not in out and o.visible_get())
    return out


def game_ambient(scene):
    """The stage ambient colour (Phantom Dust Lighting; display values), baked into the light maps as sky light."""
    return tuple(getattr(scene, 'pd_stage_ambient', (0.424, 0.392, 0.373)))[:3]


def _see_through(ob):
    for s in ob.material_slots:
        m = s.material
        if m is None:
            continue
        st = pd_material.read(m)
        if st['diffuse'] is not None and pd_material.alpha_kind(st['diffuse']) != 'NONE':
            return True
    return False


def targets(scene):
    """(receivers to bake, casters that only cast). Receivers: stage meshes and one placement per object model."""
    from . import scene_tools
    from .objects_import import part_kind
    stage = [o for o in scene_tools.stage_meshes(scene) if o.visible_get()]
    objs, seen_mesh = [], set()
    for oc in exporter.collections_with_role(scene, 'OBJECTS'):
        for tc in oc.children:
            if getattr(tc, 'pd_preset', '') == 'JUMP_PAD':
                continue
            for o in sorted(tc.objects, key=lambda o: o.name):
                if o.type != 'MESH' or part_kind(o) or o.get('pd_no_model') or \
                        (o.parent is not None and part_kind(o.parent)):
                    continue
                objs.append(o)
    receivers, casters = [], []
    for o in stage + objs:
        if _see_through(o) or not o.data.polygons:
            casters.append(o)
        elif o in objs:
            if o.data.name in seen_mesh:                  # the model is baked once, on its first placement
                casters.append(o)
            else:
                seen_mesh.add(o.data.name)
                receivers.append(o)
        else:
            receivers.append(o)
    return receivers, casters


def baked_light(ob):
    """The light map of an object, or None."""
    return baked_image(ob, 'pd_light_image')


def baked_glow(ob):
    """The baked glow (Emission Map) of an object on its light map UVs, or None."""
    return baked_image(ob, 'pd_emit_image')


def baked_image(ob, key='pd_bake_image'):
    """The baked texture an object exports with, or None."""
    for src in (ob, getattr(ob, 'data', None)):
        name = src.get(key) if src is not None else None
        if name and name in bpy.data.images:
            return bpy.data.images[name]
    return None


# ---------------------------------------------------------------- one mesh

def bake_folder(context):
    """Where baked textures are saved: Map/pd_lightmaps/<.blend name> in the game data folder (the add-on's
    preference), else a pd_lightmaps folder next to the .blend. None if neither is known."""
    import os
    base = os.path.splitext(os.path.basename(bpy.data.filepath))[0] if bpy.data.filepath else 'unsaved'
    try:
        data = context.preferences.addons[__package__].preferences.game_data
    except (KeyError, AttributeError):
        data = ''
    if data:
        mdir = exporter.map_dir(bpy.path.abspath(data))
        if os.path.isdir(mdir):
            return os.path.join(mdir, 'pd_lightmaps', base)
    if bpy.data.filepath:
        return os.path.join(os.path.dirname(bpy.data.filepath), 'pd_lightmaps')
    return None


def _store(img, folder, exr=False):
    """Save a baked image as a PNG file in `folder` and point the image at it (no copy inside the .blend);
    packed into the .blend only if there is nowhere to save it."""
    import os
    if folder:
        try:
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, bpy.path.clean_name(img.name) + ('.exr' if exr else '.png'))
            img.filepath_raw = path
            img.file_format = 'OPEN_EXR' if exr else 'PNG'
            img.save()
            img.source = 'FILE'                           # reloads from the PNG when the .blend is opened
            img.filepath = path
            img.reload()
            img.use_fake_user = True
            return path
        except (RuntimeError, OSError) as e:
            print('Phantom Dust bake: could not save %s (%s); packed into the .blend instead' % (img.name, e))
    img.pack()
    return None


def _override(ob, selected=None):
    """A context the mesh and bake operators accept when run from the bake's timer: a 3D view, `ob` active and
    `selected` (default: ob alone) selected."""
    wm = bpy.context.window_manager
    win = bpy.context.window or (wm.windows[0] if wm.windows else None)
    area = next((a for a in win.screen.areas if a.type == 'VIEW_3D'), None) if win else None
    region = next((r for r in area.regions if r.type == 'WINDOW'), None) if area else None
    sel = list(selected) if selected else [ob]
    kw = dict(active_object=ob, object=ob, selected_objects=sel, selected_editable_objects=sel)
    if win is not None:
        kw['window'] = win
        kw['screen'] = win.screen
    if area is not None:
        kw.update(area=area, region=region)
    return kw


def keep_texture_uv_active(me):
    """Image nodes without a UV Map node use the active render UV map: it must never be the light map's, or the
    texture is laid out like the light map. Puts the texture UV map back (returns True if it had to)."""
    cur = next((l for l in me.uv_layers if l.active_render), None)
    if cur is None or cur.name != UV_NAME:
        return False
    other = next((l for l in me.uv_layers if l.name != UV_NAME), None)
    if other is None:
        return False
    me.uv_layers.active = other
    other.active_render = True
    return True


def _texture_uv(me):
    """The UV map the textures use (never the lightmap's)."""
    return next((l for l in me.uv_layers if l.active_render and l.name != UV_NAME), None) or \
        next((l for l in me.uv_layers if l.name != UV_NAME), None)


def _surface_area(ob):
    sx, sy, sz = ob.matrix_world.to_scale()
    return sum(p.area for p in ob.data.polygons) * abs(sx * sy * sz) ** (2.0 / 3.0)


def light_map_size(ob, scene=None):
    """Light map size for a mesh: its surface at DENSITY pixels per metre, a power of two from 32 to the
    scene's Max light map size."""
    side = math.sqrt(_surface_area(ob) / UV_FILL) * DENSITY
    top = int(getattr(scene, 'pd_bake_max_size', MAX_SIZE)) if scene is not None else MAX_SIZE
    return min(top, 1 << max(5, int(math.ceil(math.log2(max(side, 1.0)) - 0.25))))


def _ensure_uv(ob, scene):
    """Make the mesh's light map UVs (PD_LightUV, Smart UV Project: every face its own spot). The texture UVs
    stay as they are and stay active."""
    me = ob.data
    tex_uv = _texture_uv(me)
    tex_name = tex_uv.name if tex_uv is not None else None
    if me.uv_layers.get(UV_NAME) is None:
        if len(me.uv_layers) >= 8:
            raise RuntimeError('%s has no room for another UV map' % ob.name)
        me.uv_layers.new(name=UV_NAME)
    me.uv_layers.active = me.uv_layers[UV_NAME]
    view_layer = bpy.context.view_layer
    for o in view_layer.objects:
        o.select_set(False)
    ob.select_set(True)
    view_layer.objects.active = ob
    with bpy.context.temp_override(**_override(ob)):
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            bpy.ops.mesh.reveal()
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=UV_GAP, area_weight=0.0,
                                     correct_aspect=True, scale_to_bounds=False)
        finally:
            bpy.ops.object.mode_set(mode='OBJECT')
    me = ob.data
    co = [0.0] * (2 * len(me.uv_layers[UV_NAME].data))
    me.uv_layers[UV_NAME].data.foreach_get('uv', co)
    if not any(co):
        raise RuntimeError('the light map unwrap came out empty')
    if tex_name and tex_name in me.uv_layers:               # the textures keep their own UV map
        me.uv_layers.active = me.uv_layers[tex_name]
        me.uv_layers[tex_name].active_render = True
    keep_texture_uv_active(me)


def _image_for(ob, size, prefix=IMAGE_PREFIX):
    name = prefix + ob.name
    img = bpy.data.images.get(name)
    if img is not None:                                   # a fresh image every bake (the old one is a file now)
        bpy.data.images.remove(img)
    light = prefix == LIGHT_PREFIX                        # light can be brighter than white: a float image
    img = bpy.data.images.new(name, size, size, alpha=False, float_buffer=light)
    if not light:
        img.colorspace_settings.name = 'sRGB'
    img.use_fake_user = True
    return img


# ---------------------------------------------------------------- showing the bake in the viewport

VIEW_PREFIX = 'PDBakeView_'


def _view_material(img):
    """A material showing a baked texture as is (emission) on the lightmap UVs."""
    name = VIEW_PREFIX + img.name
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        uv = nt.nodes.new('ShaderNodeUVMap')
        uv.uv_map = UV_NAME
        uv.location = (-600, 0)
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.location = (-350, 0)
        em = nt.nodes.new('ShaderNodeEmission')
        em.location = (-50, 0)
        out = nt.nodes.new('ShaderNodeOutputMaterial')
        out.location = (200, 0)
        nt.links.new(uv.outputs['UV'], tex.inputs['Vector'])
        nt.links.new(tex.outputs['Color'], em.inputs['Color'])
        nt.links.new(em.outputs['Emission'], out.inputs['Surface'])
    tex = next(n for n in m.node_tree.nodes if n.type == 'TEX_IMAGE')
    tex.image = img
    return m


def is_view_material(m):
    return m is not None and m.name.startswith(VIEW_PREFIX)


def _lit_copy(ob, i, m, light):
    """A copy of a PD material showing the texture times this object's light map (Light Map input)."""
    name = '%s%s_%d' % (VIEW_PREFIX, ob.name, i)
    old = bpy.data.materials.get(name)
    if old is not None:
        bpy.data.materials.remove(old)
    c = m.copy()
    c.name = name
    c['pd_view_of'] = m.name                        # the material panel edits the original
    nt = c.node_tree
    g = pd_material.group_node(c)
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = light
    tex.location = (g.location.x - 400, g.location.y - 700)
    uv = nt.nodes.new('ShaderNodeUVMap')
    uv.uv_map = UV_NAME
    uv.location = (tex.location.x - 250, tex.location.y)
    nt.links.new(uv.outputs['UV'], tex.inputs['Vector'])
    nt.links.new(tex.outputs['Color'], g.inputs['Light Map'])
    g.inputs['Light Map Amount'].default_value = 1.0
    return c


def show_baked(scene, on):
    """Show every baked mesh lit by its bake (object-level material slots, the mesh keeps its own) or back.
    PD materials show their own texture times the light map, sharp; other materials the exported texture."""
    pd_material.ensure_group()
    for ob in scene.objects:
        if ob.type != 'MESH':
            continue
        light = baked_light(ob) if on else None
        img = light
        has_uv = ob.data.uv_layers.get(UV_NAME) is not None
        if on and has_uv:
            keep_texture_uv_active(ob.data)
        for i, slot in enumerate(ob.material_slots):
            if slot.link == 'OBJECT' and is_view_material(slot.material):
                old = slot.material
                slot.material = None
                slot.link = 'DATA'
                if old.users == 0 and old.name.startswith(VIEW_PREFIX + ob.name):
                    bpy.data.materials.remove(old)
            if not on or not has_uv:
                continue
            m = slot.material
            if light is not None and pd_material.group_node(m) is not None and \
                    'Light Map' in pd_material.group_node(m).inputs:
                view = _lit_copy(ob, i, m, light)
            elif img is not None:
                view = _view_material(img)
            else:
                continue
            slot.link = 'OBJECT'
            slot.material = view


def _show_update(self, context):
    show_baked(context.scene, self.pd_bake_show)


# ---------------------------------------------------------------- stand-in materials for the bake

def _texture_of(m):
    if m is None:
        return None
    try:
        return pd_material.read(m).get('diffuse') or pd_material.first_image(m)
    except Exception:
        return None


def _colour_of(m):
    if m is None:
        return (0.8, 0.8, 0.8, 1.0)
    g = pd_material.group_node(m)
    if g is not None and 'Diffuse' in g.inputs:
        c = g.inputs['Diffuse'].default_value
        t = g.inputs['Diffuse Color'].default_value if 'Diffuse Color' in g.inputs else (1.0, 1.0, 1.0, 1.0)
        return tuple(c[k] * t[k] for k in range(3)) + (1.0,)
    if m.use_nodes and m.node_tree:
        bs = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bs is not None:
            return tuple(bs.inputs['Base Color'].default_value)
    return tuple(m.diffuse_color)


def _glow_colour(nt, ob, m):
    """Nodes giving a material's glow (Emission Map x Emission Strength) on the texture UVs, or None."""
    if m is None or not pd_material.glows(m):
        return None
    e = pd_material.emission(m)
    if e['emission'] is not None:
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = e['emission']
        tex.location = (-400, -300)
        tuv = _texture_uv(ob.data)
        if tuv is not None:
            uvn = nt.nodes.new('ShaderNodeUVMap')
            uvn.uv_map = tuv.name
            uvn.location = (-650, -300)
            nt.links.new(uvn.outputs['UV'], tex.inputs['Vector'])
        col = tex.outputs['Color']
        if tuple(e['emission_tint']) != (1.0, 1.0, 1.0):          # Emission Color
            mul = nt.nodes.new('ShaderNodeMix')
            mul.data_type, mul.blend_type = 'RGBA', 'MULTIPLY'
            mul.inputs['Factor'].default_value = 1.0
            mul.location = (-250, -300)
            nt.links.new(col, mul.inputs[6])
            mul.inputs[7].default_value = tuple(e['emission_tint']) + (1.0,)
            col = mul.outputs[2]
    else:
        rgb = nt.nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value = tuple(e['emission_colour']) + (1.0,)
        rgb.location = (-400, -300)
        col = rgb.outputs[0]
    em = nt.nodes.new('ShaderNodeEmission')
    em.location = (-100, -300)
    em.inputs['Strength'].default_value = e['emission_strength']
    nt.links.new(col, em.inputs['Color'])
    return em


def _stand_in(ob, m, i, glow_only=False):
    """A temporary material in Blender's own shaders for one slot: a Diffuse BSDF with the slot's texture (the
    texture only tints the bounced light) plus the slot's glow, so glowing surfaces light their surroundings.
    glow_only: the glow alone (black where none), for baking the glow into the light map's alpha."""
    tmp = bpy.data.materials.new('%s%s_%d' % (TMP_PREFIX, ob.name, i))
    tmp.use_nodes = True
    nt = tmp.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    out.location = (400, 0)
    em = _glow_colour(nt, ob, m)
    if glow_only:
        if em is None:
            em = nt.nodes.new('ShaderNodeEmission')
            em.inputs['Color'].default_value = (0.0, 0.0, 0.0, 1.0)
        nt.links.new(em.outputs['Emission'], out.inputs['Surface'])
        return tmp
    img = _texture_of(m)
    if img is not None:
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = img
        tex.location = (-400, 150)
        tuv = _texture_uv(ob.data)
        if tuv is not None:
            uvn = nt.nodes.new('ShaderNodeUVMap')
            uvn.uv_map = tuv.name
            uvn.location = (-650, 150)
            nt.links.new(uvn.outputs['UV'], tex.inputs['Vector'])
        colour = tex.outputs['Color']
    else:
        rgb = nt.nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value = _colour_of(m)[:3] + (1.0,)
        rgb.location = (-400, 150)
        colour = rgb.outputs[0]
    sh = nt.nodes.new('ShaderNodeBsdfDiffuse')
    sh.location = (-100, 150)
    nt.links.new(colour, sh.inputs['Color'])
    if em is None:
        nt.links.new(sh.outputs['BSDF'], out.inputs['Surface'])
    else:
        add = nt.nodes.new('ShaderNodeAddShader')
        add.location = (150, 0)
        nt.links.new(sh.outputs['BSDF'], add.inputs[0])
        nt.links.new(em.outputs['Emission'], add.inputs[1])
        nt.links.new(add.outputs['Shader'], out.inputs['Surface'])
    return tmp


def _target(tmp, img):
    n = tmp.node_tree.nodes.new('ShaderNodeTexImage')
    n.name = n.label = NODE_NAME
    n.image = img
    n.location = (-900, -600)
    for other in tmp.node_tree.nodes:
        other.select = False
    n.select = True
    tmp.node_tree.nodes.active = n


def _swap(saved, ob, i, slot, tmp):
    """Put a temporary material in a slot, remembering what was there (once)."""
    key = (ob.name, i)
    if key not in saved['slot_keys']:
        saved['slot_keys'].add(key)
        saved['slots'].append((ob.name, i, slot.link, slot.material.name if slot.link == 'OBJECT' and slot.material else None))
    slot.link = 'OBJECT'
    slot.material = tmp


# ---------------------------------------------------------------- the bake operator

TMP_PREFIX = 'PDBakeTmp_'


class PDSTAGE_OT_bake_light(bpy.types.Operator):
    """Bake the Lighting collection's sun and lamps (shadows and bounced light between all meshes) into a
    texture per stage mesh and object model, in one Cycles bake of the whole scene. Everything that is not a
    Visual, an Object or a light is hidden while it bakes. On export each baked mesh uses its baked texture"""
    bl_idname = 'pdstage.bake_light'
    bl_label = 'Bake Lighting'

    _timer = None

    def invoke(self, context, event):
        scene = context.scene
        fixed = [o.name for o in scene.objects if o.type == 'MESH' and keep_texture_uv_active(o.data)]
        if fixed:
            print('Phantom Dust bake: the light map UVs were the active UV map of %s; set back to the texture UVs'
                  % ', '.join(fixed))
        if bpy.data.filepath and not _state:                 # save first (waits until written)
            try:
                bpy.ops.wm.save_mainfile()
            except RuntimeError as e:
                self.report({'WARNING'}, 'Could not save before baking: %s' % e)
        if _state:
            if time.time() - _state.get('alive', 0) < 3.0:
                self.report({'WARNING'}, 'A bake is already running')
                return {'CANCELLED'}
            self._timer = None                               # a bake that stopped on an error: put the scene back
            try:
                self._finish(context, False)
            except Exception:
                import traceback
                traceback.print_exc()
            _state.clear()
        receivers, casters = targets(scene)
        if not receivers:
            self.report({'ERROR'}, 'Nothing to bake: no visible meshes under Visuals or Objects')
            return {'CANCELLED'}
        if context.object is not None and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if scene.pd_bake_show:
            scene.pd_bake_show = False                       # bake through the real materials
        sizes = {o.name: light_map_size(o, scene) for o in receivers}
        print('Phantom Dust bake: %d meshes, %.1f megapixels of light map' % (
            len(sizes), sum(z * z for z in sizes.values()) / 1e6))
        _state.update(alive=time.time(), phase='uv', todo=[o.name for o in receivers], k=0, sizes=sizes, errors=[],
                      casters=[o.name for o in casters], start=time.time())
        scene.pd_bake_progress = 0.0
        scene.pd_bake_status = 'Preparing lightmap UVs...'
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    # -- phase 1: a lightmap UV map per mesh (one per timer tick: the unwrap needs edit mode)
    def _uv_step(self, context):
        scene = context.scene
        todo, k = _state['todo'], _state['k']
        ob = bpy.data.objects.get(todo[k])
        if ob is not None:
            try:
                _ensure_uv(ob, scene)
            except RuntimeError as e:
                _state['errors'].append('%s: %s' % (ob.name, e))
        _state['k'] = k + 1
        scene.pd_bake_progress = 0.1 * _state['k'] / len(todo)
        scene.pd_bake_status = 'Lightmap UVs %d / %d' % (_state['k'], len(todo))

    # -- phase 2: the whole scene in one bake
    def _start_bake(self, context):
        scene = context.scene
        failed = {e.split(':')[0] for e in _state['errors']}
        receivers = [bpy.data.objects[n] for n in _state['todo'] if n in bpy.data.objects and n not in failed]
        casters = [bpy.data.objects[n] for n in _state['casters'] if n in bpy.data.objects]
        if not receivers:
            return False
        keep = set(receivers) | set(casters) | set(lights(scene))
        saved = dict(engine=scene.render.engine, samples=scene.cycles.samples,
                     max_b=scene.cycles.max_bounces, diff_b=scene.cycles.diffuse_bounces,
                     device=scene.cycles.device, world=scene.world,
                     hidden={o.name: o.hide_render for o in scene.objects},
                     coll_hidden={},
                     sel=[o.name for o in context.view_layer.objects if o.select_get()],
                     active=context.view_layer.objects.active.name if context.view_layer.objects.active else None,
                     slots=[])
        _state['saved'] = saved
        # hide everything that is not a visual, an object or a light; show the ones that are (also their
        # collections, if those are switched off for renders)
        for o in scene.objects:
            o.hide_render = o not in keep
        # what else can keep a mesh out of the render: a parent collection switched off for renders (anywhere up
        # the tree), the object's ray visibility (Object > Visibility) or holdout. All on for the bake.
        parents = {}
        for c in [scene.collection] + list(scene.collection.children_recursive):
            for ch in c.children:
                parents[ch.name] = c
        flags = ('visible_camera', 'visible_diffuse', 'visible_glossy', 'visible_shadow', 'visible_transmission')
        saved['rays'] = {}
        for o in keep:
            for c in o.users_collection:
                while c is not None:
                    if c.hide_render and c.name not in saved['coll_hidden']:
                        saved['coll_hidden'][c.name] = True
                        c.hide_render = False
                    c = parents.get(c.name)
            if o.type == 'MESH':
                saved['rays'][o.name] = tuple(getattr(o, f, True) for f in flags) + (getattr(o, 'is_holdout', False),)
                for f in flags:
                    if hasattr(o, f):
                        setattr(o, f, True)
                if hasattr(o, 'is_holdout'):
                    o.is_holdout = False
        scene.render.engine = 'CYCLES'
        scene.cycles.samples = scene.pd_bake_samples
        scene.cycles.max_bounces = max(scene.pd_bake_bounces, 1)
        scene.cycles.diffuse_bounces = scene.pd_bake_bounces
        if scene.pd_bake_gpu:
            try:
                scene.cycles.device = 'GPU'
            except TypeError:
                pass
        w = bpy.data.worlds.get('PD Bake Ambient') or bpy.data.worlds.new('PD Bake Ambient')
        w.use_nodes = True
        bg = next((n for n in w.node_tree.nodes if n.type == 'BACKGROUND'), None)
        if bg is not None:                                   # no ambient: the game adds the stage ambient itself
            bg.inputs['Color'].default_value = (0.0, 0.0, 0.0, 1.0)
            bg.inputs['Strength'].default_value = 0.0
        scene.world = w
        sun = next((o for o in lights(scene) if o.data.type == 'SUN'), None)   # the stage light colour on the Sun
        if sun is not None:
            saved['sun_colour'] = (sun.name, tuple(sun.data.color), sun.data.energy)
            sun.data.color = tuple(getattr(scene, 'pd_stage_light', sun.data.color))
            # brightness: the sun colour (Phantom Dust Lighting) times the Sun's own Strength (1 = as the game)
        pd_material.set_preview(False)                       # Blender's own shading, not the game look
        # every mesh bakes through stand-ins in Blender's own shaders (object-level slots, the mesh keeps its
        # materials): a plain diffuse surface with its texture. Receivers bake the light alone into a light map.
        saved['slot_keys'] = set()
        images = {}
        for ob in receivers + [c for c in casters if c not in receivers]:
            img = None
            if ob in receivers:
                img = _image_for(ob, _state['sizes'][ob.name], LIGHT_PREFIX)
                images[ob.name] = img.name
            for i, slot in enumerate(ob.material_slots):
                tmp = _stand_in(ob, slot.material, i)
                if img is not None:
                    _target(tmp, img)
                _swap(saved, ob, i, slot, tmp)
        _state['images'] = images
        _state['clean'] = [n for n in images.values() if not bpy.data.images[n].is_dirty]   # counted as they bake
        view_layer = context.view_layer
        for o in view_layer.objects:
            o.select_set(False)
        for o in receivers:
            o.select_set(True)
        view_layer.objects.active = receivers[0]
        bpy.app.handlers.object_bake_complete.append(_on_done)
        bpy.app.handlers.object_bake_cancel.append(_on_cancel)
        print('Phantom Dust bake: %d meshes, lights: %s, ambient %s' % (
            len(receivers), ', '.join('%s (%s, strength %.1f)' % (o.name, o.data.type, o.data.energy)
                                     for o in lights(scene)) or 'none',
            tuple(round(x, 2) for x in getattr(scene, 'pd_stage_ambient', (0, 0, 0)))))
        for o in lights(scene):
            if o.data.type == 'SUN':
                import mathutils
                d = (o.matrix_world.to_3x3() @ mathutils.Vector((0.0, 0.0, -1.0))).normalized()
                print('Phantom Dust bake: sun %s shines %s (%.0f degrees %s the horizon)' % (
                    o.name, 'DOWN' if d.z < 0 else 'UP, from below: floors get no sun',
                    abs(math.degrees(math.asin(max(-1.0, min(1.0, -d.z))))), 'above' if d.z < 0 else 'below'))
        _state['phase'] = 'bake'
        _state['bake_start'] = time.time()
        _state['n'] = len(receivers)
        scene.pd_bake_status = 'Baking %d meshes together (progress bar at the bottom)...' % len(receivers)
        try:
            with bpy.context.temp_override(**_override(receivers[0], receivers)):
                res = bpy.ops.object.bake('INVOKE_DEFAULT', type='DIFFUSE',
                                          pass_filter={'DIRECT', 'INDIRECT'}, target='IMAGE_TEXTURES',
                                          margin=MARGIN, use_clear=True, uv_layer=UV_NAME)
        except RuntimeError as e:
            _state['errors'].append('bake: %s' % e)
            res = {'CANCELLED'}
        if 'CANCELLED' in res:
            _state['result'] = 'cancel'
        return True

    def modal(self, context, event):
        if event.type != 'TIMER':
            if event.type == 'ESC' and _state.get('phase') == 'uv':
                _state['result'] = 'cancel'
            else:
                return {'PASS_THROUGH'}
        scene = context.scene
        phase = _state.get('phase')
        _state['alive'] = time.time()
        if _state.get('result'):
            ok = _state['result'] == 'done'
            self._finish(context, ok)
            return {'FINISHED'} if ok else {'CANCELLED'}
        if phase == 'uv':
            try:
                if _state['k'] < len(_state['todo']):
                    self._uv_step(context)
                elif not self._start_bake(context):
                    _state['result'] = 'cancel'
            except Exception as e:                           # an error: put the scene back on the next tick
                import traceback
                traceback.print_exc()
                _state.setdefault('errors', []).append('bake: %s' % e)
                _state['result'] = 'cancel'
        elif phase == 'bake':                                # no scene changes while Blender's bake job runs
            took = time.time() - _state['bake_start']
            # Blender writes each mesh's image as soon as that mesh is baked: count the images that changed
            done = sum(1 for n in _state['clean'] if n in bpy.data.images and bpy.data.images[n].is_dirty)
            total = _state['n']
            _state['done'] = done
            # the time shown and the estimate change every 5 seconds only (the count right away)
            now = time.time()
            if now - _state.get('shown_at', 0) >= 5.0 or 'shown' not in _state:
                _state['shown_at'] = now
                left = ''
                if 0 < done < total:
                    left = ', about %s left' % _clock(took / done * (total - done))
                _state['shown'] = '%s%s' % (_clock(took), left)
            _state['status'] = 'Baking %d / %d  -  %s' % (done, total, _state['shown'])
        for area in context.screen.areas if context.screen else ():
            area.tag_redraw()
        return {'RUNNING_MODAL'}

    @staticmethod
    def _original(saved, ob, i):
        """The material a slot had before the bake."""
        for name, k, link, mat in saved['slots']:
            if name == ob.name and k == i:
                if link == 'OBJECT':
                    return bpy.data.materials.get(mat) if mat else None
                return ob.data.materials[i] if i < len(ob.data.materials) else None
        return ob.material_slots[i].material

    def _glow_pass(self, context):
        """Glowing materials (Emission Map): their glow baked onto the light map UVs (PDEmit_ images, a quick
        one-sample emission bake), which the export stores in the light map's alpha. {object name: image}."""
        scene = context.scene
        saved = _state['saved']
        out, obs = {}, []
        for name, lname in _state.get('images', {}).items():
            ob, light = bpy.data.objects.get(name), bpy.data.images.get(lname)
            if ob is None or light is None:
                continue
            mats = [self._original(saved, ob, i) for i in range(len(ob.material_slots))]
            if not any(m is not None and pd_material.glows(m) for m in mats):
                continue
            name_img = 'PDEmit_' + ob.name
            old = bpy.data.images.get(name_img)
            if old is not None:
                bpy.data.images.remove(old)
            img = bpy.data.images.new(name_img, light.size[0], light.size[1], alpha=False, float_buffer=True)
            for i, slot in enumerate(ob.material_slots):
                tmp = _stand_in(ob, mats[i], i, glow_only=True)
                _target(tmp, img)
                slot.material = tmp
            out[name] = img.name
            obs.append(ob)
        if not obs:
            return out
        scene.cycles.samples = 1
        with bpy.context.temp_override(**_override(obs[0], obs)):
            bpy.ops.object.bake('EXEC_DEFAULT', type='EMIT', target='IMAGE_TEXTURES', margin=MARGIN,
                                use_clear=True, uv_layer=UV_NAME)
        print('Phantom Dust bake: glow baked for %d meshes' % len(obs))
        return out

    def _finish(self, context, ok):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
        for lst, fn in ((bpy.app.handlers.object_bake_complete, _on_done),
                        (bpy.app.handlers.object_bake_cancel, _on_cancel)):
            while fn in lst:
                lst.remove(fn)
        scene = context.scene
        s = _state.get('saved')
        glow = {}
        if ok and s:
            try:
                glow = self._glow_pass(context)
            except Exception as e:                          # never leave the scene in its bake state
                _state.setdefault('errors', []).append('glow: %s' % e)
        if s:
            for name, i, link, mat in s['slots']:            # the objects' own materials back
                ob = bpy.data.objects.get(name)
                if ob is None or i >= len(ob.material_slots):
                    continue
                slot = ob.material_slots[i]
                slot.material = None
                slot.link = link
                if link == 'OBJECT' and mat:
                    slot.material = bpy.data.materials.get(mat)
            for m in [m for m in bpy.data.materials if m.name.startswith(TMP_PREFIX)]:
                bpy.data.materials.remove(m)
            scene.render.engine = s['engine']
            scene.cycles.samples = s['samples']
            scene.cycles.max_bounces = s['max_b']
            scene.cycles.diffuse_bounces = s['diff_b']
            try:
                scene.cycles.device = s['device']
            except TypeError:
                pass
            scene.world = s['world']
            if s.get('sun_colour'):
                sun = bpy.data.objects.get(s['sun_colour'][0])
                if sun is not None and sun.type == 'LIGHT':
                    sun.data.color = s['sun_colour'][1]
                    sun.data.energy = s['sun_colour'][2]
            for o in scene.objects:                         # everything hidden for the bake shown again
                if o.name in s['hidden']:
                    o.hide_render = s['hidden'][o.name]
            flags = ('visible_camera', 'visible_diffuse', 'visible_glossy', 'visible_shadow', 'visible_transmission')
            for name, vals in s.get('rays', {}).items():
                o = bpy.data.objects.get(name)
                if o is None:
                    continue
                for f, v in zip(flags, vals[:5]):
                    if hasattr(o, f):
                        setattr(o, f, v)
                if hasattr(o, 'is_holdout'):
                    o.is_holdout = vals[5]
            for cname in s['coll_hidden']:
                c = bpy.data.collections.get(cname)
                if c is not None:
                    c.hide_render = True
            for o in context.view_layer.objects:
                o.select_set(o.name in s['sel'])
            if s['active'] and s['active'] in bpy.data.objects:
                context.view_layer.objects.active = bpy.data.objects[s['active']]
            pd_material.set_preview(True)                     # the preview follows the scene again
            pd_material.sync_preview(force=True)
        n = 0
        folder = bake_folder(context) if ok else None
        black = []
        if ok:
            import numpy as np
            for name, img_name in _state.get('images', {}).items():
                ob, img = bpy.data.objects.get(name), bpy.data.images.get(img_name)
                if ob is None or img is None:
                    continue
                px = np.empty(len(img.pixels), dtype=np.float32)
                img.pixels.foreach_get(px)
                if px.reshape(-1, 4)[:, :3].max() <= 0.0:       # no light reached it at all
                    black.append(name)
                _store(img, folder, exr=True)                   # files, not inside the .blend
                ob['pd_light_image'] = img.name
                gimg = bpy.data.images.get(glow.get(name, ''))
                for src in (ob, ob.data):
                    if 'pd_emit_image' in src:
                        del src['pd_emit_image']
                if gimg is not None:
                    _store(gimg, folder, exr=True)
                    ob['pd_emit_image'] = gimg.name
                    if ob.data.users > 1:
                        ob.data['pd_emit_image'] = gimg.name
                if 'pd_bake_image' in ob:                       # the older texture x light bake
                    del ob['pd_bake_image']
                if ob.data.users > 1:                           # object placements share their model
                    ob.data['pd_light_image'] = img.name
                n += 1
        if ok and n:                                        # meshes left out this time drop an old bake
            baked_now = set(_state.get('images', {}))
            shared = {bpy.data.objects[k].data.name for k in baked_now if k in bpy.data.objects}
            for o in scene.objects:
                if o.type == 'MESH' and o.name not in baked_now and o.data.name not in shared:
                    for key in ('pd_bake_image', 'pd_light_image', 'pd_emit_image'):
                        for src in (o, o.data):
                            if key in src:
                                del src[key]
        errors = _state.get('errors', [])
        took = time.time() - _state.get('start', time.time())
        scene.pd_bake_progress = 1.0 if ok else 0.0
        scene.pd_bake_status = ('Baked %d meshes in %s%s' % (n, _clock(took), ', saved in %s' % folder if folder else '')
                                if ok else 'Bake cancelled') + (
            ', %d left out (see System Console)' % len(errors) if errors else '')
        for e in errors:
            print('Phantom Dust bake:', e)
        if black:
            print('Phantom Dust bake: %d meshes came out completely black:' % len(black))
            for name in sorted(black):
                ob = bpy.data.objects.get(name)
                if ob is None:
                    continue
                mats = []
                for slot in ob.material_slots:
                    m = slot.material
                    if m is None:
                        mats.append('(none)')
                        continue
                    bs = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if m.use_nodes else None
                    info = 'PD material' if pd_material.group_node(m) else (
                        'Principled, base %s, metallic %.2f' % (
                            'texture' if bs.inputs['Base Color'].is_linked else
                            tuple(round(x, 2) for x in bs.inputs['Base Color'].default_value[:3]),
                            bs.inputs['Metallic'].default_value) if bs is not None else 'other shader')
                    mats.append('%s: %s' % (m.name, info))
                print('   %s  [%s]  parent collections: %s' % (name, '; '.join(mats) or 'no materials',
                                                               ', '.join(c.name for c in ob.users_collection)))
            scene.pd_bake_status += ', %d completely black (see System Console)' % len(black)
        _state.clear()
        if ok and n:
            print('Phantom Dust bake: done, %d light maps saved.' % n)
            scene.pd_bake_show = True
        for area in context.screen.areas if context.screen else ():
            area.tag_redraw()


def _on_done(*_args):
    _state['result'] = 'done'


def _on_cancel(*_args):
    _state['result'] = 'cancel'


def _clock(sec):
    sec = int(round(sec))
    return '%d:%02d min' % (sec // 60, sec % 60) if sec >= 60 else '%d s' % sec


class PDSTAGE_OT_clear_bake(bpy.types.Operator):
    """Remove the baked lighting: the meshes export with their own textures and vertex light again (the
    PD_LightUV maps stay, so the next bake is faster)"""
    bl_idname = 'pdstage.clear_light'
    bl_label = 'Clear Lighting'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        context.scene.pd_bake_show = False
        n = 0
        for src in list(bpy.data.objects) + list(bpy.data.meshes):
            for key in ('pd_bake_image', 'pd_light_image', 'pd_emit_image'):
                if key in src:
                    del src[key]
                    n += key == 'pd_light_image'
        for m in [m for m in bpy.data.materials if m.name.startswith(VIEW_PREFIX)]:
            bpy.data.materials.remove(m)
        for img in [i for i in bpy.data.images if i.name.startswith((IMAGE_PREFIX, LIGHT_PREFIX, 'PDEmit_'))]:
            bpy.data.images.remove(img)
        context.scene.pd_bake_status = ''
        context.scene.pd_bake_progress = 0.0
        self.report({'INFO'}, 'Baked lighting removed (%d)' % n)
        return {'FINISHED'}


class PDSTAGE_OT_add_lighting(bpy.types.Operator):
    """Make a Lighting collection for Bake Lighting and put the scene's suns in it (or a new sun if there is
    none). Lamps you add to it light the bake too"""
    bl_idname = 'pdstage.add_lighting'
    bl_label = 'Add Lighting Collection'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        coll = bpy.data.collections.new('Lighting')
        scene.collection.children.link(coll)
        coll.pd_role = 'LIGHTING'
        suns = [o for o in scene.objects if o.type == 'LIGHT' and o.data.type == 'SUN']
        if not suns:
            sun = bpy.data.objects.new('Sun', bpy.data.lights.new('Sun', 'SUN'))
            sun.data.energy = 1.0
            sun.location = (0.0, 0.0, 20.0)
            sun.rotation_euler = (math.radians(50), math.radians(15), math.radians(35))
            suns = [sun]
            if hasattr(scene, 'pd_sun'):
                scene.pd_sun = sun
        for o in suns:
            for c in list(o.users_collection):
                c.objects.unlink(o)
            coll.objects.link(o)
        self.report({'INFO'}, 'Lighting collection made with %d sun%s' % (len(suns), '' if len(suns) == 1 else 's'))
        return {'FINISHED'}


def draw(layout, context):
    """The Light section of the sidebar."""
    s = context.scene
    col = layout.column(align=True)
    row = col.row(align=True)
    row.enabled = not _state
    row.operator(PDSTAGE_OT_bake_light.bl_idname, icon='LIGHT_SUN')
    row.operator(PDSTAGE_OT_clear_bake.bl_idname, text='', icon='X')
    if _state:
        if _state.get('phase') == 'bake':
            col.progress(factor=_state.get('done', 0) / max(1, _state.get('n', 1)),
                         text=_state.get('status') or 'Baking...')
        else:
            col.progress(factor=s.pd_bake_progress, text=s.pd_bake_status or 'Baking...')
    elif s.pd_bake_status:
        col.label(text=s.pd_bake_status, icon='CHECKMARK')
    if not exporter.collections_with_role(s, 'LIGHTING'):
        col.operator(PDSTAGE_OT_add_lighting.bl_idname, icon='LIGHT')
    if any(baked_light(o) is not None for o in s.objects if o.type == 'MESH'):
        col.prop(s, 'pd_bake_show', icon='SHADING_TEXTURE')
    box = layout.box()
    box.prop(s, 'pd_bake_use')
    sub = box.column(align=True)
    sub.prop(s, 'pd_bake_max_size')
    sub.prop(s, 'pd_bake_samples')
    sub.prop(s, 'pd_bake_bounces')
    sub.prop(s, 'pd_bake_gpu')
    baked = sum(1 for o in s.objects if o.type == 'MESH' and baked_light(o) is not None)
    if baked:
        sub.label(text='%d meshes have baked lighting' % baked, icon='INFO')


classes = (PDSTAGE_OT_bake_light, PDSTAGE_OT_clear_bake, PDSTAGE_OT_add_lighting)


def register():
    register_props()
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    for p in PROPS:
        if hasattr(bpy.types.Scene, p):
            delattr(bpy.types.Scene, p)

