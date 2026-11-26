"""The stage .dat as a container of sections: drop the sections nothing points at any more.

The export's section writers (collision, effects, objects, the light script, the stage model list) put each new
section at the end of the file and point the header at it. The game's own section stays where it was, unused. This
module removes such dead sections, so a rebuilt file holds each section once.

Container (clean-room notes on the stage layout, docs "dat_stage"): a 0x13C-byte header of u32 words, then
sections. A section runs from its offset to the next distinct offset any reader uses. The offsets are the header
words below and, inside the object definitions (OB00, 0x38 bytes each), the nine words at +0x0C..+0x2F (animation,
collision and effect lists per state). The tags NM00, OC0x, OE0x, OA0x, OB00 and the placement tags PS0x sit just
before the data their offset points at; EF00, SP00, MD00 and CP00 start their own data.
"""
import re
import struct

NONE = 0xFFFFFFFF
HEADER = 0x13C
H_FILE_SIZE = 0x138
H_OBJECTS = 0x90
H_OBJECT_COUNT = 0x60
# offset words: placement lists (0x04..0x2C), names (0x5C), then 0x64..0x134
OFFSET_WORDS = [0x04 + 4 * i for i in range(11)] + [0x5C] + list(range(0x64, 0x138, 4))
# 0x64..0x84 point at the OC / OE / OA sections, but no reader goes through them (the object definitions do):
# they do not keep a section alive, and are cleared when theirs is removed
TAG_WORDS = set(range(0x64, 0x88, 4))
_LEAD_TAG = re.compile(rb'(?:NM|OC|OE|OA|OB|OS|PS)0[0-9/]')


def _u32(b, o):
    return struct.unpack_from('<I', b, o)[0]


def _object_refs(b):
    """(position, value) of every offset word inside the current object definitions."""
    ob, n = _u32(b, H_OBJECTS), _u32(b, H_OBJECT_COUNT)
    out = []
    if ob == NONE or ob + n * 0x38 > len(b):
        return out
    for i in range(n):
        for k in range(3, 12):
            pos = ob + i * 0x38 + 4 * k
            out.append((pos, _u32(b, pos)))
    return out


def refs(b, with_tags=True):
    """(position, value) of every offset word in use (value not -1)."""
    out = [(w, _u32(b, w)) for w in OFFSET_WORDS if with_tags or w not in TAG_WORDS]
    if _u32(b, H_OBJECT_COUNT) == 0:
        # no object definitions: the 0x90 word points at nothing (st32 has it at its collision's old offset, which
        # kept the game's collision in a rebuilt file next to the new one); it is still moved by _delete
        out = [(w, v) for w, v in out if w != H_OBJECTS]
    out += _object_refs(b)
    return [(p, v) for p, v in out if v != NONE and HEADER <= v <= len(b)]


class Spans(list):
    """Sections of a file as (start, end), and where its object definitions start (`objects`)."""
    objects = NONE


def spans(b):
    """Sections of a file as (start, end): from each distinct offset to the next one (or the file's end)."""
    starts = sorted({v for _p, v in refs(b) if v < len(b)})
    out = Spans((s, starts[k + 1] if k + 1 < len(starts) else len(b)) for k, s in enumerate(starts))
    out.objects = _u32(b, H_OBJECTS)
    return out


def _lead(b, x):
    return 4 if HEADER + 4 <= x <= len(b) and _LEAD_TAG.fullmatch(bytes(b[x - 4:x])) else 0


def _delete(b, c0, c1):
    """Remove bytes c0..c1 and move every offset word that points past them."""
    n = c1 - c0
    words = [(w, _u32(b, w)) for w in OFFSET_WORDS] + _object_refs(b)
    for p, v in words:
        if v == NONE:
            continue
        if v >= c1:
            struct.pack_into('<I', b, p, v - n)
        elif v > c0 or (v == c0 and p in TAG_WORDS):
            struct.pack_into('<I', b, p, NONE)          # only the unread tag words can point into a removed span
    b[c0:c1] = b''


def compact(new, old_spans):
    """`new` (bytes of an edited file whose sections were written at its end) without the sections of the file it
    was made from (`old_spans`, from spans() of that file) that no offset uses any more. Returns (bytes, bytes
    removed)."""
    b = bytearray(new)
    # the OC / OE / OA tag words keep their (often empty) sections while the file's own object definitions are in
    # use; once the definitions were written new, those sections go with them
    objects_new = getattr(old_spans, 'objects', NONE) != NONE and _u32(b, H_OBJECTS) != old_spans.objects
    live = {v for _p, v in refs(b, with_tags=not objects_new)}
    cuts = []                                           # worked out on the unmodified bytes, merged
    for s, e in sorted(old_spans):
        if any(s <= v < e for v in live):
            continue
        # a section's leading tag goes with it; the next section's tag (the span's last 4 bytes) stays
        c0, c1 = s - _lead(b, s), (e - _lead(b, e) if e < len(b) else e)
        if c1 <= c0:
            continue
        if cuts and c0 <= cuts[-1][1]:
            cuts[-1][1] = max(cuts[-1][1], c1)
        else:
            cuts.append([c0, c1])
    removed = 0
    for c0, c1 in reversed(cuts):                       # from the end: earlier cuts keep their positions
        _delete(b, c0, c1)
        removed += c1 - c0
    if len(b) >= HEADER:
        struct.pack_into('<I', b, H_FILE_SIZE, len(b))
    return bytes(b), removed
