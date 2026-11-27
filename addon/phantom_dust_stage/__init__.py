"""Phantom Dust Stage: build maps in Blender and export them to the game's format.

- Collection Properties > Phantom Dust: give a collection a role (Colliders, Spawn Points) and, for collision,
  a surface type. Objects inside need no tags.
- File > Export > Phantom Dust Stage (.dat): pick the map slot to replace and write a new .dat.
- File > Import > Phantom Dust Stage (.dat): optional, loads an existing map as a starting point.
- Material Properties > Phantom Dust Material: the PD Stage Shader, with only the settings the game's stage
  shaders have (texture, normal map, reflection map, highlight colour and shininess, shine mask, baked light).
"""
import os

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import convert as cv
from . import characters_ui, exporter, guides, importer, lightbake, navmesh, pd_material, release, realtime, restricted, scene_tools, sky, surfaces
from ._lib import effects_build, objects_build
from .objects_import import part_kind

PRESET_ITEMS = [(k, objects_build.LABELS.get(k, k.title()), v[2])
                for k, v in objects_build.PRESETS.items()]
EFFECT_ITEMS = [(k, v[2], 'Works in every map', v[3]) for k, v in effects_build.PRESETS.items()] + [
    ('GAME', "Game original's (imported)", 'Each empty keeps the effect entry it was imported with. Only works '
     'in the map it came from (its textures and sounds live there)', 99)]

GAME_ORIGINAL_ITEMS = [(k, '%s (%s)' % (name, k), 'Replace %s' % name) for k, name in cv.GAME_ORIGINALS]
# Import also offers each map's second object layout ("variant": jump pads on or off, bridges already broken...):
# the game's placement table for layout 2 (slot 2), where the map has one (all scanned, 2026-11-18).
VARIANT_MAPS = {'st02', 'st12', 'st22', 'st03', 'st13', 'st23', 'st04', 'st14', 'st05', 'st15', 'st25',
                'st06', 'st16', 'st26'}
IMPORT_ITEMS = []
for _k, _name in cv.GAME_ORIGINALS:
    IMPORT_ITEMS.append((_k, '%s (%s)' % (_name, _k), 'Import %s' % _name))
    if _k in VARIANT_MAPS:
        IMPORT_ITEMS.append((_k + ':v2', '%s, variant 2' % _name,
                             'Import %s with its second object layout (jump pads, broken bridges...)' % _name))


class PDSTAGE_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    game_data: StringProperty(
        name='Game data folder', subtype='DIR_PATH',
        description="Phantom Dust's Assets\\Data folder (contains Map\\st04.dat and so on)")

    github_token: StringProperty(
        name='GitHub token', subtype='PASSWORD',
        description='For Release > Publish to GitHub: a fine-grained personal access token with "Contents: read and '
                    'write" on your mod repositories (github.com > Settings > Developer settings). Saved in Blender\'s '
                    'preferences on this computer. Empty: the GH_TOKEN / GITHUB_TOKEN environment variable')

    def draw(self, context):
        self.layout.prop(self, 'game_data')
        self.layout.prop(self, 'github_token')


def _prefs_game_data(context):
    try:
        return context.preferences.addons[__package__].preferences.game_data
    except (KeyError, AttributeError):
        return ''


class PDSTAGE_OT_import(bpy.types.Operator, ImportHelper):
    """Import a Phantom Dust game original map (Assets/Data/Map/stNN.dat) as a starting point"""
    bl_idname = 'import_scene.phantom_dust_stage'
    bl_label = 'Import Phantom Dust Stage'
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = '.dat'
    filter_glob: StringProperty(default='st*.dat', options={'HIDDEN'})
    scale: FloatProperty(name='Scale', description='Blender units per game unit', default=cv.DEFAULT_SCALE, min=0.0001)
    collision: BoolProperty(name='Collision', default=True)
    spawns: BoolProperty(name='Spawns and orbs', default=True)
    visuals: BoolProperty(name='Visible model', default=True,
                          description='Stage, background and sky from stNN.alr, with textures (reference only)')

    def execute(self, context):
        try:
            _root, msg = importer.import_stage(context, self.filepath, self.scale, self.collision, self.spawns,
                                               self.visuals)
        except Exception as e:
            self.report({'ERROR'}, 'Import failed: %s' % e)
            return {'CANCELLED'}
        self.report({'INFO'}, 'Imported: ' + msg)
        return {'FINISHED'}


