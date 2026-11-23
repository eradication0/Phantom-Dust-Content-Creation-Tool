"""Sidebar panel "Characters" (3D view > Phantom Dust) and its operators."""
import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

from . import char_tools as ct
from . import characters as chars
from . import convert as cv
from .pdstage import character as ch

_items = {}


def _data(context):
    try:
        return context.preferences.addons[__package__].preferences.game_data
    except (KeyError, AttributeError):
        return ''


def _cached(key, fn, context):
    data = _data(context)
    try:
        items = fn(data) if data else []
    except OSError:
        items = []
    items = items or [('NONE', 'No game data folder set (add-on preferences)', '')]
    _items[key] = items                          # Blender needs the list kept alive
    return items


def _char_items(self, context):
    return _cached('chars', chars.character_items, context)


def _set_items(self, context):
    return _cached('sets', chars.animation_set_items, context)


def _target_items(self, context):
    def fn(data):
        s = chars.scan(data)
        return [(cid, '%s: %s (%s)' % (cat, name, cid), 'Replace %s' % name)
                for cid, cat, name in ch.CHARACTERS if cat != 'NPC' and cid in s['battle']]
    return _cached('targets', fn, context)


def _voice_items(self, context):
    def fn(data):
        return [('KEEP', 'Keep current voice', 'Leave the voice bank as it is')] + chars.voice_items(data)
    return _cached('voices', fn, context)


def active_character(context):
    """The character armature (main body) the selection belongs to."""
    ob = context.active_object
    seen = 0
    while ob is not None and seen < 8:
        if ob.type == 'ARMATURE' and ob.get('pd_joints') and ob.get('pd_character'):
            return ob
        ob = ob.parent
        seen += 1
    return None


class PDSTAGE_OT_char_import(bpy.types.Operator):
    """Load the character's model, textures, armature with weights and (battle characters) all its animations"""
    bl_idname = 'pdstage.char_import'
    bl_label = 'Load Character'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = context.scene
        data = _data(context)
        if not data or s.pd_char_pick == 'NONE':
            self.report({'ERROR'}, 'Set the game data folder in the add-on preferences first')
            return {'CANCELLED'}
        try:
            arm, n = chars.import_character(context, data, s.pd_char_pick, int(s.pd_char_variant),
                                            s.pd_scale or cv.DEFAULT_SCALE, s.pd_char_load_anims)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, 'Loading failed: %s' % e)
            return {'CANCELLED'}
        context.view_layer.objects.active = arm
        miss = list(arm.get('pd_missing', []))
        if miss:
            self.report({'WARNING'}, 'Loaded %s: POSSIBLY BROKEN as a fighter, its skeleton lacks %s'
                        % (arm.name, ', '.join(miss)))
        else:
            self.report({'INFO'}, 'Loaded %s%s' % (arm.name, ', %d animations' % n if n else ''))
        return {'FINISHED'}


class PDSTAGE_OT_char_load_set(bpy.types.Operator):
    """Load every animation of the chosen set onto the selected character (moved onto its skeleton by joint
    names when it is another character's set). Takes a while for battle sets (136 motions)"""
    bl_idname = 'pdstage.char_load_set'
    bl_label = 'Load Animation Set'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = active_character(context)
        if arm is None:
            self.report({'ERROR'}, 'Select a loaded character first')
            return {'CANCELLED'}
        try:
            n = chars.load_animation_set(context, arm, _data(context), context.scene.pd_anim_set_pick)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, 'Loading animations failed: %s' % e)
            return {'CANCELLED'}
        self.report({'INFO'}, 'Loaded %d animations' % n)
        return {'FINISHED'}


class PDSTAGE_OT_char_play(bpy.types.Operator):
    """Show this animation on the character"""
    bl_idname = 'pdstage.char_play'
    bl_label = 'Play'

    action: bpy.props.StringProperty()

    def execute(self, context):
        arm = active_character(context)
        act = bpy.data.actions.get(self.action)
        if arm is None or act is None:
            return {'CANCELLED'}
        chars.play(arm, act)
        if not context.screen.is_animation_playing:
            bpy.ops.screen.animation_play()
        return {'FINISHED'}


