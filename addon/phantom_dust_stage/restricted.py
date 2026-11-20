"""Show restricted-area walls (collision surface 10: the barrier that keeps players in the arena) as see-through
red in the viewport, so they stand out from ordinary colliders. Display only: a red material on the object's own
material slots (object-linked, the mesh's materials are left alone); collision export ignores materials."""
import bpy

from . import convert as cv

SURFACE = 0x10
MATERIAL = 'PD Restricted Area'


def material():
    m = bpy.data.materials.get(MATERIAL)
    if m is None:
        m = bpy.data.materials.new(MATERIAL)
        m.diffuse_color = (1.0, 0.1, 0.1, 0.3)             # Solid view (colour by material)
        m.use_nodes = True
        bsdf = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf is not None:
            bsdf.inputs['Base Color'].default_value = (1.0, 0.1, 0.1, 1.0)
            bsdf.inputs['Alpha'].default_value = 0.3
        for attr, val in (('surface_render_method', 'BLENDED'), ('blend_method', 'BLEND')):
            try:
                setattr(m, attr, val)
            except (AttributeError, TypeError):
                pass
        m.use_backface_culling = False
    return m


def _mark(ob, on):
    m = material()
    me = ob.data
    if on:
        if not ob.material_slots:
            me.materials.append(m)
        for slot in ob.material_slots:
            if slot.material is not m:
                slot.link = 'OBJECT'
                slot.material = m
        ob.show_transparent = True
    else:
        for slot in ob.material_slots:
            if slot.material is m:
                if slot.link == 'OBJECT':
                    slot.material = None
                    slot.link = 'DATA'
        for i in range(len(me.materials) - 1, -1, -1):
            if me.materials[i] is m:
                me.materials.pop(index=i)


def refresh(scene=None):
    """Mark every collider whose surface (its own, else its collection's) is 10; unmark the rest."""
    scene = scene or bpy.context.scene
    from . import exporter
    colliders = set()
    for c in exporter.collections_with_role(scene, 'COLLIDERS'):
        colliders.add(c)
        colliders.update(c.children_recursive)
    seen = set()
    for c, st in exporter.collision_collections(scene):
        if c not in colliders:
            continue
        for ob in c.objects:
            if ob.type != 'MESH' or ob.name in seen:
                continue
            seen.add(ob.name)
            try:
                _mark(ob, cv.surface_value(getattr(ob, 'pd_surface', ''), st) == SURFACE)
            except (ValueError, RuntimeError):
                pass


def on_change(self, context):
    try:
        refresh(context.scene)
    except (RuntimeError, AttributeError):
        pass