class PDSTAGE_OT_import_game_original(bpy.types.Operator):
    """Import one of the game's maps from your game data folder: visible model, collision, spawns, objects,
    effects and its sky as editable settings"""
    bl_idname = 'pdstage.import_game_original'
    bl_label = 'Import Game Original'
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = 'map'

    map: EnumProperty(name='Map', items=IMPORT_ITEMS)
    preserve: BoolProperty(
        name='Record for preserving unedited parts', default=False,
        description='Also record what the import made, for the export fallback "Preserve unedited parts from the '
                    'original file". Off: the scene holds only what it shows')

    def execute(self, context):
        stage, _sep, variant = self.map.partition(':')
        data = bpy.path.abspath(_prefs_game_data(context))
        if not data:
            self.report({'ERROR'}, 'Set the game data folder in the add-on preferences first')
            return {'CANCELLED'}
        dat_path = exporter.game_original_dat(data, stage)
        alr_path = exporter.game_original_alr(data, stage)
        if not os.path.isfile(dat_path):
            self.report({'ERROR'}, '%s not found: %s' % (os.path.basename(dat_path), exporter.missing_hint(data)))
            return {'CANCELLED'}
        try:
            _root, msg = importer.import_stage(context, dat_path, alr_path=alr_path, stage=stage,
                                               variant=2 if variant == 'v2' else 0, preserve=self.preserve)
        except Exception as e:
            self.report({'ERROR'}, 'Import failed: %s' % e)
            return {'CANCELLED'}
        self.report({'INFO'}, 'Imported: ' + msg)
        return {'FINISHED'}


