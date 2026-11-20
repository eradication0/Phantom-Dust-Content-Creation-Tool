"""Write map effects (EF00 at header 0x98) into a stage .dat.

An entry is 0x5C bytes: u8 kind, u8 layout filter (0 = always; otherwise shown only for layout value - 6),
u8 0xFF, u8 0, f32 position[3] (+4), f32 rotation[3] radians (+0x10), f32 scale[3] (+0x1C), then 13 values whose
meaning depends on the kind (+0x28). The kind picks the effect class through the game's table at 0x1402dc520
(FUN_1401ef940): see KINDS.

Effects are written as presets: an entry copied from one of the game's own maps (read from the user's files),
moved to a new position. The new table is appended to the end of the file and header 0x98 repointed.
"""
import struct

from . import dat

ENTRY = 0x5C

KINDS = {
    2: 'smoke', 3: 'smoke', 4: 'belt smoke', 5: 'glow', 6: 'crash', 7: 'jump point', 8: 'smoke', 9: 'crash',
    10: 'effect model', 11: 'sound', 12: 'sound', 13: 'effect model', 14: 'effect model', 15: 'effect model',
    16: 'screen shake', 17: 'screen shake', 18: 'water drops', 19: 'water drops',
    20: 'stage parameters (the stage variants picked at random per match)',
    21: 'steam', 22: 'steam', 23: 'sparks', 24: 'sparks',
}


# Effects that work in any map: the smoke, steam and sparks families (confirmed in game copied into another map).
# Every other kind used in the maps needs its home map's own files: glow (Twilight Lane) and water drops (Palace)
# their textures, effect models, sound emitters and break bursts an index into the map's own models/sounds.
# The presets are distinct parameter sets the game itself uses (all maps scanned), named from the effect test
# map (tools/effect_test_map.py); the game's own entry is copied from the user's files. The steam kind (22) also
# makes smoke and fire depending on its parameters. Black smoke (kind 2, Panorama Earthquake) shows in other maps.
PRESETS = {                     # key: (source map, effect index, name, stable id for Blender's saved files)
    'STEAM_PIPE':  ('st09', 137, 'Steam Pipe', 10),
    'SMOKE':       ('st09', 79,  'Smoke', 11),
    'FAINT_SMOKE': ('st09', 3,   'Faint Smoke', 12),
    'BLACK_SMOKE': ('st04', 21,  'Black Smoke (spread out)', 13),
    'FIRE':        ('st09', 17,  'Animated Fire (stuttery)', 14),
    'SPARKS':      ('st09', 75,  'Sparks', 15),
    'LIGHT_SPARKS': ('st09', 7,  'Light Sparks', 16),
}


def preset_entry(b, index):
    """Raw bytes of effect entry `index` of a stage .dat."""
    es = dat.effects(b)
    if not 0 <= index < len(es):
        raise IndexError('effect %d not found (the map has %d)' % (index, len(es)))
    return bytes(b[es[index]['offset']:es[index]['offset'] + ENTRY])


def place(raw, pos, yaw=0.0, scale=None, layout_filter=0):
    """A copy of a preset entry at `pos`, turned by `yaw` radians (added to its own Y rotation)."""
    e = bytearray(raw)
    e[1] = layout_filter
    struct.pack_into('<3f', e, 4, *pos)
    rx, ry, rz = struct.unpack_from('<3f', e, 0x10)
    struct.pack_into('<3f', e, 0x10, rx, ry + yaw, rz)
    if scale is not None:
        struct.pack_into('<3f', e, 0x1C, *scale)
    return bytes(e)


def set_effects(b, entries):
    """New .dat whose effect table is exactly `entries` (raw 0x5C-byte entries), appended at the end."""
    buf = bytearray(b)
    buf += b'\0' * (-len(buf) % 4)
    off = len(buf)
    buf += b'EF00' + struct.pack('<HH', len(entries), ENTRY * len(entries)) + b''.join(entries)
    struct.pack_into('<I', buf, dat.H_EF00, off)
    struct.pack_into('<I', buf, dat.H_FILE_SIZE, len(buf))
    return bytes(buf)
