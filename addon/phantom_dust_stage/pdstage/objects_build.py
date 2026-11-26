"""Write placed objects (props, breakables, jump pads...) into a stage .dat.

How the game uses them (PDUWP.exe FUN_140203720 / FUN_140203dc0, and Esper-RE st00.h):
- NM00 (header 0x5C, count at 0x60): object names, NUL-terminated.
- OB00 (header 0x90): one 0x38-byte entry per object: 3 .alr root indices (model per state: intact, broken,
  debris; FFFFFFFF = none), then 9 file offsets (FFFFFFFF = none): [3..5] unknown, [6] collision chain for the
  intact state, [7..8] unused in maps, [9] effect block (EF00) for the intact state, [10..11] unused. [12..13]
  are 0 and FFFFFFFF in the first entry and uninitialised in the rest.
- Placement tables (header 0x04 + 4*slot, count at 0x30 + 4*slot): 0x24-byte entries: s32 object index,
  u8 category, u8 type, u8, u8, u32 0, f32 position[3], f32 rotation[3] (radians). A match uses slot
  (layout + 1) and falls back to slot 0.
- Object sounds (header 0xF8): one 16-byte entry per object (8 x u16, FFFF = none): [1] the sound when it is hit or
  breaks, [2] the sound of its loose pieces hitting things (an index into the game's sound pairs, 0x1402dc640).
  There must be an entry for every object: a piece of an object past the end of the table plays a garbage sound
  number and crashes the game (FUN_140240a00) the first time it hits something.
- category/type choose the object's class through the game's factory table (0x1402dc4f0). Category 2 is the
  destructible family; see PRESETS.

Everything new is appended to the end of the file and the header offsets are pointed at it (the same method
confirmed in game for collision), so nothing else in the file moves.
"""
import struct

from . import dat
from .collision_build import build_block, OBJECT_GRID

NONE = 0xFFFFFFFF

# Behaviour presets: name -> (category, type, description, states used). From the game's object factory table
# (0x1402dc4f0): each category/type builds a class made of behaviour parts, read from the classes' names (RTTI):
# Hit = reacts to attacks, Brk = breakable, Roll = broken pieces become rolling physics bodies, Crm = pieces crumble
# in place, Tch = breaks on touch, Wall / Ceil(ing) / Jump, NoCam = the camera ignores it. States: I intact,
# B broken (pieces), D debris.
PRESETS = {
    'SOLID':       (1, 4,  'Never breaks (lamps, signs)', 'I'),
    'BREAK_SCATTER': (2, 1, 'Breaks; debris flies off (boxes, chairs)', 'ID'),
    'BREAK_ROLL':  (2, 2,  'Breaks; debris rolls away (cones, barricades)', 'ID'),
    'CRUMBLE':     (2, 3,  'Pieces collapse where it stood (desks, fences)', 'IBD'),
    'BREAK_TOUCH': (2, 18, 'Shatters when a player touches it (glass)', 'IBD'),
    'WALL':        (2, 7,  'Wall; pieces topple over', 'IB'),
    'WALL_CRUMBLE': (2, 8, 'Wall; pieces collapse in place', 'IB'),
    'CEILING':     (2, 12, 'Hangs overhead; falls when hit', 'IB'),
    'PILLAR':      (2, 48, 'Pillar; pieces collapse in place', 'IB'),
    'JUMP_PAD':    (4, 16, 'Launches players into the air', 'I'),
    # The game's own special breakables (type numbers past 20)
    'BREAK_SOLID': (1, 15, 'Breaks, but its pieces never move (car)', 'IB'),
    'BRIDGE_SECTION': (2, 4, 'Only some hits break it; pieces roll', 'IBD'),
    'TOUCH_ROLL':  (2, 17, 'Breaks when touched; debris rolls (gift box)', 'ID'),
    'COLLAPSING_FLOOR': (2, 23, 'Floor or bridge; pieces fall away', 'IB'),
    'SUPPORT_PILLAR': (2, 28, 'Breaks when what rests on it breaks', 'IB'),
    'FALLING_SIGN': (2, 53, 'Attacks don\'t break it; falls by itself', 'IBD'),
    'EVENT_PROP':  (2, 54, 'Moved by the map, can\'t be broken', 'I'),
    'FALLING_BRIDGE': (2, 58, 'Falls, then collapses', 'IB'),
    'RUBBLE':      (2, 74, 'Breaks; debris flies off (rubble)', 'ID'),
    'GAME':        (None, None, 'Kept as the imported map had it', 'IBD'),
}