class PDSTAGE_OT_export(bpy.types.Operator, ExportHelper):
    """Write this scene as a Phantom Dust map .dat, replacing the chosen game original"""
    bl_idname = 'export_scene.phantom_dust_stage'
    bl_label = 'Export Phantom Dust Stage'

    filename_ext = '.dat'
    filter_glob: StringProperty(default='*.dat', options={'HIDDEN'})
    game_original: EnumProperty(name='Replaces', items=GAME_ORIGINAL_ITEMS,
                             description='Game original map this map replaces; its file supplies the parts not made in Blender')
    game_data: StringProperty(name='Game data folder', subtype='DIR_PATH',
                              description="Phantom Dust's Assets\\Data folder")
    scale: FloatProperty(name='Scale', description='Blender units per game unit', default=cv.DEFAULT_SCALE, min=0.0001)
    compress_textures: EnumProperty(
        name='Textures', default='ALL',
        items=[('ALL', 'Compressed', 'Every new texture compressed (DXT1/DXT5) with mip levels, like the game\'s own'),
               ('NONE', 'Uncompressed', 'Plain BGRA without mip levels (as the game\'s own plain textures): sharper '
                'up close but shimmers at a distance and takes four to eight times the space. Light maps stay '
                'compressed')])
    lightmap_budget_mb: IntProperty(
        name='Light map budget (MB)', default=16, min=1, max=256,
        description='How much the baked light maps may take in the model file: the biggest are halved until '
                    'they fit')
    texture_budget_mb: IntProperty(
        name='Texture budget (MB)', default=24, min=1, max=256,
        description='How much the new textures (not the light maps) may take in the model file: if they do '
                    'not fit, the biggest are halved. The game loads at most 20 MiB of model data (vertices and textures): '
                    'the export also shrinks the biggest textures until the map fits')
    preserve_unedited: BoolProperty(
        name='Preserve unedited parts from the original file', default=False,
        description='Fallback, off by default: parts the scene did not change since it was imported with "Record '
                    'for preserving unedited parts" keep the original file\'s bytes, and simple edits are written '
                    'into the original records. Off: both files are built from what is in the scene')
    install_to_game: BoolProperty(
        name='Install into the game', default=False,
        description='Also copy the exported files over the game original in the game data folder, so it is playable '
                    'right away. The game\'s own files are backed up first (Map\\pd_addon_backup); '
                    'Restore Game Original puts them back')

    def invoke(self, context, event):
        self.game_original = context.scene.pd_game_original
        self.scale = context.scene.pd_scale
        if not self.game_data:
            self.game_data = _prefs_game_data(context)
        self.filepath = self.game_original + '.dat'
        return super().invoke(context, event)

    def execute(self, context):
        scene_tools.set_broken_parts_hidden(context, True)      # break_ / collider_broken_ / stay_ out of the way
        game_data = bpy.path.abspath(self.game_data or _prefs_game_data(context))
        if not game_data:
            self.report({'ERROR'}, 'Set the game data folder (Assets\\Data) in the export options or add-on preferences')
            return {'CANCELLED'}
        game_map = os.path.normcase(os.path.abspath(exporter.map_dir(game_data)))
        if os.path.normcase(os.path.dirname(os.path.abspath(self.filepath))) == game_map:
            self.report({'ERROR'}, 'Export to another folder; tick "Install into the game" to put the map in the game')
            return {'CANCELLED'}
        from . import roundtrip
        roundtrip.ENABLED = self.preserve_unedited
        try:
            base_alr = exporter.game_original_alr(game_data, self.game_original)
            out_alr = os.path.splitext(self.filepath)[0] + '.alr'
            vmsg, objects, placements = exporter.export_models(context, base_alr, out_alr, self.scale,
                                                               True, True,   # background and sky, character shadows: always
                                                               compress_textures=self.compress_textures,
                                                               texture_budget_mb=self.texture_budget_mb,
                                                               lightmap_budget_mb=self.lightmap_budget_mb)
            msg = exporter.export_scene(context, exporter.game_original_dat(game_data, self.game_original),
                                        self.filepath, self.scale, True, objects, placements,   # clean slate: always
                                        game_data)
            if vmsg:
                msg += '; ' + vmsg + ' -> ' + os.path.basename(out_alr)
            try:
                cad_path, nmsg = navmesh.export(context.scene, self.scale, self.filepath)
            except ValueError as e:
                raise exporter.ExportError(str(e))
            msg += '; ' + nmsg
            if self.install_to_game:
                done = exporter.install(game_data, self.game_original, self.filepath, out_alr if vmsg else None)
                if cad_path:
                    nav_done = navmesh.install(game_data, self.game_original, cad_path)
                    done += nav_done
                    if nav_done and navmesh.stage_number(self.game_original) % 10 in (2, 3, 4, 5, 6, 7, 8):
                        n = navmesh.stage_number(self.game_original) % 10
                        msg += ('; note: st%02d, st1%d and st2%d share one nav mesh file' % (n, n, n))
                msg += '; installed into the game as %s' % ', '.join(os.path.basename(p) for p in done)
        except (exporter.ExportError, OSError) as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        context.scene.pd_game_original = self.game_original
        context.scene.pd_scale = self.scale
        self.report({'INFO'}, 'Exported %s: %s' % (os.path.basename(self.filepath), msg))
        return {'FINISHED'}