class _FolderOp:
    directory: StringProperty(subtype='DIR_PATH')
    filter_folder: BoolProperty(default=True, options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class PDSTAGE_OT_char_tex_export(_FolderOp, bpy.types.Operator):
    """Save the textures of the selected objects (meshes, or a character's armature: all its meshes) as PNG
    files into a folder, alpha included (colour: cut-out; normal map: shine mask)"""
    bl_idname = 'pdstage.char_tex_export'
    bl_label = 'Export Textures of Selected'

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_objects)

    def execute(self, context):
        imgs = ct.object_images(context.selected_objects)
        if not imgs:
            self.report({'ERROR'}, 'The selected objects have no character textures')
            return {'CANCELLED'}
        paths = ct.save_images(imgs, bpy.path.abspath(self.directory))
        self.report({'INFO'}, '%d textures saved to %s' % (len(paths), self.directory))
        return {'FINISHED'}


class PDSTAGE_OT_char_tex_extract(_FolderOp, bpy.types.Operator):
    """Save every texture of the selected character (body, cloth and props, normal maps and the lighting
    lookup) as PNG files into a folder: edit them, then Import Textures from the same folder"""
    bl_idname = 'pdstage.char_tex_extract'
    bl_label = 'Extract All Textures'

    @classmethod
    def poll(cls, context):
        return active_character(context) is not None

    def execute(self, context):
        arm = active_character(context)
        imgs = ct.object_images([arm])
        paths = ct.save_images(imgs, bpy.path.abspath(self.directory))
        self.report({'INFO'}, '%d textures of %s saved to %s' % (len(paths), arm.name, self.directory))
        return {'FINISHED'}


class PDSTAGE_OT_char_tex_import(_FolderOp, bpy.types.Operator):
    """Load the selected character's textures back from a folder (files named like the textures, any common
    image format): converted to RGBA and a power of two (at most 1024), normal maps kept Non-Color; a normal
    map without alpha keeps its shine mask. Quick colour swaps: Extract, recolour, Import"""
    bl_idname = 'pdstage.char_tex_import'
    bl_label = 'Import Textures'

    @classmethod
    def poll(cls, context):
        return active_character(context) is not None

    def execute(self, context):
        arm = active_character(context)
        try:
            done, missing = ct.import_images(ct.object_images([arm]), bpy.path.abspath(self.directory))
        except (RuntimeError, ValueError) as e:
            self.report({'ERROR'}, 'Import failed: %s' % e)
            return {'CANCELLED'}
        for name, note in done:
            if note:
                self.report({'INFO'}, '%s: %s' % (name, note))
        if not done:
            self.report({'ERROR'}, 'No file in that folder matches a texture name (%s)' % ', '.join(missing[:6]))
            return {'CANCELLED'}
        self.report({'INFO'}, '%d textures loaded%s' % (len(done), ('; not found: %s' % ', '.join(missing))
                                                         if missing else ''))
        return {'FINISHED'}


class PDSTAGE_OT_char_rename_bones(bpy.types.Operator):
    """Give the bones readable names (Shoulder.L, Hand_Shadow.R...). The game's names stay with every bone
    (bone property pd_name) and the export writes those, so bones can be renamed freely"""
    bl_idname = 'pdstage.char_rename_bones'
    bl_label = 'Readable Bone Names'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return active_character(context) is not None and context.mode == 'OBJECT'

    def execute(self, context):
        arm = active_character(context)
        n = 0
        for ob in [arm] + [c for c in arm.children_recursive if c.type == 'ARMATURE' and c.get('pd_joints')]:
            n += ct.rename_bones(ob)
        self.report({'INFO'}, '%d bones renamed' % n)
        return {'FINISHED'}


class PDSTAGE_OT_char_shine_layer(bpy.types.Operator):
    """Add the PD Shine vertex paint layer to the character's meshes (white = full shine, black = none) and
    make it the active colour for Vertex Paint"""
    bl_idname = 'pdstage.char_shine_layer'
    bl_label = 'Shine Paint Layer'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return active_character(context) is not None and context.mode == 'OBJECT'

    def execute(self, context):
        arm = active_character(context)
        meshes = [o for o in ct.character_meshes(arm) if not o.get('pd_rigid')]
        for ob in meshes:
            ct.ensure_shine(ob.data)
        self.report({'INFO'}, 'PD Shine on %d meshes (Vertex Paint mode to paint it)' % len(meshes))
        return {'FINISHED'}