# Object sounds (header 0xF8 entries): the values the game's own objects use, with what uses them
BREAK_SOUNDS = [         # [1]: when it is hit or breaks
    (0xFFFF, 'No sound', 'Silent (some of the game\'s own fences and signs)'),
    (0x11, 'Light metal', 'Barricades, cones, street lamps, road signs, handrails (Spiral Highway)'),
    (0x13, 'Wall', 'Walls, pillars, handrails (Lost Palace)'),
    (0x14, 'Wooden furniture', 'Benches, chairs, tables (Lost Palace)'),
    (0x15, 'Glass', 'Glass handrails (Lost Palace)'),
    (0x16, 'Concrete', 'Bridges, floors, broken gates, containers'),
    (0x17, 'Heavy metal', 'Cars, oil cans, tanks'),
    (0x18, 'Iron road', 'Iron road sections (Spiral Highway)'),
    (0x19, 'Big metal', 'Containers, helicopter (Lunar Plains)'),
    (0x1A, 'Cardboard', 'Gift boxes, cardboard boxes'),
    (0x1C, 'Office chair', 'Office chairs (Silent Sanctuary)'),
    (0x1D, 'Railing', 'Fences, guardrails, handrails (Lunar Plains)'),
]
PIECE_SOUNDS = [         # [2]: its loose pieces hitting things
    (0xFFFF, 'No sound', 'Silent (most of the game\'s own objects)'),
    (0x24, 'Heavy rubble', 'Walls, pillars, containers, helicopter'),
    (0x25, 'Glass shards', 'Glass handrails'),
    (0x26, 'Concrete pieces', 'Bridges, floors, broken gates'),
]

# Types whose class moves the object by its own animation (Mvan): without one the game crashes on load
NEEDS_ANIMATION = {(2, 6), (2, 26)}

# Short names for the dropdown and for imported collections: what the object does
LABELS = {
    'SOLID': 'Unbreakable', 'BREAK_SCATTER': 'Debris Flies Off', 'BREAK_ROLL': 'Debris Rolls Away',
    'CRUMBLE': 'Collapse in Place', 'BREAK_TOUCH': 'Shatter on Touch', 'WALL': 'Wall, Topples',
    'WALL_CRUMBLE': 'Wall, Collapses', 'CEILING': 'Falls from Ceiling', 'PILLAR': 'Pillar, Collapses',
    'JUMP_PAD': 'Jump Pad', 'BREAK_SOLID': 'Breaks, Stays Put', 'BRIDGE_SECTION': 'Breaks from Some Hits',
    'TOUCH_ROLL': 'Breaks on Touch, Rolls', 'COLLAPSING_FLOOR': 'Floor Falls Away',
    'SUPPORT_PILLAR': 'Breaks with Load Above', 'FALLING_SIGN': 'Falls by Itself', 'EVENT_PROP': 'Moved by Map',
    'FALLING_BRIDGE': 'Falls, then Collapses', 'RUBBLE': 'Rubble, Flies Off', 'GAME': 'Other Game Type',
}