class PDSTAGE_PT_collection(bpy.types.Panel):
    bl_label = 'Phantom Dust'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'collection'

    def draw(self, context):
        c = context.collection
        lay = self.layout
        parent = next((p for p in bpy.data.collections if c.name in p.children), None)
        if parent is not None and parent.pd_role == 'EFFECTS':
            lay.label(text='Effect type (in %s)' % parent.name, icon='SHADERFX')
            lay.prop(c, 'pd_effect')
            col = lay.column(align=True)
            col.label(text='Each object here (empties work well) is one placement:')
            col.label(text='location, turn about Z, and scale (multiplies the effect size)')
            return
        if parent is not None and parent.pd_role == 'OBJECTS':
            lay.label(text='Object type (in %s)' % parent.name, icon='OBJECT_DATA')
            lay.prop(c, 'pd_preset')
            box = lay.box()
            col = box.column(align=True)
            for k, line in enumerate(objects_build.HELP.get(c.pd_preset, ())):
                col.label(text=line, icon='INFO' if k == 0 else 'BLANK1')
            if c.pd_preset == 'GAME':
                row = lay.row(align=True)
                row.prop(c, 'pd_category')
                row.prop(c, 'pd_type')
            cat = c.pd_category if c.pd_preset == 'GAME' else objects_build.PRESETS[c.pd_preset][0]
            states = objects_build.PRESETS[c.pd_preset][3]
            destructible = cat == 2 or 'B' in states                        # category 2 = breakable objects
            if destructible:
                if c.pd_preset not in ('BREAK_TOUCH', 'TOUCH_ROLL', 'FALLING_SIGN', 'EVENT_PROP'):
                    lay.prop(c, 'pd_hits')
                import re
                tag = re.search(r'dmg:\s*(\d+)', c.name, re.I)
                if tag:
                    lay.label(text='Damage: %s (from "dmg:" in the name)' % tag.group(1), icon='INFO')
                else:
                    lay.prop(c, 'pd_damage')
                if 'B' in states:
                    lay.prop(c, 'pd_pieces_hurt')
                if 'D' in states:
                    lay.prop(c, 'pd_debris_stays')
                lay.prop(c, 'pd_break_sound')
                if 'B' in states or 'D' in states:
                    lay.prop(c, 'pd_piece_sound')
            if c.pd_preset == 'JUMP_PAD':
                lay.prop(c, 'pd_jump_power')
                lay.prop(c, 'pd_pad_visible')
            draw_surface(lay, c, 'Collider surface')
            col = lay.column(align=True)
            col.label(text='Every mesh here is one placement: copy it as often')
            col.label(text='as you like (Shift+D or Alt+D, any scale)')
            box = lay.box()
            col = box.column(align=True)
            col.label(text='Parts: objects parented to a placement, named', icon='OUTLINER_OB_MESH')
            if 'B' in states:
                col.label(text='break_...  broken piece that falls as physics debris', icon='BLANK1')
                col.label(text='stay_...   broken piece that stays where it is', icon='BLANK1')
            if 'D' in states:
                col.label(text='debris_... what is left after breaking', icon='BLANK1')
            col.label(text='collider_... collision (default: its own mesh)', icon='BLANK1')
            if destructible:
                col.label(text='collider_broken_... collision once broken', icon='BLANK1')
                col.label(text="A piece's own children (shadow) move with it.", icon='BLANK1')
                col.label(text='How fast pieces fly is up to the game (from', icon='INFO')
                col.label(text='their mass, with a fixed limit): no setting.', icon='BLANK1')
            return
        lay.prop(c, 'pd_role')
        found = dict(exporter.collision_collections(context.scene))
        if _in_visuals(context.scene, c):
            lay.prop(c, 'pd_collide')
        if c in found:
            draw_surface(lay, c)
        if c.pd_role == 'SPAWNS':
            lay.label(text='Child collections = layouts; spawn empties (+Y = facing) with 3 orb children')
        elif c.pd_role == 'VISUALS':
            lay.label(text='Texture from each material; baked lighting from the PD_Light colour attribute')
        elif c.pd_role == 'OBJECTS':
            lay.label(text='Each child collection is one object type')
        elif c.pd_role == 'EFFECTS':
            lay.label(text='Each child collection is one effect type (steam, sparks, smoke)')
        elif c.pd_role == 'NAVMESH':
            lay.label(text='AI paths: NavMesh quads, NavLinks, JumpPoint empties (drawn pink)')