class PDSTAGE_OT_char_check(bpy.types.Operator):
    """Check whether the selected character can replace the chosen battle character: skeleton and animations,
    textures (sizes, formats), bone names, vertex weights, UVs, materials and the shine paint layer"""
    bl_idname = 'pdstage.char_check'
    bl_label = 'Check'

    def execute(self, context):
        arm = active_character(context)
        if arm is None:
            self.report({'ERROR'}, 'Select a loaded character first')
            return {'CANCELLED'}
        problems = chars.check_compatible(arm, _data(context), context.scene.pd_char_target,
                                          context.scene.pd_char_experimental)
        warnings = []
        for ob in [arm] + [c for c in arm.children_recursive if c.type == 'ARMATURE' and c.get('pd_joints')]:
            e, w = ct.check_model(ob)
            problems += e
            warnings += w
        for w in warnings:
            self.report({'WARNING'}, w)
        if problems:
            for p in problems:
                self.report({'ERROR'}, p)
            return {'CANCELLED'}
        if arm.get('pd_missing'):
            self.report({'WARNING'}, 'Exportable, but POSSIBLY BROKEN: the skeleton lacks %s (added from the '
                        'replaced character on export)' % ', '.join(arm['pd_missing']))
            return {'FINISHED'}
        self.report({'WARNING'} if warnings else {'INFO'},
                    'Compatible: skeleton, the 136 motions, textures, weights and UVs are fine'
                    + (' (%d warnings, see the info log)' % len(warnings) if warnings else ''))
        return {'FINISHED'}


class PDSTAGE_OT_char_export(bpy.types.Operator):
    """Write the selected character (model, textures, armature, the loaded battle animation set) over the chosen
    battle character in the game folder. The game's own files are saved in that character's pd_addon_backup
    folder first"""
    bl_idname = 'pdstage.char_export'
    bl_label = 'Export Character'

    def execute(self, context):
        s = context.scene
        arm = active_character(context)
        if arm is None:
            self.report({'ERROR'}, 'Select a loaded character first')
            return {'CANCELLED'}
        variants = (0, 1, 2, 3) if s.pd_char_target_variant == 'ALL' else (int(s.pd_char_target_variant),)
        try:
            msg = chars.export_character(context, arm, _data(context), s.pd_char_target, variants,
                                         move=s.pd_char_move, voice=s.pd_char_voice,
                                         experimental=s.pd_char_experimental)
        except chars.CharacterExportError as e:
            self.report({'ERROR'}, 'Cannot export: %s' % e)
            return {'CANCELLED'}
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, 'Export failed: %s' % e)
            return {'CANCELLED'}
        self.report({'WARNING'} if 'POSSIBLY BROKEN' in msg else {'INFO'}, 'Exported: ' + msg)
        return {'FINISHED'}


class PDSTAGE_OT_char_settings(bpy.types.Operator):
    """Write only the voice and jump / cartwheel choice into the game's character table (setup\\charaset) for
    the chosen battle character, without exporting a model"""
    bl_idname = 'pdstage.char_settings'
    bl_label = 'Apply Voice, Movement, Hitbox'

    def execute(self, context):
        s = context.scene
        move = None
        if s.pd_char_move in ('750', '751'):
            move = int(s.pd_char_move)
        elif s.pd_char_move == 'AUTO':
            arm = active_character(context)
            move = chars.set_movement(arm, _data(context)) if arm else None
        try:
            arm = active_character(context)
            box = chars.character_hitbox(arm) if arm is not None else None
            chars.patch_charaset(_data(context), s.pd_char_target, move=move,
                                 voice=None if s.pd_char_voice == 'KEEP' else s.pd_char_voice, box=box)
        except (OSError, KeyError) as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        r = chars.charaset_record(_data(context), s.pd_char_target)
        self.report({'INFO'}, '%s: %s, voice %s' % (s.pd_char_target, 'cartwheel' if r and r['move'] == 751 else 'jump',
                                                    r['voice'] if r else '?'))
        return {'FINISHED'}


class PDSTAGE_OT_char_restore(bpy.types.Operator):
    """Put the chosen battle character's own files back (from its pd_addon_backup folder)"""
    bl_idname = 'pdstage.char_restore'
    bl_label = 'Restore Original'

    def execute(self, context):
        done = chars.restore_character(_data(context), context.scene.pd_char_target)
        if not done:
            self.report({'WARNING'}, 'No backup: this character was never replaced')
            return {'CANCELLED'}
        self.report({'INFO'}, 'Restored %s' % ', '.join(done))
        return {'FINISHED'}


