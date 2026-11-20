"""Build a small map from scratch in Blender, bake its lighting, save it and export it.

  blender -b --factory-startup --python examples/build_example_map.py -- <Assets/Data folder> <out_dir> [game_original]

Makes out_dir/example_map.blend (a template to copy) and exports out_dir/<game_original>.dat + .alr
(default game original st04, Panorama Earthquake). Nothing here comes from the game: geometry, textures, UVs,
lighting, colliders and spawns are all made in Blender.

Scene layout (the add-on's roles are set on the collections):
  Visuals       role Visuals       floor, walls, pillars, ramp, platform (textured, lit by PD_Light)
  Colliders     role Colliders     simple boxes for the same shapes (surface 08); child "Slopes" (07) holds the ramp
  Spawn_Points  role Spawn Points  LAYOUT_1: 4 spawns in the corners facing the middle, 3 orbs each
Scale 0.1: 1 Blender metre = 10 game units. The floor sits at z = 6.4 (game height 64), Panorama Earthquake's
main floor level.
"""
import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'addon'))
sys.path.insert(0, ROOT)
import phantom_dust_stage as addon          # noqa: E402
from phantom_dust_stage import visuals as pd_visuals  # noqa: E402  (material helper: texture x PD_Light)

args = sys.argv[sys.argv.index('--') + 1:]
data, out_dir = args[0], args[1]
game_original = args[2] if len(args) > 2 else 'st04'
os.makedirs(out_dir, exist_ok=True)
addon.register()

FLOOR_Z = 6.4
HALF = 15.0              # floor is 30 x 30 m
WALL_H = 6.0
TEX_REPEAT = 2.0         # metres per texture repeat

for o in list(bpy.data.objects):            # start empty (drop the default cube, camera and light)
    bpy.data.objects.remove(o)
scene = bpy.context.scene
scene.pd_game_original = game_original
scene.pd_scale = 0.1


def collection(name, parent=None, role='NONE', surface=''):
    c = bpy.data.collections.new(name)
    (parent or scene.collection).children.link(c)
    c.pd_role = role
    c.pd_surface = surface
    return c


# ---------------------------------------------------------------- textures (made here, not from the game)

def make_image(name, w, h, fn):
    img = bpy.data.images.new(name, w, h, alpha=False)
    px = []
    for y in range(h):
        for x in range(w):
            r, g, b = fn(x / w, y / h)
            px += (r, g, b, 1.0)
    img.pixels = px
    img.pack()
    return img


def tiles(u, v):                     # floor: grey tiles with dark grout
    gu, gv = (u * 4) % 1.0, (v * 4) % 1.0
    grout = gu < 0.05 or gv < 0.05
    shade = 0.55 + 0.1 * (((int(u * 4) + int(v * 4)) % 2))
    return (0.2, 0.2, 0.22) if grout else (shade, shade, shade * 1.05)


def bricks(u, v):                    # walls: red-brown bricks, offset rows
    row = int(v * 8)
    bu = (u * 4 + (0.5 if row % 2 else 0.0)) % 1.0
    mortar = (v * 8) % 1.0 < 0.1 or bu < 0.04
    return (0.75, 0.72, 0.65) if mortar else (0.55, 0.25 + 0.05 * (row % 3), 0.18)


def stripes(u, v):                   # ramp: yellow/black hazard stripes
    return (0.9, 0.75, 0.1) if ((u + v) * 6) % 1.0 < 0.5 else (0.08, 0.08, 0.08)


def metal(u, v):                     # pillars/platform: blue-grey panels (deliberately 300 x 200)
    edge = (u * 2) % 1.0 < 0.03 or (v * 2) % 1.0 < 0.03
    return (0.15, 0.17, 0.2) if edge else (0.35, 0.42, 0.5)


IMAGES = {
    'ex_floor': make_image('ex_floor', 256, 256, tiles),
    'ex_bricks': make_image('ex_bricks', 256, 256, bricks),
    'ex_stripes': make_image('ex_stripes', 128, 128, stripes),
    'ex_metal': make_image('ex_metal', 300, 200, metal),
}
MATERIALS = {k: pd_visuals._material(k + '_mat', img) for k, img in IMAGES.items()}