class PDSTAGE_PT_lighting(bpy.types.Panel):
    bl_label = 'Phantom Dust Lighting'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'scene'

    def draw_header(self, context):
        self.layout.prop(context.scene, 'pd_light_custom', text='')

    def draw(self, context):
        s = context.scene
        lay = self.layout
        lay.active = s.pd_light_custom
        box = lay.box()
        box.label(text='Sun: lights the stage, objects and effects', icon='LIGHT_SUN')
        box.prop(s, 'pd_sun', text='Object')
        sun = scene_sun(s)
        if sun is not None:                              # the Sun object's own settings, here for convenience
            row = box.row(align=True)
            row.prop(sun.data, 'energy', text='Strength')
            row.prop(sun.data, 'color', text='')
        else:
            box.prop(s, 'pd_stage_light', text='Colour')
        box.prop(s, 'pd_stage_ambient', text='Shadow side (ambient)')
        box = lay.box()
        box.label(text='Characters: their own light (same direction as the Sun)', icon='USER')
        row = box.row(align=True)
        row.prop(s, 'pd_char_light', text='Colour')
        row.prop(s, 'pd_char_ambient', text='Shadow side')
        box = lay.box()
        box.label(text='The game multiplies the stage\'s baked PD_Light', icon='INFO')
        box.label(text='colours by this light. Off: keep the game original\'s own.')
        box.label(text='Fog is not supported (the PC version ignores it).')


def _surface_items(self, context):
    return surfaces.enum_items(context.scene if context is not None else bpy.context.scene)


def _surface_get(self):
    text = (self.pd_surface or '').strip()
    if not text:
        return 0
    try:
        v = int(text, 16)
    except ValueError:
        return 999
    return v + 1 if v in surfaces.DROPDOWN else 999


def _surface_set(self, value):
    if value == 0:
        self.pd_surface = ''
    elif value != 999:
        self.pd_surface = '%02X' % (value - 1)
    elif not self.pd_surface:
        self.pd_surface = '%02X' % surfaces.DEFAULT
    restricted.on_change(self, bpy.context)


def _in_visuals(scene, c):
    """c is a Visuals collection or inside one (not its Sky / Background)."""
    from .visuals_export import _slot_for
    for v in exporter.collections_with_role(scene, 'VISUALS'):
        todo = [(v, _slot_for(v.name, 0))]
        while todo:
            k, slot = todo.pop()
            if slot != 0:
                continue
            if k == c:
                return True
            todo += [(ch, _slot_for(ch.name, slot)) for ch in k.children]
    return False


class PDSTAGE_PT_object(bpy.types.Panel):
    bl_label = 'Phantom Dust'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'object'

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.type == 'MESH' and any(
            ob.name in c.objects for c, _st in exporter.collision_collections(context.scene))

    def draw(self, context):
        lay = self.layout
        ob = context.object
        coll_st = next(st for c, st in exporter.collision_collections(context.scene) if ob.name in c.objects)
        lay.label(text='Collision surface (collection: %02X %s)' % (coll_st, surfaces.name(coll_st)), icon='MOD_PHYSICS')
        draw_surface(lay, ob, 'This object')


class PDSTAGE_PT_object_part(bpy.types.Panel):
    bl_label = 'Phantom Dust Piece'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'object'

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.type == 'MESH' and part_kind(ob) in ('broken', 'debris')

    def draw(self, context):
        lay = self.layout
        ob = context.object
        n = ob.name.lower()
        if part_kind(ob) == 'debris':
            lay.label(text='debris_: what is left after breaking', icon='MOD_EXPLODE')
        elif n.startswith('stay_') or (not n.startswith('break_') and ob.get('pd_stay')):
            lay.label(text='stay_: stays where it is (no physics)', icon='PINNED')
        else:
            lay.label(text='break_: falls as physics debris', icon='MOD_PHYSICS')
        lay.label(text='Rename break_ <-> stay_ to switch', icon='BLANK1')


def _pad_visible_update(self, context):
    for o in self.objects:                               # an invisible trigger shows as a wireframe in Blender
        if o.type == 'MESH' and not o.get('pd_part'):
            o.display_type = 'TEXTURED' if self.pd_pad_visible else 'WIRE'


