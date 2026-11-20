"""Collision surface types: one byte per collision triangle.

The numbers are one global material list in the game (not per map): each picks the footstep sound, the landing
sound, whether attacks leave craters, and a few special behaviours. Tested by the user on a test map with a pad per
number (2026-11-18); 00, 03, 12, 14 and 1F corrected after Tinkerer_Red's research and a second test (2026-11-20). Valid numbers are 00-20: the game's footstep table (PDUWP.exe 0x1402f6270, two sound ids per
number) has 33 entries and the code ignores anything from 21 up. Untested numbers carry what that table says
about their steps.

MATERIALS: number -> (name, description, warning). SURFACES: how often each map uses each number (measured from
the game files), to mark the replaced map's own numbers in the dropdown.
"""

MATERIALS = {
    0x00: ('Silent, no craters', 'Solid floor and wall with no sounds at all: no steps, no landing sound, attacks '
                                 'leave no craters', False),
    0x01: ('Silent', 'No step sound, no landing sound, no craters', False),
    0x02: ('Metal, weak landing', 'Metal steps, a weak metal landing sound; craters', False),
    0x03: ('Metal (like 02)', 'Same as 02: metal steps, attacks leave craters', False),
    0x04: ('Plastic', 'Plastic steps, metal landing; craters', False),
    0x05: ('Metal', 'Metal steps, metal landing; craters', False),
    0x06: ('Plastic (like 04)', 'Plastic steps, metal landing; craters', False),
    0x07: ('Stone', 'Stone steps, stone landing; craters', False),
    0x08: ('Stone, strong landing', 'Stone steps, strong landing; craters. The most common floor', False),
    0x09: ('Stone, crackling landing', 'Stone steps, crackling landing; craters', False),
    0x0A: ('Wood', 'Wood steps, crackling landing; craters', False),
    0x0B: ('Pebbles', 'Pebble steps, no landing sound, no craters', False),
    0x0C: ('Broken: do not use', 'A bug in the game: each step starts a looping sound that never stops; after a '
                                   'while of running, other sounds stop playing', True),
    0x0D: ('Water', 'Water steps, glass landing; craters', False),
    0x0E: ('Silent, water landing', 'No steps, a water sound when landing', False),
    0x0F: ('Silent, plain landing', 'No steps, a generic landing sound', False),
    0x10: ('Restricted wall', 'The map edge: solid to everything, with a blob effect and a warning sound when '
                              'touched. Use on the invisible walls around the map', True),
    0x11: ('Respawn on touch', 'Touching it at all counts as falling off the map: -3 HP and a respawn', True),
    0x12: ('Character wall', 'Invisible wall for characters only: stops players, but the camera and attacks pass '
                             'through. Silent, no craters. The game puts it on railings and fences', True),
    0x13: ('Silent, no craters', 'Solid with no sounds and no craters (like 00)', False),
    0x14: ('Jump-through wall', 'Ledge guard: stops walking, running and dodging, but a jump passes through near '
                                'its top. The camera and attacks pass. Used on the edge of a walkway with a drop '
                                'behind it (Edgar\'s Dream). Not a floor: landing on it fails and players fall', True),
    0x15: ('Hollow pipe', 'Hollow pipe steps, no landing sound, but craters', False),
    0x16: ('Sticky', 'Sticky steps; no landing sound, no craters', False),
    0x17: ('Cloth', 'Cloth steps and a landing sound, but no craters', False),
    0x18: ('Ceramic', 'Ceramic steps, strong landing; craters', False),
    0x19: ('Rattling', 'Rattling steps, strong landing; craters', False),
    0x1A: ('Light steps', 'Light steps, strong landing; craters', False),
    0x1B: ('Metal grate', 'Metal grate steps, strong landing; craters', False),
    0x1C: ('Light wood', 'Light wood steps, strong landing; craters', False),
    0x1D: ('Grass', 'Grass steps, strong landing; craters', False),
    0x1E: ('Dirt', 'Dirt steps, strong landing; craters', False),
    0x1F: ('Camera wall', 'Invisible wall for the camera only: players and attacks pass through, the camera '
                          'cannot. Keeps the camera inside the arena (e.g. on top of the edge walls). Not a floor: '
                          'players fall through it', True),
    0x20: ('Dampened wood', 'Dampened wood steps, strong landing; craters', False),
}