# What each behaviour does, for the Collection panel (lines). "Pieces" = the Broken child collection, "debris" =
# the Debris child collection, both optional.
HELP = {
    'SOLID': ('Never breaks. It blocks players and attacks like a', 'piece of the map; the camera passes through it.',
              'The game uses it for lamps and signs.'),
    'BREAK_SCATTER': ('Takes "Hits to break" hits, then breaks: the Debris', 'model is launched in the direction of the hit and',
                      'bounces and rolls along the floor (it can hurt', 'players it hits). Boxes, chairs, handrails.', 'Resting on another object: it falls when that one', 'breaks (the game checks straight down).'),
    'BREAK_ROLL': ('Same game behaviour family as Break Scatter (debris', 'launched and rolling); the game uses it for cones',
                   'and barricades. How the two differ in play is not', 'measured yet: try both.', 'Resting on another object: it falls when that one', 'breaks (the game checks straight down).'),
    'CRUMBLE': ('Takes "Hits to break" hits, then turns into its Broken', 'pieces, which collapse where it stood instead of',
                'flying away; the Debris model is what is left over.', 'Desks, benches, fences.', 'Resting on another object: it falls when that one', 'breaks (the game checks straight down).'),
    'BREAK_TOUCH': ('Shatters the moment a player runs into it, no hits', 'needed; the pieces collapse in place.',
                    'The game uses it for glass railings.'),
    'WALL': ('A wall that blocks like the map until it breaks;', 'then its Broken pieces topple over and roll.'),
    'WALL_CRUMBLE': ('A wall that blocks like the map until it breaks;', 'then its Broken pieces collapse straight down.'),
    'CEILING': ('Hangs overhead. When hit it falls down, and its', 'Broken pieces roll where they land (they can hurt',
                'players: Debris damage).'),
    'PILLAR': ('A pillar: after its hits it breaks into its Broken', 'pieces, which collapse in place.'),
    'BREAK_SOLID': ('Takes "Hits to break" hits, then swaps to its Broken', 'model. Its pieces stay where they are (no physics);',
                    'the game uses it for the car on Spiral Highway.'),
    'BRIDGE_SECTION': ('A big section (Light Palace bridges X/Y): only', 'some hits break it (the game checks the hit first),',
                       'then its pieces roll. Pieces named stay_ stay put.'),
    'TOUCH_ROLL': ('Breaks the moment a player touches it; the Debris', 'model rolls away. Light Palace gift box.'),
    'COLLAPSING_FLOOR': ('A walkway that breaks under attacks: the break_', 'pieces fall away as physics debris, stay_ pieces',
                         'remain standing (Lost Palace bridges A/B/C).'),
    'SUPPORT_PILLAR': ('A pillar holding something up (Lost Palace bridge', 'pillars): it breaks when the object resting on',
                       'it breaks. The game checks straight up from its', 'collider: the other object\'s collider has to',
                       'touch it (within 1 game unit). Then its break_', 'pieces fall, stay_ pieces (the base) remain.'),
    'FALLING_SIGN': ('Attacks don\'t break it: the game drops and breaks', 'it by itself (Dawn City\'s flying sign). Its',
                     'pieces crumble where they land.'),
    'EVENT_PROP': ('Not breakable: the map moves it (Dawn City rubble,', 'signs and track). Only its model and collider',
                   'are exported; how it moves is not decoded yet.'),
    'FALLING_BRIDGE': ('After its hits it falls and crumbles into its', 'pieces (Sein\'s bridges and floors).'),
    'RUBBLE': ('Like Break Scatter: after its hits the debris flies', 'off and rolls (Edgar\'s Dream rubble).'),
    'GAME': ('One of the game\'s own object types, kept as the', 'imported map had it (category / type below).',
             'Its exact behaviour isn\'t named yet; the game picks it', 'from the factory table (FORMATS.md).'),
    'JUMP_PAD': ('Not breakable. Players who touch its collider are', 'launched up by "Jump power". The game\'s own pads are',
                 'invisible: the collider is the trigger, a model is', 'only decoration.'),
}


def _tagged(tag, data):
    return tag + data