def _wrap(text, n):
    import textwrap
    return textwrap.wrap(text, n) or ['']


def draw_surface(lay, c, text='Surface'):
    lay.prop(c, 'pd_surface_pick', text=text)
    if c.pd_surface_pick.startswith('S'):
        m = surfaces.MATERIALS.get(int(c.pd_surface_pick[1:], 16))
        if m and m[2]:                                   # special surfaces: say what they do
            col = lay.column(align=True)
            col.scale_y = 0.8
            for i, line in enumerate(_wrap(m[1], 48)):
                col.label(text=line, icon='INFO' if i == 0 else 'BLANK1')
    if c.pd_surface_pick == 'CUSTOM':
        lay.prop(c, 'pd_surface', text='Number (hex)')
        v = c.pd_surface.strip()
        try:
            lay.label(text=surfaces.MATERIALS[int(v, 16)][1] if v else '', icon='INFO')
        except (ValueError, KeyError):
            lay.label(text='Not a surface the game knows (00-20)', icon='ERROR')


def _sun_poll(self, ob):
    return ob.type == 'LIGHT' and ob.data.type == 'SUN'


def menu_import(self, context):
    self.layout.operator_menu_enum(PDSTAGE_OT_import_game_original.bl_idname, 'map',
                                   text='Phantom Dust Game Original')
    self.layout.operator(PDSTAGE_OT_import.bl_idname, text='Phantom Dust Map File (.dat)')


def menu_export(self, context):
    self.layout.operator(PDSTAGE_OT_export.bl_idname, text='Phantom Dust Stage (.dat)')


classes = (PDSTAGE_Preferences, PDSTAGE_OT_import, PDSTAGE_OT_import_game_original, PDSTAGE_OT_export, PDSTAGE_PT_collection, PDSTAGE_PT_object, PDSTAGE_PT_object_part,
           PDSTAGE_PT_lighting) \
    + scene_tools.classes + pd_material.classes + sky.classes + lightbake.classes + characters_ui.classes \
    + realtime.classes


def _colour(name, default, desc, update=None):
    return bpy.props.FloatVectorProperty(name=name, subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0,
                                         default=default, description=desc, update=update)


def scene_sun(scene):
    """The scene's Sun (Phantom Dust Lighting), if it is still in the scene."""
    sun = getattr(scene, 'pd_sun', None)
    return sun if sun is not None and sun.type == 'LIGHT' and sun.name in scene.objects else None


def _stage_light_update(self, context):
    """The stage light colour is the Sun's colour: keep the Sun object in step."""
    sun = scene_sun(self)
    if sun is not None and any(abs(a - b) > 1e-4 for a, b in zip(sun.data.color, self.pd_stage_light)):
        sun.data.color = tuple(self.pd_stage_light)


