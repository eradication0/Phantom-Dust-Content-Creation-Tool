"""Shadow casters: meshes in a "ShadowCasters" collection become the stage's shadow volumes (shader sshadowc,
position only): closed shapes, already stretched along the sun, that darken the characters inside them. The
export writes them as they are; the Stretch/Fix Shadow Casters button makes them: a mesh's faces turned to the
sun stay as the top, a copy goes down along the Sun to just below the kill height (game y = -1), and walls join
the two. A stretched mesh remembers which bottom corner belongs to which top corner (point attribute pd_top), so
pressing the button again after turning the Sun only moves the bottom.
Without the collection the export writes a tiny box far below the map (character shadows on, no stage shadows).

No real-time point lights: the game's maps (battle and campaign) never light the stage or characters with the
lighting script's point lights (only the far background); the campaign lights characters with each area's
character light (set 1: colour and direction) and bakes the rest.
"""
import bpy
from mathutils import Vector

from . import convert as cv
from . import exporter

SHADOW_ROLE = 'SHADOWS'
STRETCHED = 'pd_shadow_stretched'     # object property: already a stretched volume
TOP = 'pd_top'                          # point attribute: the top corner a bottom corner hangs from (-1: top)
BOTTOM_Y = -1.0                         # game units: just below the kill height (0)


def in_role(ob, role):
    return any(ob.name in c.all_objects for c in exporter.collections_with_role(bpy.context.scene, role))


def sun_blender(scene):
    """The way the scene Sun's light travels (Blender space, normalised), or None without a sun."""
    from . import lightbake
    sun = scene.pd_sun
    if sun is None or sun.type != 'LIGHT' or sun.name not in scene.objects:
        sun = next((o for o in lightbake.lights(scene) if o.data.type == 'SUN'), None)
    if sun is None:
        return None
    return (sun.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()


def _down_to(p, d, z):
    """p moved along d until it reaches height z (not upwards)."""
    k = max(p.z - z, 0.0) / -d.z
    return p + d * k


def stretch(ob, d, z):
    """Make ob a shadow volume along d down to height z (see the module notes). Returns an error or None."""
    me = ob.data
    mw = ob.matrix_world
    imw = mw.inverted_safe()
    nmat = mw.to_3x3().inverted_safe().transposed()
    attr = me.attributes.get(TOP)
    if ob.get(STRETCHED):
        if attr is None or attr.domain != 'POINT':
            return 'was stretched elsewhere (imported): delete it and stretch a new one'
        tops = [a.value for a in attr.data]
        for i, t in enumerate(tops):
            if 0 <= t < len(me.vertices):
                me.vertices[i].co = imw @ _down_to(mw @ me.vertices[t].co, d, z)
        me.update()
        return None
    faces = [tuple(p.vertices) for p in me.polygons if (nmat @ p.normal).dot(-d) > 0.0]
    if not faces:                                  # nothing faces the sun: use the other side of every face
        faces = [tuple(reversed(p.vertices)) for p in me.polygons]
    if not faces:
        return 'has no faces'
    used = sorted({i for f in faces for i in f})
    top = {old: new for new, old in enumerate(used)}
    verts = [me.vertices[i].co.copy() for i in used]
    n = len(verts)
    verts += [imw @ _down_to(mw @ co, d, z) for co in verts[:n]]
    out = [tuple(top[i] for i in f) for f in faces]
    out += [tuple(n + top[i] for i in reversed(f)) for f in faces]
    directed = {(f[k], f[(k + 1) % len(f)]) for f in faces for k in range(len(f))}
    for a, b in directed:
        if (b, a) not in directed:                 # an outer edge of the top: a wall down to the bottom
            out.append((top[b], top[a], n + top[a], n + top[b]))
    me.clear_geometry()
    me.from_pydata([tuple(v) for v in verts], [], out)
    a = me.attributes.new(TOP, 'INT', 'POINT')
    a.data.foreach_set('value', [-1] * n + list(range(n)))
    me.validate()
    me.update()
    ob[STRETCHED] = True
    return None


class PDSTAGE_OT_stretch_shadow_casters(bpy.types.Operator):
    """Turn every shadow caster into a shadow volume: its faces turned to the Sun stay as the top, the bottom
    goes down along the Sun to just below the kill height. Already stretched ones only move their bottom to
    follow the Sun's current direction"""
    bl_idname = 'pdstage.stretch_shadow_casters'
    bl_label = 'Stretch/Fix Shadow Casters'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        d = sun_blender(scene)
        if d is None:
            self.report({'ERROR'}, 'No Sun: add one to the Lighting collection')
            return {'CANCELLED'}
        if d.z > -0.05:
            self.report({'ERROR'}, 'The Sun shines upwards or flat: point it down')
            return {'CANCELLED'}
        if context.object is not None and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        z = BOTTOM_Y * scene.pd_scale
        done, fixed, errors = 0, 0, []
        for c in exporter.collections_with_role(scene, SHADOW_ROLE):
            for o in c.all_objects:
                if o.type != 'MESH':
                    continue
                again = bool(o.get(STRETCHED))
                err = stretch(o, d, z)
                if err:
                    errors.append('%s %s' % (o.name, err))
                elif again:
                    fixed += 1
                else:
                    done += 1
        if not done and not fixed and not errors:
            self.report({'WARNING'}, 'No meshes in a Shadow Casters collection')
            return {'CANCELLED'}
        msg = 'Stretched %d, turned to the Sun %d' % (done, fixed)
        if errors:
            self.report({'WARNING'}, msg + '; ' + '; '.join(errors))
        else:
            self.report({'INFO'}, msg)
        return {'FINISHED'}


def sun_direction(scene):
    """The way the scene Sun's light travels, in game space (straight down without a sun): the export stretches
    the shadow volumes along it on maps whose shadows are pre-stretched (sshadowc)."""
    from . import lightbake
    sun = scene.pd_sun
    if sun is None or sun.type != 'LIGHT' or sun.name not in scene.objects:
        sun = next((o for o in lightbake.lights(scene) if o.data.type == 'SUN'), None)
    if sun is None:
        return (0.0, -1.0, 0.0)
    d = Vector(cv.to_game(sun.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0)), 1.0)).normalized()
    return tuple(d)