class PDSTAGE_UL_char_actions(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        row = layout.row(align=True)
        row.label(text=item.get('pd_clip', item.name), icon='ACTION')
        row.operator(PDSTAGE_OT_char_play.bl_idname, text='', icon='PLAY').action = item.name

    def filter_items(self, context, data, propname):
        acts = getattr(data, propname)
        arm = active_character(context)
        name = arm.name if arm else None
        flt = [self.bitflag_filter_item if a.get('pd_armature') == name and name else 0 for a in acts]
        if self.filter_name:
            low = self.filter_name.lower()
            flt = [f if f and low in a.name.lower() else 0 for f, a in zip(flt, acts)]
        order = sorted(range(len(acts)), key=lambda i: (acts[i].get('pd_set', ''), acts[i].get('pd_motion', -1),
                                                       acts[i].name))
        neworder = [0] * len(acts)
        for k, i in enumerate(order):
            neworder[i] = k
        return flt, neworder


def _action_index_update(self, context):
    arm = active_character(context)
    i = self.pd_char_action_index
    if arm is not None and 0 <= i < len(bpy.data.actions):
        act = bpy.data.actions[i]
        if act.get('pd_armature') == arm.name:
            chars.play(arm, act)


class PDSTAGE_PT_characters(bpy.types.Panel):
    bl_label = 'Characters'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Phantom Dust'
    bl_order = 1

    def draw(self, context):
        s = context.scene
        lay = self.layout
        col = lay.column(align=True)
        col.label(text='1. Load')
        col.prop(s, 'pd_char_pick', text='')
        row = col.row(align=True)
        row.enabled = s.pd_char_pick.startswith('B:')
        row.prop(s, 'pd_char_variant', text='Colour')
        col.prop(s, 'pd_char_load_anims')
        col.operator(PDSTAGE_OT_char_import.bl_idname, icon='ARMATURE_DATA')

        arm = active_character(context)
        if arm is not None and arm.get('pd_missing'):
            box = lay.box()
            box.alert = True
            box.label(text='%s: possibly broken' % arm.name, icon='ERROR')
            box.label(text='Skeleton lacks: %s' % ', '.join(arm['pd_missing']), icon='BLANK1')
        col = lay.column(align=True)
        col.label(text='2. Animations' + (' (%s)' % arm.name if arm else ''))
        if arm is None:
            col.label(text='Select a loaded character', icon='INFO')
        else:
            col.label(text='Set: %s' % arm.get('pd_anim_set', 'none'), icon='ACTION')
            col.prop(s, 'pd_anim_set_pick', text='')
            col.operator(PDSTAGE_OT_char_load_set.bl_idname, icon='IMPORT')
            col.template_list('PDSTAGE_UL_char_actions', '', bpy.data, 'actions', s, 'pd_char_action_index', rows=6)

        col = lay.column(align=True)
        col.label(text='Textures, Bones, Paint')
        col.operator(PDSTAGE_OT_char_tex_export.bl_idname, icon='EXPORT')
        row = col.row(align=True)
        row.operator(PDSTAGE_OT_char_tex_extract.bl_idname, text='Extract All', icon='FILE_FOLDER')
        row.operator(PDSTAGE_OT_char_tex_import.bl_idname, text='Import', icon='IMPORT')
        row = col.row(align=True)
        row.operator(PDSTAGE_OT_char_rename_bones.bl_idname, text='Readable Bones', icon='BONE_DATA')
        row.operator(PDSTAGE_OT_char_shine_layer.bl_idname, text='Shine Paint', icon='VPAINT_HLT')
        if arm is not None and context.active_bone is not None and context.active_object is not None \
                and context.active_object.type == 'ARMATURE':
            b = context.active_object.data.bones.get(context.active_bone.name)
            if b is not None and ct.GAME_NAME in b:
                col.label(text='In game: %s' % (b[ct.GAME_NAME] or '(unnamed joint %d)' % b.get('pd_index', -1)),
                          icon='INFO')

        col = lay.column(align=True)
        col.label(text='3. Export over')
        col.prop(s, 'pd_char_target', text='')
        col.prop(s, 'pd_char_target_variant', text='Colours')
        rec = None
        try:
            rec = chars.charaset_record(_data(context), s.pd_char_target) if _data(context) else None
        except OSError:
            pass
        if rec:
            col.label(text='Now: %s, voice %s, height %.1f' % (
                'cartwheel' if rec['move'] == 751 else 'jump',
                (rec['voice'] or 'none').replace('BattleVo_', '').replace('.bin', ''), rec['height'] / 10.0),
                      icon='INFO')
        col.prop(s, 'pd_char_move', text='Movement')
        col.prop(s, 'pd_char_voice', text='Voice')
        if arm is not None and arm.get('pd_hitbox'):
            hb = chars.character_hitbox(arm)
            col.label(text='Hitbox: height %.1f, width %.1f, hit radius %.1f' % (hb[0] / 10, hb[1] / 10, hb[2] / 10),
                      icon='MESH_CAPSULE')
            if int(arm['pd_hitbox'][0]) < chars.MIN_CAPSULE:
                col.label(text='(own height %.1f raised to the minimum 18)' % (int(arm['pd_hitbox'][0]) / 10),
                          icon='BLANK1')
        col.operator(PDSTAGE_OT_char_settings.bl_idname, icon='SPEAKER')
        col.prop(s, 'pd_char_experimental')
        row = col.row(align=True)
        row.enabled = arm is not None
        row.operator(PDSTAGE_OT_char_check.bl_idname, icon='CHECKMARK')
        row.operator(PDSTAGE_OT_char_export.bl_idname, icon='EXPORT')
        col.operator(PDSTAGE_OT_char_restore.bl_idname, icon='LOOP_BACK')


classes = (PDSTAGE_OT_char_tex_export, PDSTAGE_OT_char_tex_extract, PDSTAGE_OT_char_tex_import,
           PDSTAGE_OT_char_rename_bones, PDSTAGE_OT_char_shine_layer,
           PDSTAGE_OT_char_import, PDSTAGE_OT_char_load_set, PDSTAGE_OT_char_play, PDSTAGE_OT_char_check,
           PDSTAGE_OT_char_export, PDSTAGE_OT_char_settings, PDSTAGE_OT_char_restore, PDSTAGE_UL_char_actions, PDSTAGE_PT_characters)


def register_props():
    S = bpy.types.Scene
    S.pd_char_pick = EnumProperty(name='Character', items=_char_items,
                                  description='Character to load (from your game data folder)')
    S.pd_char_variant = EnumProperty(name='Colour', items=[(str(k), 'Colour %d' % (k + 1), 'File <id>%d.alr' % k)
                                                           for k in range(4)], default='0')
    S.pd_char_load_anims = BoolProperty(name='With its animations', default=True,
                                        description='Battle characters: also load their 136 motions (slower)')
    S.pd_anim_set_pick = EnumProperty(name='Animation set', items=_set_items,
                                      description='Animations to load onto the selected character')
    S.pd_char_action_index = IntProperty(name='Animation', default=-1, update=_action_index_update)
    S.pd_char_target = EnumProperty(name='Replace', items=_target_items,
                                    description='Battle character whose files the export replaces')
    S.pd_char_experimental = BoolProperty(
        name='Experimental: allow missing joints', default=False,
        description='Export characters whose skeleton lacks body joints the game needs (bosses, monsters): the '
                    'missing joints are copied from the replaced character, unconnected to any mesh. Expect a '
                    'broken-looking or crashing fighter')
    S.pd_char_move = EnumProperty(
        name='Movement', default='AUTO',
        items=[('AUTO', 'From the animation set', 'Cartwheel if the loaded battle set belongs to a cartwheeling '
                'character (Edgar, Cuff Button, pH, JD, Sammah...), else jump'),
               ('750', 'Jump', 'Movement skill 750'), ('751', 'Cartwheel', 'Movement skill 751: the dash / cartwheel. '
                'Needs a cartwheel motion: jumpers given it are reported to crash'),
               ('KEEP', 'Keep current', 'Leave it as it is')])
    S.pd_char_voice = EnumProperty(name='Voice', items=_voice_items,
                                   description='Voice and battle sound bank the character uses (Sound\\BattleVo_*)')
    S.pd_char_target_variant = EnumProperty(
        name='Colours', default='ALL',
        items=[('ALL', 'All 4 colours', 'Replace <id>0..3.alr')] +
              [(str(k), 'Colour %d only' % (k + 1), 'Replace <id>%d.alr only' % k) for k in range(4)])


def unregister_props():
    for p in ('pd_char_experimental', 'pd_char_hitbox', 'pd_char_move', 'pd_char_voice', 'pd_char_pick', 'pd_char_variant', 'pd_char_load_anims', 'pd_anim_set_pick', 'pd_char_action_index',
              'pd_char_target', 'pd_char_target_variant'):
        if hasattr(bpy.types.Scene, p):
            delattr(bpy.types.Scene, p)