def register():
    bpy.types.Collection.pd_role = EnumProperty(name='Role', items=cv.ROLES, default='NONE',
                                                description='What this collection is in the exported map')
    bpy.types.Collection.pd_surface = StringProperty(
        name='Surface number', default='',
        description='Collision surface type in hex. Empty = same as the parent collection',
        update=restricted.on_change)
    bpy.types.Collection.pd_collide = BoolProperty(
        name='Use as collision', default=False,
        description='Players can walk on these meshes too (no separate collider needed)')
    bpy.types.Object.pd_surface = StringProperty(
        name='Surface number', default='',
        description='Collision surface of this object in hex. Empty = its collection\'s',
        update=restricted.on_change)
    bpy.types.Object.pd_surface_pick = EnumProperty(
        name='Surface', items=_surface_items, get=_surface_get, set=_surface_set,
        description='Surface of this object (overrides the collection)')
    bpy.types.Collection.pd_surface_pick = EnumProperty(
        name='Surface', items=_surface_items, get=_surface_get, set=_surface_set,
        description='Footstep sound, craters and special effects of this collision')
    bpy.types.Collection.pd_preset = EnumProperty(
        name='Behaviour', items=PRESET_ITEMS, default='SOLID',
        description='What these objects do in game')
    bpy.types.Collection.pd_category = bpy.props.IntProperty(
        name='Category', default=2, min=0, max=255,
        description='Game object category (from the imported map)')
    bpy.types.Collection.pd_type = bpy.props.IntProperty(
        name='Type', default=1, min=0, max=255, description='Game object type within the category')
    bpy.types.Collection.pd_debris_stays = BoolProperty(
        name='Debris stays', default=False, description='Debris stays on the ground (off: it disappears)')
    bpy.types.Collection.pd_effect = EnumProperty(
        name='Effect', items=EFFECT_ITEMS, default='STEAM_PIPE',
        description='Which of the game\'s effects to place (copied from your game files when exporting)')
    bpy.types.Collection.pd_break_sound = EnumProperty(
        name='Break sound', default='KEEP',
        items=[('KEEP', 'As imported / none', 'An imported object keeps its own; a new one is silent')]
        + [('%04X' % v, name, desc) for v, name, desc in objects_build.BREAK_SOUNDS],
        description='The game sound when this object is hit or breaks')
    bpy.types.Collection.pd_piece_sound = EnumProperty(
        name='Pieces sound', default='KEEP',
        items=[('KEEP', 'As imported / none', 'An imported object keeps its own; a new one is silent')]
        + [('%04X' % v, name, desc) for v, name, desc in objects_build.PIECE_SOUNDS],
        description='The game sound when its broken pieces hit something')
    bpy.types.Collection.pd_jump_power = bpy.props.IntProperty(
        name='Jump power', default=150, min=1, max=255, description='How high the pad launches players (game: 100-250)')
    bpy.types.Collection.pd_pad_visible = BoolProperty(
        name='Visible pad', default=False, update=_pad_visible_update,
        description='Export the pad\'s mesh as a visible model. Off: an invisible trigger to walk into (the mesh '
                    'only sets where it is), like the game\'s own pads')
    bpy.types.Collection.pd_hits = bpy.props.IntProperty(
        name='Hits to break', default=1, min=1, max=255, description='Hits it takes before it breaks')
    bpy.types.Collection.pd_damage = bpy.props.IntProperty(
        name='Damage', default=2, min=0, max=255,
        description='Damage a player takes when flying pieces or debris hit them (game: 2-3)')
    bpy.types.Collection.pd_pieces_hurt = BoolProperty(
        name='Pieces hit players', default=True, description='Flying break_ pieces can hit players (off: harmless)')
    bpy.types.Scene.pd_game_original = EnumProperty(name='Game original', items=GAME_ORIGINAL_ITEMS, default='st03')
    bpy.types.Scene.pd_scale = FloatProperty(name='Scale', default=cv.DEFAULT_SCALE, min=0.0001)
    bpy.types.Scene.pd_imported = BoolProperty(name='Started from an imported game original', default=False)
    # Defaults: Panorama Earthquake's own light colours
    bpy.types.Scene.pd_light_custom = BoolProperty(
        name='Custom lighting', default=False,
        description='Write these light settings into the map (off: keep the game original\'s lighting)')
    bpy.types.Scene.pd_sun = bpy.props.PointerProperty(
        name='Sun', type=bpy.types.Object, poll=_sun_poll,
        description='A Sun light whose direction the game\'s light uses (empty: keep the game original\'s direction)')
    bpy.types.Scene.pd_stage_light = _colour('Light', (0.706, 0.686, 0.608),
                                             'Colour of the sun on the stage, placed objects and effects (the same '
                                             'as the Sun\'s own colour: changing one changes the other)',
                                             update=_stage_light_update)
    bpy.types.Scene.pd_stage_ambient = _colour('Ambient', (0.424, 0.392, 0.373),
                                               'Light everywhere the sun does not reach: the darkest the stage, '
                                               'objects and effects get (the game adds it to every surface, '
                                               'light-mapped ones too)')
    bpy.types.Scene.pd_char_light = _colour('Light', (0.941, 0.922, 0.843),
                                            'Colour of the sunlight on characters (the game lights them '
                                            'separately from the stage)')
    bpy.types.Scene.pd_char_ambient = _colour('Ambient', (0.314, 0.282, 0.263),
                                              'Light on characters\' shaded side')
    bpy.types.Scene.pd_game_preview = BoolProperty(
        name='Game Preview', default=True,
        description='Show the game\'s look in Material Preview: PD materials drawn as the game does (sun, ambient '
                    'and shine like the game\'s shader). Off: Blender\'s own lighting. Bake Lighting turns it off '
                    'while it bakes',
        update=lambda self, context: pd_material.sync_preview(force=True))
    sky.register_props()
    lightbake.register_props()
    characters_ui.register_props()
    realtime.register_props()
    for c in classes:
        _register_class(c)
    pd_material.register_props()
    try:
        guides.register()
    except Exception as e:                          # a viewport convenience: never block the add-on
        print('Phantom Dust Stage: scale guides not started:', e)
    navmesh.register()
    release.register()
    try:
        scene_tools.register_handlers()
    except Exception as e:
        print('Phantom Dust Stage: collider display not started:', e)
    try:
        pd_material.register_preview()
    except Exception as e:                          # the live preview is a convenience: never block the add-on
        print('Phantom Dust Stage: game preview sync not started:', e)
    for menu, fn in ((bpy.types.TOPBAR_MT_file_import, menu_import), (bpy.types.TOPBAR_MT_file_export, menu_export)):
        try:
            menu.remove(fn)
        except Exception:
            pass
        menu.append(fn)