SURFACES = {
    'st01': [(0x02, 1948, 'floors and walls', ('wall',)), (0x07, 345, 'walls', ('wall',)), (0x12, 340, 'floors and walls', ('wall',)), (0x14, 178, 'invisible walls', ('wall',)), (0x1F, 198, 'floors', ('wall',))],
    'st02': [(0x02, 44, 'floors and walls', ()), (0x05, 852, 'floors and walls', ('railing',)), (0x06, 282, 'walls', ()), (0x09, 2368, 'floors and walls', ()), (0x10, 51, 'invisible walls', ()), (0x12, 24, 'invisible walls', ()), (0x16, 24, 'floors and walls', ())],
    'st03': [(0x02, 36, 'floors', ('escalator', 'clutter', 'floor')), (0x04, 12, 'walls', ('shop front', 'grating')), (0x07, 344, 'walls', ('gate', 'floor')), (0x08, 885, 'floors and walls', ('gate', 'wall', 'floor')), (0x0A, 287, 'slopes', ('wood', 'floor', 'clutter')), (0x0B, 108, 'floors and walls', ('escalator', 'shop front', 'grating')), (0x0D, 32, 'floors', ('floor', 'escalator')), (0x10, 26, 'walls', ('gate', 'clutter', 'wall')), (0x12, 433, 'floors and walls', ('wood', 'escalator', 'clutter')), (0x16, 120, 'walls', ('escalator',)), (0x19, 28, 'walls', ('shutter', 'shop front', 'grating')), (0x1F, 309, 'slopes', ('wood', 'clutter', 'wall')), (0x20, 103, 'floors', ('floor', 'escalator', 'clutter'))],
    'st04': [(0x02, 33, 'floors and walls', ('lift',)), (0x07, 68, 'floors and walls', ('props', 'stone', 'concrete')), (0x08, 2130, 'floors and walls', ('concrete', 'props', 'lift')), (0x12, 16, 'floors and walls', ('concrete', 'floor', 'stone'))],
    'st05': [(0x01, 51, 'floors and walls', ('stone', 'metal')), (0x02, 16, 'floors and walls', ('metal', 'road', 'door')), (0x04, 100, 'floors and walls', ('clutter', 'metal', 'stone')), (0x10, 8, 'invisible walls', ()), (0x12, 165, 'walls', ('door', 'metal', 'clutter')), (0x18, 170, 'floors', ('window', 'door', 'stone')), (0x19, 14, 'floors', ('shutter', 'stone')), (0x1A, 173, 'floors and walls', ('metal', 'stone', 'sign')), (0x20, 498, 'floors and walls', ('stone', 'metal', 'road'))],
    'st06': [(0x01, 24, 'invisible walls', ()), (0x02, 1134, 'floors and walls', ()), (0x04, 282, 'floors and walls', ()), (0x05, 1009, 'floors and walls', ()), (0x06, 133, 'floors and walls', ()), (0x10, 16, 'invisible walls', ()), (0x12, 430, 'floors and walls', ()), (0x1A, 188, 'floors and walls', ()), (0x1B, 630, 'floors and walls', ())],
    'st07': [(0x05, 995, 'floors and walls', ('fence', 'wall', 'clutter')), (0x06, 178, 'floors and walls', ('fence', 'clutter', 'wires')), (0x08, 5927, 'floors and walls', ('wall', 'fence', 'road')), (0x0A, 214, 'floors', ('roof', 'tree', 'wall')), (0x10, 82, 'invisible walls', ('wall', 'clutter')), (0x12, 685, 'walls', ('wall', 'fence', 'tree')), (0x16, 214, 'walls', ('clutter', 'fence', 'wall')), (0x18, 582, 'floors and walls', ('window', 'wall', 'clutter')), (0x19, 68, 'floors and walls', ('wall', 'window')), (0x1A, 113, 'floors', ('roof', 'wall', 'clutter')), (0x1C, 88, 'floors', ('clutter', 'wall', 'wires')), (0x1D, 69, 'floors', ('wall', 'road', 'clutter')), (0x1E, 51, 'floors', ('gravel', 'clutter', 'wall')), (0x1F, 77, 'walls', ('wall', 'fence', 'window'))],
    'st08': [(0x04, 98, 'floors and walls', ()), (0x08, 2721, 'floors and walls', ()), (0x10, 40, 'invisible walls', ()), (0x18, 12, 'floors and walls', ()), (0x19, 336, 'floors and walls', ()), (0x1B, 359, 'floors and walls', ()), (0x1C, 256, 'floors and walls', ())],
    'st12': [(0x02, 44, 'floors and walls', ()), (0x05, 852, 'floors and walls', ('railing',)), (0x06, 282, 'walls', ()), (0x09, 2368, 'floors and walls', ()), (0x10, 51, 'invisible walls', ()), (0x12, 24, 'invisible walls', ()), (0x16, 24, 'floors and walls', ())],
    'st13': [(0x02, 36, 'floors', ('escalator', 'clutter', 'floor')), (0x04, 12, 'walls', ('shop front', 'grating')), (0x07, 344, 'walls', ('gate', 'floor')), (0x08, 885, 'floors and walls', ('gate', 'wall', 'floor')), (0x0A, 287, 'slopes', ('wood', 'floor', 'clutter')), (0x0B, 108, 'floors and walls', ('escalator', 'shop front', 'grating')), (0x0D, 32, 'floors', ('floor', 'escalator')), (0x10, 26, 'walls', ('gate', 'clutter', 'wall')), (0x12, 433, 'floors and walls', ('wood', 'escalator', 'clutter')), (0x16, 120, 'walls', ('escalator',)), (0x19, 28, 'walls', ('shutter', 'shop front', 'grating')), (0x1F, 309, 'slopes', ('wood', 'clutter', 'wall')), (0x20, 103, 'floors', ('floor', 'escalator', 'clutter'))],
    'st14': [(0x02, 33, 'floors and walls', ('lift',)), (0x07, 68, 'floors and walls', ('props', 'stone', 'concrete')), (0x08, 2130, 'floors and walls', ('concrete', 'props', 'lift')), (0x12, 16, 'floors and walls', ('concrete', 'floor', 'stone'))],
    'st15': [(0x01, 51, 'floors and walls', ('stone', 'metal')), (0x02, 16, 'floors and walls', ('metal', 'road', 'door')), (0x04, 100, 'floors and walls', ('clutter', 'metal', 'stone')), (0x10, 8, 'invisible walls', ()), (0x12, 165, 'walls', ('door', 'metal', 'clutter')), (0x18, 170, 'floors', ('window', 'door', 'stone')), (0x19, 14, 'floors', ('shutter', 'stone')), (0x1A, 173, 'floors and walls', ('metal', 'stone', 'sign')), (0x20, 498, 'floors and walls', ('stone', 'metal', 'road'))],
    'st16': [(0x01, 24, 'invisible walls', ()), (0x02, 1134, 'floors and walls', ()), (0x04, 282, 'floors and walls', ()), (0x05, 1009, 'floors and walls', ()), (0x06, 133, 'floors and walls', ()), (0x10, 16, 'invisible walls', ()), (0x12, 430, 'floors and walls', ()), (0x1A, 188, 'floors and walls', ()), (0x1B, 630, 'floors and walls', ())],
    'st17': [(0x05, 995, 'floors and walls', ('fence', 'wall', 'clutter')), (0x06, 178, 'floors and walls', ('fence', 'clutter', 'wires')), (0x08, 5927, 'floors and walls', ('wall', 'fence', 'road')), (0x0A, 214, 'floors', ('roof', 'tree', 'wall')), (0x10, 82, 'invisible walls', ('wall', 'clutter')), (0x12, 685, 'walls', ('wall', 'fence', 'tree')), (0x16, 214, 'walls', ('clutter', 'fence', 'wall')), (0x18, 582, 'floors and walls', ('window', 'wall', 'clutter')), (0x19, 68, 'floors and walls', ('wall', 'window')), (0x1A, 113, 'floors', ('roof', 'wall', 'clutter')), (0x1C, 88, 'floors', ('clutter', 'wall', 'wires')), (0x1D, 69, 'floors', ('wall', 'road', 'clutter')), (0x1E, 51, 'floors', ('gravel', 'clutter', 'wall')), (0x1F, 77, 'walls', ('wall', 'fence', 'window'))],
    'st22': [(0x02, 44, 'floors and walls', ()), (0x05, 852, 'floors and walls', ('railing',)), (0x06, 282, 'walls', ()), (0x09, 2368, 'floors and walls', ()), (0x10, 51, 'invisible walls', ()), (0x12, 24, 'invisible walls', ()), (0x16, 24, 'floors and walls', ())],
    'st23': [(0x02, 36, 'floors', ('escalator', 'clutter', 'floor')), (0x04, 12, 'walls', ('shop front', 'grating')), (0x07, 344, 'walls', ('gate', 'floor')), (0x08, 885, 'floors and walls', ('gate', 'wall', 'floor')), (0x0A, 287, 'slopes', ('wood', 'floor', 'clutter')), (0x0B, 108, 'floors and walls', ('escalator', 'shop front', 'grating')), (0x0D, 32, 'floors', ('floor', 'escalator')), (0x10, 26, 'walls', ('gate', 'clutter', 'wall')), (0x12, 433, 'floors and walls', ('wood', 'escalator', 'clutter')), (0x16, 120, 'walls', ('escalator',)), (0x19, 28, 'walls', ('shutter', 'shop front', 'grating')), (0x1F, 309, 'slopes', ('wood', 'clutter', 'wall')), (0x20, 103, 'floors', ('floor', 'escalator', 'clutter'))],
    'st24': [(0x07, 12, 'floors and walls', ('props', 'stone', 'concrete')), (0x08, 666, 'floors and walls', ('concrete', 'props', 'lift')), (0x12, 16, 'floors and walls', ('concrete', 'floor', 'stone'))],
    'st25': [(0x01, 51, 'floors and walls', ('stone', 'metal')), (0x02, 16, 'floors and walls', ('metal', 'road', 'door')), (0x04, 100, 'floors and walls', ('clutter', 'metal', 'stone')), (0x10, 8, 'invisible walls', ()), (0x12, 165, 'walls', ('door', 'metal', 'clutter')), (0x18, 170, 'floors', ('window', 'door', 'stone')), (0x19, 14, 'floors', ('shutter', 'stone')), (0x1A, 173, 'floors and walls', ('metal', 'stone', 'sign')), (0x20, 498, 'floors and walls', ('stone', 'metal', 'road'))],
    'st26': [(0x01, 24, 'invisible walls', ()), (0x02, 1210, 'floors and walls', ()), (0x04, 282, 'floors and walls', ()), (0x05, 1009, 'floors and walls', ()), (0x06, 133, 'floors and walls', ()), (0x10, 16, 'invisible walls', ()), (0x12, 430, 'floors and walls', ()), (0x1A, 188, 'floors and walls', ()), (0x1B, 630, 'floors and walls', ())],
}