def add_objects(b, objects, placements):
    """Return a new .dat with these objects as the stage's only objects.

    objects:    list of dict(name, roots=(intact, broken, debris) .alr root indices or None,
                collision=[(v0, v1, v2, surface)] in the object's local game space, or None)
    placements: list of dict(object=index into objects, category, type, pos=(x, y, z), rot=(x, y, z),
                extra=(u8, u8) optional)
    The game original's own object tables are left in the file but no longer used."""
    buf = bytearray(b)
    buf += b'\0' * (-len(buf) % 4)

    # names
    names = b''.join(o['name'].encode('ascii', 'replace')[:31] + b'\0' for o in objects)
    buf += b'NM00'
    names_off = len(buf)
    buf += names
    buf += b'\0' * (-len(buf) % 4)

    # per-object collision chains, one per state (intact, broken, debris; each ends with its own 0xFF), and the
    # objects' own effect blocks (EF00 tables carried over from an imported map)
    col_off, fx_off = [], []
    for o in objects:
        cols = list(o.get('collisions') or [o.get('collision'), None, None]) + [None, None, None]
        offs = []
        for tris in cols[:3]:
            if tris:
                block, _ = build_block(tris, grid=OBJECT_GRID)
                offs.append(len(buf))
                buf += block
                buf += b'\0' * (-len(buf) % 4)
            else:
                offs.append(NONE)
        col_off.append(offs)
        fxs = list(o.get('effects') or []) + [None, None, None]
        offs = []
        for raw in fxs[:3]:
            if raw:
                offs.append(len(buf))
                buf += raw
                buf += b'\0' * (-len(buf) % 4)
            else:
                offs.append(NONE)
        fx_off.append(offs)
    # the objects' own animations (OA blocks: u32 count, u32 size, keys), carried over from an imported map
    anim_off = []
    for o in objects:
        offs = []
        for raw in (list(o.get('anims') or []) + [None, None, None])[:3]:
            if raw:
                offs.append(len(buf))
                buf += raw
                buf += b'\0' * (-len(buf) % 4)
            else:
                offs.append(NONE)
        anim_off.append(offs)

    # object table
    buf += b'OB00'
    ob_off = len(buf)
    for i, o in enumerate(objects):
        roots = [NONE if r is None else r for r in (list(o['roots']) + [None, None, None])[:3]]
        offs = anim_off[i] + col_off[i] + fx_off[i]          # animations, collisions, effects (per state)
        tail = (0, NONE) if i == 0 else (NONE, NONE)
        buf += struct.pack('<3I9I2I', *roots, *offs, *tail)

    # object sounds: one entry for every object (see the notes at the top); imported ones keep the map's own
    buf += b'OS00'
    snd_off = len(buf)
    for o in objects:
        snd = list(o.get('sounds') or [])[:8]
        snd += [0xFFFF] * (8 - len(snd))
        buf += struct.pack('<8H', *[int(x) & 0xFFFF for x in snd])

    # one placement list per slot the placements name (slot 0: the default list, used by a variant without its own
    # list 1 + variant); a placement without slots is in list 0
    lists = {}
    for p in placements:
        for slot in p.get('slots') or (0,):
            lists.setdefault(int(slot), []).append(p)
    ps = {}
    for slot in sorted(lists):
        buf += b'PS0/' if slot == 0 else b'PS0%d' % (slot - 1)     # the game's tags: PS0/, PS01 (slot 2), PS02
        ps[slot] = len(buf)
        for p in lists[slot]:
            e6, e7 = p.get('extra', (0, 0))
            buf += struct.pack('<i4BI3f3f', p['object'], p['category'], p['type'], e6, e7, 0, *p['pos'], *p['rot'])

    struct.pack_into('<I', buf, dat.H_NAMES, names_off)
    struct.pack_into('<I', buf, dat.H_OBJECT_COUNT, len(objects))
    struct.pack_into('<I', buf, dat.H_OBJECTS, ob_off)
    struct.pack_into('<I', buf, dat.H_OBJECT_SOUNDS, snd_off)
    for slot in range(11):
        struct.pack_into('<I', buf, dat.H_LAYOUT_SLOTS + 4 * slot, ps.get(slot, NONE))
        struct.pack_into('<I', buf, dat.H_LAYOUT_COUNTS + 4 * slot, len(lists[slot]) if slot in ps else NONE)
    struct.pack_into('<I', buf, dat.H_FILE_SIZE, len(buf))
    return bytes(buf)


def read_objects(b):
    """Names, object table entries and placements as the game would see them (for checks)."""
    h = dat.header(b)
    names, o = [], h['names']
    for _ in range(h['object_count']):
        e = b.index(b'\0', o)
        names.append(b[o:e].decode('ascii', 'replace'))
        o = e + 1
    table = [struct.unpack_from('<14I', b, h['objects'] + i * 0x38) for i in range(h['object_count'])]
    places = []
    for slot, off, cnt in dat.placement_tables(b):
        for i in range(cnt):
            oid, cat, typ, e6, e7, _pad, *rest = struct.unpack_from('<i4BI3f3f', b, off + i * 0x24)
            places.append(dict(slot=slot, object=oid, category=cat, type=typ, extra=(e6, e7),
                               pos=tuple(rest[:3]), rot=tuple(rest[3:]), offset=off + i * 0x24))
    return names, table, places