def unregister():
    try:
        scene_tools.unregister_handlers()
    except Exception:
        pass
    try:
        pd_material.unregister_preview()
    except Exception:
        pass
    pd_material.unregister_props()
    try:
        guides.unregister()
    except Exception:
        pass
    try:
        navmesh.unregister()
    except Exception:
        pass
    try:
        release.unregister()
    except Exception:
        pass
    for menu, fn in ((bpy.types.TOPBAR_MT_file_export, menu_export), (bpy.types.TOPBAR_MT_file_import, menu_import)):
        try:
            menu.remove(fn)
        except Exception:
            pass
    for c in reversed(classes):
        try:
            bpy.utils.unregister_class(c)
        except RuntimeError:
            pass
    sky.unregister_props()
    characters_ui.unregister_props()
    realtime.unregister_props()
    for p in lightbake.PROPS:
        if hasattr(bpy.types.Scene, p):
            delattr(bpy.types.Scene, p)
    for t, props in ((bpy.types.Scene, SCENE_PROPS), (bpy.types.Collection, COLLECTION_PROPS),
                     (bpy.types.Object, OBJECT_PROPS)):
        for p in props:
            if hasattr(t, p):
                try:
                    delattr(t, p)
                except (AttributeError, RuntimeError):
                    pass


SCENE_PROPS = ('pd_char_ambient', 'pd_char_light', 'pd_stage_ambient', 'pd_stage_light', 'pd_sun', 'pd_light_custom',
               'pd_game_preview', 'pd_imported', 'pd_scale', 'pd_game_original')
COLLECTION_PROPS = ('pd_break_sound', 'pd_piece_sound', 'pd_effect', 'pd_damage', 'pd_hits', 'pd_pieces_hurt', 'pd_pad_visible', 'pd_jump_power', 'pd_debris_stays', 'pd_preset',
                    'pd_category', 'pd_type',
                    'pd_surface_pick', 'pd_surface', 'pd_collide', 'pd_role')
OBJECT_PROPS = ('pd_surface_pick', 'pd_surface')


def _register_class(c):
    """Register a class, first removing a copy left behind by an earlier failed enable or an older version."""
    old = getattr(bpy.types, c.__name__, None)
    if old is not None:
        try:
            bpy.utils.unregister_class(old)
        except RuntimeError:
            pass
    bpy.utils.register_class(c)