def shadow_meshes(context, scale):
    """Meshes of the ShadowCasters collections as writer meshes (game space: verts [(position, normal)],
    tris), or [] when there are none."""
    scene = context.scene
    deps = context.evaluated_depsgraph_get()
    out, seen = [], set()
    for c in exporter.collections_with_role(scene, SHADOW_ROLE):
        for o in c.all_objects:
            if o.type != 'MESH' or o.name in seen:
                continue
            seen.add(o.name)
            ev = o.evaluated_get(deps)
            me = ev.to_mesh()
            try:
                me.calc_loop_triangles()
                mw = o.matrix_world
                nm = mw.to_3x3().inverted_safe().transposed()
                verts, tris = [], []
                for lt in me.loop_triangles:
                    n = Vector(cv.to_game(nm @ lt.normal, 1.0))
                    n = tuple(n.normalized()) if n.length > 0 else (0.0, 1.0, 0.0)
                    idx = []
                    for vi in lt.vertices:
                        idx.append(len(verts))
                        verts.append((cv.to_game(mw @ me.vertices[vi].co, scale), n))
                    tris.append(cv.flip_winding(tuple(idx)))
                if tris:
                    out.append(dict(verts=verts, tris=tris, name=o.name, stretched=bool(o.get(STRETCHED))))
            finally:
                ev.to_mesh_clear()
    return out


class PDSTAGE_PT_shadow_caster(bpy.types.Panel):
    bl_label = 'Phantom Dust Shadow Caster'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'object'

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.type == 'MESH' and in_role(ob, SHADOW_ROLE)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.scale_y = 0.8
        ob = context.object
        col.label(text='Casts real-time shadows in game (not drawn)', icon='INFO')
        col.label(text='Stretched: %s' % ('yes' if ob.get(STRETCHED) else 'no, press the button'),
                  icon='BLANK1')
        self.layout.operator(PDSTAGE_OT_stretch_shadow_casters.bl_idname, icon='LIGHT_SUN')


classes = (PDSTAGE_OT_stretch_shadow_casters, PDSTAGE_PT_shadow_caster)


def register_props():
    pass


def unregister_props():
    pass