# The add-on's surface dropdown: the usable numbers (all that leave craters, plus cloth and the three special ones),
# from the most generic to the most specialised. Others (silent, no collision, explosive...) stay reachable through
# "Other value".
DROPDOWN = [0x08, 0x07, 0x09, 0x1E, 0x1D, 0x0A, 0x1C, 0x20, 0x05, 0x02, 0x1B, 0x15, 0x04, 0x06, 0x18, 0x1A, 0x19, 0x0D,
            0x17, 0x01, 0x10, 0x12, 0x1F, 0x14, 0x11]

# Walls that stop only some things: never used as floors (players fall through 1F, cannot land on 14)
WALL_ONLY = (0x14, 0x1F)
# The game respawns a player who drops below this height (game units; tested on st03, 2026-11-20)
KILL_HEIGHT = 0.0
DEFAULT = 0x08


def of(game_original):
    return SURFACES.get(game_original, [])


def default_for(game_original):
    """The surface used when a collection sets none: plain stone (08), the most common one in the game. The numbers
    mean the same in every map, so the replaced map doesn't matter."""
    return DEFAULT


def name(value):
    m = MATERIALS.get(value)
    return m[0] if m else 'unknown'


_items = []


def enum_items(scene=None):
    """Dropdown entries for a collection's surface: inherit, the usable numbers by name, other."""
    if not _items:
        _items.append(('INHERIT', 'Same as parent (default: %02X %s)' % (DEFAULT, name(DEFAULT)),
                       'Use the parent collection\'s surface; at the top, %02X %s' % (DEFAULT, name(DEFAULT)), 0))
        for v in DROPDOWN:
            nm, desc, warn = MATERIALS[v]
            _items.append(('S%02X' % v, '%s  (%02X)' % (nm, v), desc, v + 1))
        _items.append(('CUSTOM', 'Other number...', 'Type a surface number in hex (00-20; the rest of the list '
                       'in FORMATS.md)', 999))
    return _items