# ---------------------------------------------------------------- geometry

def box_mesh(name, size, cuts=0):
    """A box with optional subdivisions (more vertices = smoother baked lighting)."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    if cuts:
        bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts, use_grid_fill=True)
    bm.to_mesh(me)
    bm.free()
    return me


def planar_uvs(ob):
    """World-space box mapping: each face uses the two axes it lies along, one repeat per TEX_REPEAT metres."""
    me = ob.data
    uv = me.uv_layers.new(name='UVMap')
    mw = ob.matrix_world
    for poly in me.polygons:
        n = (mw.to_3x3() @ poly.normal)
        ax = max(range(3), key=lambda i: abs(n[i]))
        a, b = [(1, 2), (0, 2), (0, 1)][ax]
        for li in poly.loop_indices:
            p = mw @ me.vertices[me.loops[li].vertex_index].co
            uv.data[li].uv = (p[a] / TEX_REPEAT, p[b] / TEX_REPEAT)


def visual(name, size, loc, mat, cuts, coll, rot_x=0.0):
    ob = bpy.data.objects.new(name, box_mesh(name, size, cuts))
    ob.location = loc
    ob.rotation_euler = (rot_x, 0, 0)
    coll.objects.link(ob)
    bpy.context.view_layer.update()
    planar_uvs(ob)
    ob.data.materials.append(MATERIALS[mat])
    light = ob.data.color_attributes.new('PD_Light', 'BYTE_COLOR', 'POINT')
    ob.data.color_attributes.active_color = light
    return ob


def collider(name, size, loc, coll, rot_x=0.0):
    ob = bpy.data.objects.new(name, box_mesh(name, size))
    ob.location = loc
    ob.rotation_euler = (rot_x, 0, 0)
    ob.display_type = 'WIRE'
    ob.hide_render = True            # don't let colliders shadow their visible copies when baking
    coll.objects.link(ob)
    return ob


vis = collection('Visuals', role='VISUALS')
cols = collection('Colliders', role='COLLIDERS', surface='08')
slopes = collection('Slopes', cols, surface='07')

T = 1.0                                            # floor slab / wall thickness
parts = [
    # name,      size,                         location,                                 material,    cuts
    ('Floor',    (2 * HALF, 2 * HALF, T),       (0, 0, FLOOR_Z - T / 2),                  'ex_floor',  24),
    ('Wall_N',   (2 * HALF + 2 * T, T, WALL_H), (0, HALF + T / 2, FLOOR_Z + WALL_H / 2),  'ex_bricks', 10),
    ('Wall_S',   (2 * HALF + 2 * T, T, WALL_H), (0, -HALF - T / 2, FLOOR_Z + WALL_H / 2), 'ex_bricks', 10),
    ('Wall_E',   (T, 2 * HALF, WALL_H),         (HALF + T / 2, 0, FLOOR_Z + WALL_H / 2),  'ex_bricks', 10),
    ('Wall_W',   (T, 2 * HALF, WALL_H),         (-HALF - T / 2, 0, FLOOR_Z + WALL_H / 2), 'ex_bricks', 10),
    ('Pillar_1', (1.5, 1.5, WALL_H),            (-5, 4, FLOOR_Z + WALL_H / 2),            'ex_metal',  6),
    ('Pillar_2', (1.5, 1.5, WALL_H),            (5, -4, FLOOR_Z + WALL_H / 2),            'ex_metal',  6),
    ('Platform', (6, 6, 2.0),                   (HALF - 3, HALF - 3, FLOOR_Z + 1.0),      'ex_metal',  6),
]
for name, size, loc, mat, cuts in parts:
    visual(name, size, loc, mat, cuts, vis)
    if name != 'Floor':
        collider('COL_' + name, size, loc, cols)

collider('COL_Floor', (2 * HALF, 2 * HALF, T), (0, 0, FLOOR_Z - T / 2), cols)
# (A test build left a hidden gap in this floor collider: a player who fell through was put back on the map by
#  the game, so maps need no kill height.)

# Ramp from the floor up to the platform top (2 m over 6 m), along +Y next to the platform
ramp_len = math.hypot(6.0, 2.0)
ramp_rot = math.atan2(2.0, 6.0)
ramp_loc = (HALF - 3, HALF - 6 - 3, FLOOR_Z + 1.0 - 0.25)
visual('Ramp', (4, ramp_len, 0.5), ramp_loc, 'ex_stripes', 8, vis, rot_x=ramp_rot)
collider('COL_Ramp', (4, ramp_len, 0.5), ramp_loc, slopes, rot_x=ramp_rot)

# ---------------------------------------------------------------- spawns: 4 corners facing the middle
sp = collection('Spawn_Points', role='SPAWNS')
lay = collection('LAYOUT_1', sp)
corners = [(-11, -11), (11, -11), (-11, 11), (3, 11)]
for i, (x, y) in enumerate(corners, 1):
    e = bpy.data.objects.new('SPAWN_%d' % i, None)
    e.empty_display_type = 'ARROWS'
    e.empty_display_size = 2.0
    e.location = (x, y, FLOOR_Z + 0.3)
    # +Y of the empty is the facing. Turning by t about Z sends +Y to (-sin t, cos t); aim it at the middle.
    e.rotation_euler = (0, 0, math.atan2(x, -y))
    lay.objects.link(e)
    for k in range(1, 4):
        o = bpy.data.objects.new('SPAWN_%d_ORB_%d' % (i, k), None)
        o.empty_display_type = 'SPHERE'
        o.empty_display_size = 0.4
        o.parent = e
        o.location = (0, 2.0 + 1.5 * k, 0.5)          # in front of the spawn, along its +Y
        lay.objects.link(o)

# ---------------------------------------------------------------- sky dome and background (replace the city)
def sky_colour(u, v):                 # v = 0 at the bottom of the image (horizon), 1 at the top (zenith)
    t = min(1.0, v * 1.4)
    return (0.75 - 0.6 * t, 0.85 - 0.5 * t, 0.95 - 0.25 * t)


def sand(u, v):
    n = (math.sin(u * 91.7) * math.sin(v * 77.3) + math.sin(u * 23.1 + v * 41.9)) * 0.05
    return (0.62 + n, 0.55 + n, 0.42 + n)


IMAGES['ex_sky'] = make_image('ex_sky', 8, 128, sky_colour)
IMAGES['ex_sand'] = make_image('ex_sand', 128, 128, sand)
for k in ('ex_sky', 'ex_sand'):
    MATERIALS[k] = pd_visuals._material(k + '_mat', IMAGES[k])


def white_light(me):
    light = me.color_attributes.new('PD_Light', 'BYTE_COLOR', 'POINT')
    for d in light.data:
        d.color_srgb = (1, 1, 1, 1)
    me.color_attributes.active_color = light


sky_coll = collection('Sky', vis)
bm = bmesh.new()
bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=1200.0)
bmesh.ops.reverse_faces(bm, faces=bm.faces[:])                 # face inwards: seen from inside
me = bpy.data.meshes.new('SkyDome')
bm.to_mesh(me)
bm.free()
uvl = me.uv_layers.new(name='UVMap')
for poly in me.polygons:
    for li in poly.loop_indices:
        p = me.vertices[me.loops[li].vertex_index].co
        elev = max(0.0, p.z / 1200.0)                          # 0 at the horizon and below, 1 at the top
        uvl.data[li].uv = (0.5, 0.02 + 0.96 * elev)
me.materials.append(MATERIALS['ex_sky'])
white_light(me)
sky = bpy.data.objects.new('SkyDome', me)
sky.hide_render = True                                         # not part of the lighting bake
sky_coll.objects.link(sky)

bg_coll = collection('Background', vis)
bm = bmesh.new()
# A grid, not one big polygon: each triangle may span at most 8 texture repeats. 1600 m square (corners inside
# the 1200 m sky dome), 12 x 12 cells of ~133 m, one texture repeat per 25 m.
bmesh.ops.create_grid(bm, x_segments=12, y_segments=12, size=800.0)
me = bpy.data.meshes.new('Ground')
bm.to_mesh(me)
bm.free()
uvl = me.uv_layers.new(name='UVMap')
for poly in me.polygons:
    for li in poly.loop_indices:
        p = me.vertices[me.loops[li].vertex_index].co
        uvl.data[li].uv = (p.x / 25.0, p.y / 25.0)
me.materials.append(MATERIALS['ex_sand'])
white_light(me)
ground = bpy.data.objects.new('Ground', me)
ground.location = (0, 0, FLOOR_Z - 20.0)
ground.hide_render = True
bg_coll.objects.link(ground)

# ---------------------------------------------------------------- objects: a breakable crate and a bench
def lit_box_mesh(name, lo, hi, mat):
    """A box mesh around the origin with box-mapped UVs and simple lighting by face direction."""
    size = tuple(hi[k] - lo[k] for k in range(3))
    me = box_mesh(name, size)
    centre = Vector(tuple((hi[k] + lo[k]) / 2 for k in range(3)))
    for v in me.vertices:
        v.co += centre
    tmp = bpy.data.objects.new('_tmp', me)
    scene.collection.objects.link(tmp)
    planar_uvs(tmp)
    bpy.data.objects.remove(tmp)
    me.materials.append(MATERIALS[mat])
    light = me.color_attributes.new('PD_Light', 'BYTE_COLOR', 'CORNER')
    for poly in me.polygons:
        s = 1.0 if poly.normal.z > 0.5 else (0.45 if poly.normal.z < -0.5 else 0.8)
        for li in poly.loop_indices:
            light.data[li].color_srgb = (s, s, s, 1.0)
    me.color_attributes.active_color = light
    return me


def join_meshes(name, meshes):
    bm = bmesh.new()
    for m in meshes:
        bm.from_mesh(m)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(meshes[0].materials[0])
    return me


def model_object(name, me, coll):
    ob = bpy.data.objects.new(name, me)
    ob.hide_render = True                          # keep pieces out of the lighting bake
    coll.objects.link(ob)
    return ob


objs = collection('Objects', role='OBJECTS')

crate_type = collection('Crate', objs)
crate_type.pd_preset = 'BREAK_SCATTER'
crate_type.pd_hits = 3                 # takes 3 hits
crate_type.pd_damage = 10              # flying debris hurts
crate_mesh = lit_box_mesh('Crate', (-1, -1, 0), (1, 1, 2), 'ex_metal')
for i, (x, y, rz) in enumerate([(-4, -3, 0.3), (-1.5, -4.5, 0.0), (3.5, 3, 1.0)]):
    ob = bpy.data.objects.new('Crate.%03d' % i if i else 'Crate', crate_mesh)
    ob.location = (x, y, FLOOR_Z)
    ob.rotation_euler = (0, 0, rz)
    ob.hide_render = True
    crate_type.objects.link(ob)
crate_debris = collection('Debris', crate_type)
model_object('Crate_debris', join_meshes('Crate_debris', [
    lit_box_mesh('cd', (x - 0.4, y - 0.4, 0), (x + 0.4, y + 0.4, 0.7), 'ex_metal')
    for x, y in ((-0.6, -0.5), (0.5, -0.6), (-0.4, 0.6), (0.6, 0.5))]), crate_debris)

bench_type = collection('Bench', objs)
bench_type.pd_preset = 'CRUMBLE'
bench_type.pd_debris_stays = True
bench_type.pd_damage = 5
seat = lit_box_mesh('seat', (-2, -0.6, 0.8), (2, 0.6, 1.1), 'ex_bricks')
leg_l = lit_box_mesh('leg_l', (-1.8, -0.5, 0), (-1.4, 0.5, 0.8), 'ex_bricks')
leg_r = lit_box_mesh('leg_r', (1.4, -0.5, 0), (1.8, 0.5, 0.8), 'ex_bricks')
bench_mesh = join_meshes('Bench', [seat, leg_l, leg_r])
for i, (x, y, rz) in enumerate([(0, 13, 0.0), (-13, 0, math.pi / 2)]):
    ob = bpy.data.objects.new('Bench.%03d' % i if i else 'Bench', bench_mesh)
    ob.location = (x, y, FLOOR_Z)
    ob.rotation_euler = (0, 0, rz)
    ob.hide_render = True
    bench_type.objects.link(ob)
bench_broken = collection('Broken', bench_type)
model_object('Bench_piece_L', join_meshes('Bench_piece_L', [lit_box_mesh('pl', (-2, -0.6, 0.6), (-0.1, 0.6, 0.9), 'ex_bricks'), leg_l]), bench_broken)
model_object('Bench_piece_R', join_meshes('Bench_piece_R', [lit_box_mesh('pr', (0.1, -0.6, 0.4), (2, 0.6, 0.7), 'ex_bricks'), leg_r]), bench_broken)
pad_type = collection('JumpPad', objs)
pad_type.pd_preset = 'JUMP_PAD'
pad_type.pd_jump_power = 200
pad_mesh = lit_box_mesh('JumpPad', (-1.5, -1.5, 0), (1.5, 1.5, 0.1), 'ex_stripes')
pad = bpy.data.objects.new('JumpPad', pad_mesh)
pad.location = (0, -6, FLOOR_Z)
pad.hide_render = True
pad_type.objects.link(pad)

bench_debris = collection('Debris', bench_type)
model_object('Bench_debris', join_meshes('Bench_debris', [
    lit_box_mesh('bd1', (-1.8, -0.5, 0), (-0.2, 0.5, 0.3), 'ex_bricks'),
    lit_box_mesh('bd2', (0.2, -0.5, 0), (1.8, 0.5, 0.3), 'ex_bricks')]), bench_debris)

# ---------------------------------------------------------------- effects: steam, sparks, smoke
effects = collection('Effects', role='EFFECTS')
for name, preset, spots in (('Steam', 'STEAM', [(-5, 5.2, FLOOR_Z), (5, -2.8, FLOOR_Z)]),
                            ('Sparks', 'SPARKS', [(9.5, 9.5, FLOOR_Z + 2.5)]),
                            ('Smoke', 'SMOKE', [(-12, -12, FLOOR_Z)])):
    ec = collection(name, effects)
    ec.pd_effect = preset
    for i, loc in enumerate(spots):
        e = bpy.data.objects.new('%s_%d' % (name, i + 1), None)
        e.empty_display_type = 'CONE'
        e.location = loc
        ec.objects.link(e)

# ---------------------------------------------------------------- bake lighting into PD_Light
world = bpy.data.worlds.new('World')
scene.world = world
world.use_nodes = True
world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.55, 0.6, 0.7, 1)
world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.6
sun = bpy.data.objects.new('Sun', bpy.data.lights.new('Sun', 'SUN'))
sun.data.energy = 3.0
sun.rotation_euler = (math.radians(50), math.radians(15), math.radians(35))
scene.collection.objects.link(sun)
# Game lighting (Scene Properties > Phantom Dust Lighting): the game's own light follows the same sun, so
# characters and the game's shading of the stage agree with the bake. Colours stay at their defaults.
scene.pd_light_custom = True
scene.pd_sun = sun

scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 32
bpy.context.view_layer.update()
for ob in bpy.context.view_layer.objects:
    ob.select_set(False)
visuals = [o for o in vis.objects]          # the map itself (not the sky or background in child collections)
for o in visuals:
    o.select_set(True)
bpy.context.view_layer.objects.active = visuals[0]
bpy.ops.object.bake(type='DIFFUSE', pass_filter={'DIRECT', 'INDIRECT'}, target='VERTEX_COLORS')
lum = []
for o in visuals:
    for c in o.data.color_attributes['PD_Light'].data:
        lum.append(sum(c.color_srgb[:3]) / 3)
print('BAKED lighting: %d vertices, brightness min %.2f mean %.2f max %.2f' % (len(lum), min(lum), sum(lum) / len(lum), max(lum)))

# Normalise so the brightest vertex is white (the game multiplies the texture by this colour)
peak = max(lum) or 1.0
for o in visuals:
    for c in o.data.color_attributes['PD_Light'].data:
        r, g, b, a = c.color_srgb
        c.color_srgb = (min(1, r / peak), min(1, g / peak), min(1, b / peak), 1.0)

blend = os.path.join(out_dir, 'example_map.blend')
bpy.ops.wm.save_as_mainfile(filepath=blend)
print('SAVED', blend)

out = os.path.join(out_dir, game_original + '.dat')
res = bpy.ops.export_scene.phantom_dust_stage(filepath=out, game_original=game_original, game_data=data,
                                              background_and_sky=True)
print('EXPORT', res, out)
