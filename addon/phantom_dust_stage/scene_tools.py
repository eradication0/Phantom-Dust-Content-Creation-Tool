"""Helpers for building a map: a starter scene, the lighting bake, restoring the game's own map files,
and the 3D View sidebar (N panel > Phantom Dust) that gathers every step."""
import math

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty

from . import convert as cv
from . import pd_material
from . import exporter
from . import visuals as pd_visuals
from . import visuals_export as vx

FLOOR_Z = 6.4                 # Panorama Earthquake's floor height (game 64): a safe height for any map slot
LIGHT = vx.LIGHT_LAYER


def _prefs_game_data(context):
    try:
        return bpy.path.abspath(context.preferences.addons[__package__].preferences.game_data)
    except (KeyError, AttributeError):
        return ''


def _collection(scene, name, parent=None, role='NONE', surface=''):
    c = bpy.data.collections.new(name)
    (parent or scene.collection).children.link(c)
    c.pd_role = role
    c.pd_surface = surface
    return c


def _checker(name, size=64, cells=8):
    img = bpy.data.images.new(name, size, size, alpha=False)
    px = []
    for y in range(size):
        for x in range(size):
            on = ((x * cells // size) + (y * cells // size)) % 2
            v = 0.62 if on else 0.48
            px += (v, v, v * 1.04, 1.0)
    img.pixels = px
    img.pack()
    return img


def _stripes(name, size=64):
    img = bpy.data.images.new(name, size, size, alpha=False)
    px = []
    for y in range(size):
        for x in range(size):
            on = ((x + y) * 6 // size) % 2
            px += (0.9, 0.75, 0.1, 1.0) if on else (0.08, 0.08, 0.08, 1.0)
    img.pixels = px
    img.pack()
    return img


def _jump_pad_object(name='JumpPad', size=3.0, height=0.1):
    """A 3 x 3 m hazard-striped slab, origin at its bottom centre, standing on the floor in the middle."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= size
        v.co.y *= size
        v.co.z = (v.co.z + 0.5) * height
    bm.to_mesh(me)
    bm.free()
    uv = me.uv_layers.new(name='UVMap')
    for li, loop in enumerate(me.loops):
        p = me.vertices[loop.vertex_index].co
        uv.data[li].uv = (p.x / size + 0.5, p.y / size + 0.5)
    me.materials.append(pd_visuals._material('JumpPad_mat', _stripes('pd_jumppad')))
    light = me.color_attributes.new(LIGHT, 'BYTE_COLOR', 'CORNER')     # top bright, sides a little darker
    for poly in me.polygons:
        s = 1.0 if poly.normal.z > 0.5 else 0.7
        for li in poly.loop_indices:
            light.data[li].color_srgb = (s, s, s, 1.0)
    me.color_attributes.active_color = light
    ob = bpy.data.objects.new(name, me)
    ob.location = (0, 0, FLOOR_Z)
    ob.hide_render = True                    # objects stay out of the stage lighting bake
    return ob


class PDSTAGE_OT_new_map(bpy.types.Operator):
    """Set up this scene for a new map: tagged collections, a floor with its collider, one spawn layout
    (4 spawns with 3 orbs each), a jump pad and a sun for the lighting"""
    bl_idname = 'pdstage.new_map'
    bl_label = 'New Map Setup'
    bl_options = {'REGISTER', 'UNDO'}

    size: bpy.props.FloatProperty(name='Floor size (m)', default=30.0, min=4.0, max=200.0)

    def execute(self, context):
        scene = context.scene
        if any(getattr(c, 'pd_role', 'NONE') != 'NONE' for c in scene.collection.children_recursive):
            self.report({'ERROR'}, 'This scene already has Phantom Dust collections; use a new scene (or a new file)')
            return {'CANCELLED'}
        scene.pd_scale = cv.DEFAULT_SCALE
        scene.pd_imported = False
        half = self.size / 2

        vis = _collection(scene, 'Visuals', role='VISUALS')
        _collection(scene, 'Sky', vis)
        _collection(scene, 'Background', vis)
        cols = _collection(scene, 'Colliders', role='COLLIDERS')          # surface: the replaced map's standard
        sp = _collection(scene, 'Spawn_Points', role='SPAWNS')
        lay = _collection(scene, 'LAYOUT_1', sp)
        objs = _collection(scene, 'Objects', role='OBJECTS')
        _collection(scene, 'Effects', role='EFFECTS')

        # floor: a subdivided plane (more vertices = smoother baked light), with a checker so scale is visible
        def floor_mesh(name, cuts):
            me = bpy.data.meshes.new(name)
            bm = bmesh.new()
            bmesh.ops.create_grid(bm, x_segments=cuts, y_segments=cuts, size=half)
            bm.to_mesh(me)
            bm.free()
            return me

        me = floor_mesh('Floor', 24)
        uv = me.uv_layers.new(name='UVMap')
        for li, loop in enumerate(me.loops):
            p = me.vertices[loop.vertex_index].co
            uv.data[li].uv = (p.x / 4.0, p.y / 4.0)                  # one checker tile per 4 m
        me.materials.append(pd_visuals._material('Floor_mat', _checker('pd_floor')))
        light = me.color_attributes.new(LIGHT, 'BYTE_COLOR', 'POINT')
        for d in light.data:
            d.color_srgb = (1, 1, 1, 1)
        me.color_attributes.active_color = light
        floor = bpy.data.objects.new('Floor', me)
        floor.location = (0, 0, FLOOR_Z)
        vis.objects.link(floor)

        col = bpy.data.objects.new('COL_Floor', floor_mesh('COL_Floor', 1))
        col.location = (0, 0, FLOOR_Z)
        col.display_type = 'WIRE'
        col.hide_render = True                    # colliders stay out of the lighting bake
        cols.objects.link(col)

        r = min(half * 0.7, 11.0)
        for i, a in enumerate((225, 315, 45, 135), 1):
            x, y = r * math.cos(math.radians(a)), r * math.sin(math.radians(a))
            e = bpy.data.objects.new('SPAWN_%d' % i, None)
            e.empty_display_type = 'ARROWS'
            e.empty_display_size = 2.0
            e.location = (x, y, FLOOR_Z + 0.3)
            e.rotation_euler = (0, 0, math.atan2(x, -y))             # +Y (the facing) towards the middle
            lay.objects.link(e)
            for k in range(1, 4):
                o = bpy.data.objects.new('SPAWN_%d_ORB_%d' % (i, k), None)
                o.empty_display_type = 'SPHERE'
                o.empty_display_size = 0.4
                o.parent = e
                o.location = (0, 2.0 + 1.5 * k, 0.5)
                lay.objects.link(o)

        # a jump pad in the middle: an object type with the Jump Pad behaviour; duplicate it (Alt+D) for more
        pads = _collection(scene, 'JumpPad', objs)
        pads.pd_preset = 'JUMP_PAD'
        pads.pd_jump_power = 200
        pad = _jump_pad_object()
        pads.objects.link(pad)
        pad.display_type = 'WIRE'                 # an invisible trigger by default (Visible pad: off)

        sun = bpy.data.objects.new('Sun', bpy.data.lights.new('Sun', 'SUN'))
        sun.data.energy = 1.0
        sun.location = (0.0, 0.0, 20.0)                    # above the floor (direction is what lights it)
        sun.rotation_euler = (math.radians(50), math.radians(15), math.radians(35))
        lighting = _collection(scene, 'Lighting', role='LIGHTING')   # the sun and lamps the bake uses
        lighting.objects.link(sun)
        scene.pd_sun = sun
        scene.pd_light_custom = True
        if scene.world is None:
            scene.world = bpy.data.worlds.new('World')
        scene.world.use_nodes = True
        bg = scene.world.node_tree.nodes.get('Background')
        if bg is not None:
            bg.inputs['Color'].default_value = (0.55, 0.6, 0.7, 1)
            bg.inputs['Strength'].default_value = 0.6
        scene.view_settings.view_transform = 'Standard'    # colours as the game shows them (Game Preview)
        scene.view_settings.look = 'None'
        for area in context.screen.areas if context.screen else ():
            if area.type == 'VIEW_3D':
                area.spaces.active.shading.type = 'MATERIAL'
        from . import sky
        err = sky.setup_new(context)                       # the sky sphere, started from the replaced map's sky
        if err:
            self.report({'WARNING'}, 'Map set up; sky: %s (gradient only)' % err)
            return {'FINISHED'}
        self.report({'INFO'}, 'Map set up: build under Visuals, add collider shapes under Colliders, '
                              'then Bake Lighting and Export')
        return {'FINISHED'}


def _role_collection(scene, role, name):
    """The scene's first collection with this role, else a new top-level one."""
    found = exporter.collections_with_role(scene, role)
    return found[0] if found else _collection(scene, name, role=role)


def _box_mesh(name, size, centre=(0.0, 0.0, 0.0), material=None):
    """A box mesh (size = x, y, z in metres) with UVs, a white PD_Light layer and an optional material."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = (v.co.x * size[0] + centre[0], v.co.y * size[1] + centre[1], v.co.z * size[2] + centre[2])
    uv = bm.loops.layers.uv.new('UVMap')
    for f in bm.faces:
        n = f.normal
        for loop in f.loops:
            p = loop.vert.co
            a, b = (p.y, p.z) if abs(n.x) > 0.5 else (p.x, p.z) if abs(n.y) > 0.5 else (p.x, p.y)
            loop[uv].uv = (a / 2.0, b / 2.0)
    bm.to_mesh(me)
    bm.free()
    if material is not None:
        me.materials.append(material)
    layer = me.color_attributes.new(LIGHT, 'BYTE_COLOR', 'POINT')
    layer.data.foreach_set('color', [1.0] * (4 * len(layer.data)))
    me.color_attributes.active_color = layer
    return me


def _crate_material():
    m = bpy.data.materials.get('Breakable_mat')
    return m or pd_visuals._material('Breakable_mat', _checker('pd_breakable', cells=4))


SPAWN_ITEMS = [
    ('JUMP_PAD', 'Jump Pad', 'A jump pad (Objects > Jump Pad)'),
    ('RESTRICTED', 'Restriction Wall', 'An invisible wall that keeps players in (Colliders, surface 10)'),
    ('BREAKABLE', 'Breakable Box', 'A box that breaks into 8 pieces, with its collider (Objects)'),
    ('STEAM', 'Steam Pipe', 'A steam pipe effect (Effects > Steam Pipe)'),
]


class PDSTAGE_OT_spawn_example(bpy.types.Operator):
    """Add a ready-made example at the 3D cursor, in the right collection with its settings"""
    bl_idname = 'pdstage.spawn_example'
    bl_label = 'Add Example'
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(name='Example', items=SPAWN_ITEMS)

    def execute(self, context):
        scene = context.scene
        at = scene.cursor.location.copy()
        if context.object is not None and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for o in context.view_layer.objects:
            o.select_set(False)
        if self.kind == 'JUMP_PAD':
            objs = _role_collection(scene, 'OBJECTS', 'Objects')
            pads = next((c for c in objs.children if c.pd_preset == 'JUMP_PAD'), None)
            if pads is None:
                pads = _collection(scene, 'Jump Pad', objs)
                pads.pd_preset = 'JUMP_PAD'
                pads.pd_jump_power = 200
            ob = _jump_pad_object()
            ob.location = at
            pads.objects.link(ob)
            ob.display_type = 'TEXTURED' if pads.pd_pad_visible else 'WIRE'
        elif self.kind == 'RESTRICTED':
            cols = _role_collection(scene, 'COLLIDERS', 'Colliders')
            walls = next((c for c in cols.children_recursive if c.pd_surface.strip().upper() in ('10', '0X10')), None)
            if walls is None:
                walls = _collection(scene, 'Restricted Area (10)', cols, surface='10')
            ob = bpy.data.objects.new('RestrictionWall', _box_mesh('RestrictionWall', (10.0, 0.2, 6.0), (0, 0, 3.0)))
            ob.location = at
            ob.hide_render = True
            walls.objects.link(ob)
            from . import restricted
            restricted.refresh(scene)
        elif self.kind == 'BREAKABLE':
            objs = _role_collection(scene, 'OBJECTS', 'Objects')
            tc = _collection(scene, 'Collapse in Place', objs)
            tc.pd_preset = 'CRUMBLE'
            tc.pd_hits = 2
            mat = _crate_material()
            ob = bpy.data.objects.new('Breakable', _box_mesh('Breakable', (2.0, 2.0, 2.0), (0, 0, 1.0), mat))
            ob.location = at
            ob.hide_render = True
            tc.objects.link(ob)
            col = bpy.data.objects.new('collider_Breakable', _box_mesh('collider_Breakable', (2.0, 2.0, 2.0), (0, 0, 1.0)))
            col['pd_part'] = 'collider'
            col.display_type = 'WIRE'
            col.parent = ob
            col.hide_render = True
            tc.objects.link(col)
            k = 0
            for z in (0.5, 1.5):
                for y in (-0.5, 0.5):
                    for x in (-0.5, 0.5):
                        k += 1
                        name = 'break_Breakable %d' % k
                        p = bpy.data.objects.new(name, _box_mesh(name, (0.95, 0.95, 0.95), (x, y, z), mat))
                        p['pd_part'] = 'broken'
                        p.parent = ob
                        p.hide_render = True
                        tc.objects.link(p)
                        p.hide_set(True)          # pieces sit inside the box: shown with the eye icon
        elif self.kind == 'STEAM':
            fx = _role_collection(scene, 'EFFECTS', 'Effects')
            steam = next((c for c in fx.children if c.pd_effect == 'STEAM_PIPE'), None)
            if steam is None:
                steam = _collection(scene, 'Steam Pipe', fx)
                steam.pd_effect = 'STEAM_PIPE'
            ob = bpy.data.objects.new('SteamPipe', None)
            ob.empty_display_type = 'ARROWS'
            ob.empty_display_size = 1.0
            ob.location = at
            steam.objects.link(ob)
        ob.select_set(True)
        context.view_layer.objects.active = ob
        self.report({'INFO'}, 'Added %s at the 3D cursor' % dict((k, n) for k, n, _d in SPAWN_ITEMS)[self.kind])
        return {'FINISHED'}


# The stage model has no hard triangle limit (meshes are split at 65,535 vertices on export); the game's own maps
# use 39k (Edgar's Dream) to 167k (Twilight Lane) triangles. Tested in game (tools/poly_test_map.py): 500k is fine,
# 1M flickers (colours and shapes) and breaks the shadows. Above the guide the export still works, with a warning.
TRI_GUIDE = 500000


def _triangle_count(objects):
    """Triangles of the stage meshes (as modelled, before modifiers): faces with n corners make n - 2."""
    total = 0
    for o in objects:
        me = o.data
        n = len(me.polygons)
        if n:
            try:
                import numpy as np
                corners = np.empty(n, dtype=np.int32)
                me.polygons.foreach_get('loop_total', corners)
                total += int(corners.sum()) - 2 * n
            except ImportError:
                total += sum(len(p.vertices) - 2 for p in me.polygons)
    return total


def collider_meshes(scene):
    """Every mesh exported as collision: the Colliders collections and Visuals marked Collide."""
    seen, out = set(), []
    for c, _st in exporter.collision_collections(scene):
        for o in c.objects:
            if o.type == 'MESH' and o.name not in seen:
                seen.add(o.name)
                out.append(o)
    return out


def stage_meshes(scene):
    """Mesh objects that make the stage model (Visuals, not its Sky/Background children)."""
    out = []

    def walk(c, slot):
        s = vx._slot_for(c.name, slot)
        if s == 0:
            out.extend(o for o in c.objects if o.type == 'MESH' and o not in out)
        for ch in c.children:
            walk(ch, s)

    for c in exporter.collections_with_role(scene, 'VISUALS'):
        walk(c, 0)
    return out



GAME_ORIGINAL_ITEMS = [(k, '%s (%s)' % (name, k), 'Restore %s' % name) for k, name in cv.GAME_ORIGINALS]


class PDSTAGE_OT_restore(bpy.types.Operator):
    """Put the game's own files for a game original map back (from the backup made when a map was installed)"""
    bl_idname = 'pdstage.restore_game_original'
    bl_label = 'Restore Game Original'

    game_original: EnumProperty(name='Game original', items=GAME_ORIGINAL_ITEMS)

    def invoke(self, context, event):
        self.game_original = context.scene.pd_game_original
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        game_data = _prefs_game_data(context)
        if not game_data:
            self.report({'ERROR'}, 'Set the game data folder in the add-on preferences')
            return {'CANCELLED'}
        try:
            done = exporter.restore(game_data, self.game_original)
        except OSError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        if not done:
            self.report({'WARNING'}, 'No backup for %s: the game\'s own files were never replaced' % self.game_original)
            return {'CANCELLED'}
        self.report({'INFO'}, 'Restored %s' % ', '.join(done))
        return {'FINISHED'}


class PDSTAGE_PT_sidebar(bpy.types.Panel):
    bl_label = 'Phantom Dust Stage'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Phantom Dust'

    def draw(self, context):
        s = context.scene
        lay = self.layout
        if not _prefs_game_data(context):
            box = lay.box()
            box.label(text='Set the game data folder in', icon='ERROR')
            box.label(text='Preferences > Add-ons > Phantom Dust')
        col = lay.column(align=True)
        col.label(text='1. Start')
        col.operator(PDSTAGE_OT_new_map.bl_idname, icon='ADD')
        col.operator_menu_enum('pdstage.import_game_original', 'map', text='Import Game Original', icon='IMPORT')
        col.operator('pdstage.make_all_materials', icon='MATERIAL')
        col = lay.column(align=True)
        col.label(text='Add at 3D cursor')
        grid = col.grid_flow(columns=2, align=True)
        for k, name, _d in SPAWN_ITEMS:
            icon = {'JUMP_PAD': 'TRIA_UP_BAR', 'RESTRICTED': 'CANCEL', 'BREAKABLE': 'MOD_EXPLODE', 'STEAM': 'SHADERFX'}[k]
            grid.operator(PDSTAGE_OT_spawn_example.bl_idname, text=name, icon=icon).kind = k
        col = lay.column(align=True)
        col.label(text='2. Light')
        from . import lightbake
        lightbake.draw(col, context)
        pd_material.draw_preview_toggle(lay, context)
        row = lay.row(align=True)
        if s.pd_sky_custom:
            row.label(text='Custom sky: on (Scene tab)', icon='WORLD')
            row.operator('pdstage.sky_preview_clear', text='', icon='X')
        else:
            row.operator('pdstage.sky_preview', text='Add Custom Sky', icon='WORLD')
        col = lay.column(align=True)
        col.label(text='3. Export')
        col.prop(s, 'pd_game_original', text='Replaces')
        col.operator('export_scene.phantom_dust_stage', text='Export...', icon='EXPORT')
        col.operator(PDSTAGE_OT_restore.bl_idname, icon='LOOP_BACK')
        n = {r: len(exporter.collections_with_role(s, r)) for r in ('VISUALS', 'COLLIDERS', 'SPAWNS', 'OBJECTS', 'EFFECTS')}
        box = lay.box()
        box.label(text='Collections in this scene:')
        for r, label in (('VISUALS', 'Visuals'), ('COLLIDERS', 'Colliders'), ('SPAWNS', 'Spawn Points'),
                         ('OBJECTS', 'Objects'), ('EFFECTS', 'Effects')):
            box.label(text='%s: %s' % (label, n[r] or 'none (game original kept)' if r in ('VISUALS', 'COLLIDERS', 'SPAWNS') else n[r]),
                      icon='CHECKMARK' if n[r] else 'DOT')
        tris = _triangle_count(stage_meshes(s))
        box.label(text='Stage triangles: {:,} / {:,}'.format(tris, TRI_GUIDE),
                  icon='ERROR' if tris > TRI_GUIDE else 'MESH_DATA')
        if tris > TRI_GUIDE:
            box.label(text='Above 500k the game may flicker', icon='BLANK1')
            box.label(text='and lose its shadows', icon='BLANK1')
        cols = collider_meshes(s)
        ctris = _triangle_count(cols)
        box.label(text='Collision triangles: {:,} / {:,}'.format(ctris, exporter.COLLISION_GUIDE),
                  icon='ERROR' if ctris > exporter.COLLISION_GUIDE else 'MOD_PHYSICS')
        box.label(text='Collision meshes: %d' % len(cols), icon='BLANK1')
        if ctris > exporter.COLLISION_GUIDE:
            box.label(text='Too much collision can crash the', icon='BLANK1')
            box.label(text='game on load: use simpler colliders', icon='BLANK1')


classes = (PDSTAGE_OT_new_map, PDSTAGE_OT_spawn_example, PDSTAGE_OT_restore, PDSTAGE_PT_sidebar)
