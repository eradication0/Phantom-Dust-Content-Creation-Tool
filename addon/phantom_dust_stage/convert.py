"""Game <-> Blender coordinates, map list and collection settings.

Game space is y-up and LEFT-handed (Direct3D); Blender is z-up and right-handed. So the conversion is a mirror:
blender = (x, z, y) * scale (swap y and z; its own inverse). Shown by the game's own signs: their text reads
left to right only this way (FORMATS.md). Being a mirror, it reverses triangle winding: every place that turns
triangles from one side to the other swaps two corners (see flip_winding), so faces and collision normals keep
pointing outwards. Turning about the vertical axis changes direction too: game yaw = -Blender rotation z.

Spawn facing: in game space the player faces (sin yaw, 0, cos yaw), in Blender (sin yaw, cos yaw, 0): the spawn
empty's +Y axis, so rotation_euler.z = -yaw.
"""
import math
import re

DEFAULT_SURFACE = 0x08      # the common floor/wall type
DEFAULT_SCALE = 0.1         # Blender units per game unit

# Battle maps (names from setup/stageset/stageset_en.dat). Exporting replaces one of these.
GAME_ORIGINALS = [
    ('st02', 'Spiral Highway'), ('st12', 'Lightning Highway'), ('st22', 'Sunlight Highway'),
    ('st03', 'Lost Palace'), ('st13', 'Light Palace'), ('st23', 'Noble Palace'),
    ('st04', 'Panorama Earthquake'), ('st14', 'Panorama Building'), ('st24', 'Panorama Boss'),
    ('st05', 'Dawn City'), ('st15', 'Dusk City'), ('st25', 'Midnight City'),
    ('st06', 'Storm Refinery'), ('st16', 'Sunset Refinery'), ('st26', 'Acid Refinery'),
    ('st07', 'Twilight Lane'), ('st17', 'Silent Lane'),
    ('st08', 'Sein'), ('st01', "Edgar's Dream"),
]

ROLES = [
    ('NONE', 'None', 'Not exported'),
    ('COLLIDERS', 'Colliders', 'Meshes in here (and in child collections) become collision'),
    ('SPAWNS', 'Spawn Points', 'Child collections are layouts; each holds spawn empties with 3 orb children'),
    ('VISUALS', 'Visuals', 'Visible meshes: replace the game original\'s stage model (child collections named '
                           'Background/Sky replace those, if enabled on export)'),
    ('OBJECTS', 'Objects', 'Props and breakables: each child collection is one object type (preset, debris, '
                           'collider); every mesh directly in it is one placement'),
    ('EFFECTS', 'Effects', 'Ambient effects: each child collection is one effect type (steam, sparks, smoke); '
                           'every object directly in it is one placement'),
    ('LIGHTING', 'Lighting', 'The sun and lamps Bake Lighting uses (not exported themselves)'),
]


def to_blender(v, s):
    return (v[0] * s, v[2] * s, v[1] * s)


def to_game(v, s):
    return (v[0] / s, v[2] / s, v[1] / s)


def flip_winding(tri):
    """A triangle's corners in the order that keeps it facing the same way on the other side of the mirror."""
    return (tri[0], tri[2], tri[1]) + tuple(tri[3:])


def yaw_to_blender(yaw):
    return wrap(-yaw)


def yaw_to_game(rz):
    return wrap(-rz)


def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


def surface_value(text, default):
    """Collection surface setting: hex text like "08" or "0x12"; empty = inherit."""
    text = (text or '').strip()
    return int(text, 16) if text else default


def natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', name)]


def _rot_game(rot):
    """Game rotation matrix (3x3, column vectors) for Euler angles (rx, ry, rz): Rz * Ry * Rx, as the game's
    node transforms (pdstage/alr.py _local)."""
    rx, ry, rz = rot
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    return [[cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
            [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
            [-sy, cy * sx, cy * cx]]


def _swap(m):
    """P m P with P swapping y and z (the game <-> Blender axes): rows and columns 1 and 2 swapped."""
    o = (0, 2, 1)
    return [[m[o[r]][o[c]] for c in range(3)] for r in range(3)]


def rot_to_blender(rot):
    """A placement's game rotation (rx, ry, rz radians) as a Blender 3x3 rotation matrix (nested lists)."""
    return _swap(_rot_game(rot))


def rot_to_game(m):
    """A Blender 3x3 rotation matrix (nested lists, no scale) as the game's (rx, ry, rz)."""
    g = _swap([list(r) for r in m])
    cy = math.hypot(g[0][0], g[1][0])
    ry = math.atan2(-g[2][0], cy)
    if cy > 1e-6:
        rx = math.atan2(g[2][1], g[2][2])
        rz = math.atan2(g[1][0], g[0][0])
    else:                                  # straight up or down (gimbal lock): put the turn in rx
        rz = 0.0
        rx = math.atan2(g[0][1], g[0][2]) if g[2][0] < 0 else math.atan2(-g[0][1], -g[0][2])
    return (wrap(rx), wrap(ry), wrap(rz))
