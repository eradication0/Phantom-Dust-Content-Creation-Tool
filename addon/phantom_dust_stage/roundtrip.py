"""Keep what was not edited: an imported game original exported back to its own slot is written byte for byte.

The exporter rebuilds every part it writes from the scene (collision appended as a new block, spawns rewritten,
the .alr models rebuilt, objects and effects re-added). That is right for edited parts, but an untouched part comes
back slightly different (float rounding through Blender, the game's triangle strips written as lists, chunking,
object names) and some data the scene does not hold is lost (the second object layout, shadow volumes, the
game's own sky model...).

So the import records, per part, a digest of exactly what the exporter would read from the scene for it (the
output of the export's own gather functions), with the SHA-1 of the game files it came from. On export, a part
whose digest is unchanged, exported over the same game files, is not rebuilt: the game file's own bytes stay.
Parts (exporter.scene_digests / model_digests):
  spawns           Spawn Points (gather_spawns)               -> moved CP00 entries written in place, or kept
  collision        Colliders and Visuals used as collision    -> new block appended, or the original kept
  effects          Effects collections (effects_export.gather)-> moved EF00 entries rewritten, or kept
  visual_0/1/2     stage (+ shadow casters), background, sky  -> that .alr root rebuilt, or kept
  visual_objects   one digest per stage / background object   -> in a rebuilt root, unedited game meshes kept
  caster_objects   one digest per shadow caster               -> unedited game shadow meshes kept
  objects          Objects collections (objects_export.gather)-> kept, or:
  objects_shape,   the same without placements; which of the  -> only placements moved: written in place
  placement_ids    file's placements the scene holds
  object_types     one digest per object type                 -> edited types added as new types, others kept
The record lives in the scene (custom property pd_roundtrip), so it survives saving the .blend. It also names the
files imported: a scene imported from an earlier export of the slot (not the game original) is exported on top
of that file (source()), so taking an edit back gives the earlier bytes back.
"""
import hashlib
import json
import math
import re
import struct

KEY = 'pd_roundtrip'

# Optional fallback, off by default: export option "Preserve unedited parts from the original file" (and the import
# option that records what the import made). With it off, recorded() and source() find nothing, so every part of
# both files is built from the scene; nothing here is consulted.
ENABLED = False
_ADDR = re.compile(r' at 0x[0-9A-Fa-f]+')


def _feed(h, x):
    """Hash a nested value of plain Python data (what the gather functions return) into h."""
    if x is None or isinstance(x, bool):
        h.update(b'N' if x is None else (b'T' if x else b'F'))
    elif isinstance(x, int):
        h.update(b'i%d;' % x)
    elif isinstance(x, float):
        # to 1e-4 (game units, normals, UVs): absorbs most float noise of matrix products (a value that rounds
        # the other way only makes the part count as edited); edits smaller than that do not count
        h.update(b'f' + struct.pack('<d', round(x, 4) + 0.0) if math.isfinite(x) else b'f' + repr(x).encode())
    elif isinstance(x, str):
        h.update(b's%d:' % len(x) + x.encode('utf-8', 'surrogatepass'))
    elif isinstance(x, (bytes, bytearray, memoryview)):
        h.update(b'b%d:' % len(x) + bytes(x))
    elif isinstance(x, dict):
        h.update(b'{%d' % len(x))
        for k in sorted(x, key=repr):
            _feed(h, k)
            _feed(h, x[k])
        h.update(b'}')
    elif isinstance(x, (list, tuple)):
        h.update(b'[%d' % len(x))
        for v in x:
            _feed(h, v)
        h.update(b']')
    elif isinstance(x, (set, frozenset)):
        _feed(h, sorted(x, key=repr))
    elif hasattr(x, '__len__') and hasattr(x, '__getitem__'):      # mathutils vectors/matrices, numpy arrays
        _feed(h, [x[i] for i in range(len(x))])
    elif hasattr(x, 'tolist'):                                    # numpy scalars
        _feed(h, x.tolist())
    else:                                                         # a Blender datablock: its kind and name
        name = getattr(x, 'name_full', None) or getattr(x, 'name', None)
        h.update(b'o' + (type(x).__name__ + ':' + (name if name is not None else _ADDR.sub('', repr(x)))).encode())


def digest(*values):
    h = hashlib.sha1()
    for v in values:
        _feed(h, v)
    return h.hexdigest()


def file_sha1(path):
    with open(path, 'rb') as f:
        return hashlib.sha1(f.read()).hexdigest()


def record(scene, stage, dat_path, alr_path, digests):
    """Remember what the import made (call after the scene is complete)."""
    import os
    has_alr = bool(alr_path) and os.path.isfile(alr_path)
    scene[KEY] = json.dumps(dict(stage=stage, dat=file_sha1(dat_path),
                                 alr=file_sha1(alr_path) if has_alr else None,
                                 dat_path=os.path.abspath(dat_path),
                                 alr_path=os.path.abspath(alr_path) if has_alr else None,
                                 digests=digests))


def source(scene, stage, kind, base_path):
    """The file (kind 'dat' or 'alr') this scene was imported from, when that is not `base_path` (the game
    original of the slot) but an earlier export of the same slot that still holds the bytes it was imported
    from, else None. Exporting such a scene builds on that file: what was not edited since keeps its bytes, and
    an edit that is taken back writes the original values back into the same entries."""
    import os
    if not ENABLED:
        return None
    try:
        r = json.loads(scene.get(KEY, ''))
    except (TypeError, ValueError):
        return None
    p = r.get(kind + '_path')
    if r.get('stage') != stage or not p or not os.path.isfile(p) or not r.get(kind):
        return None
    if base_path and os.path.isfile(base_path) and os.path.normcase(os.path.abspath(p)) ==             os.path.normcase(os.path.abspath(base_path)):
        return None
    if base_path and os.path.isfile(base_path) and file_sha1(base_path) == r.get(kind):
        return None
    return p if file_sha1(p) == r.get(kind) else None


def recorded(scene, stage, dat_path=None, alr_path=None):
    """The import's digests if this scene was imported from these very game files of `stage`, else {}."""
    import os
    if not ENABLED:
        return {}
    try:
        r = json.loads(scene.get(KEY, ''))
    except (TypeError, ValueError):
        return {}
    if r.get('stage') != stage:
        return {}
    if dat_path is not None and (not os.path.isfile(dat_path) or file_sha1(dat_path) != r.get('dat')):
        return {}
    if alr_path is not None and (not os.path.isfile(alr_path) or file_sha1(alr_path) != r.get('alr')):
        return {}
    return r.get('digests') or {}


def unchanged(scene, stage, part, now, dat_path=None, alr_path=None):
    """True when `part`'s digest `now` equals the one recorded at import from the same game files."""
    was = recorded(scene, stage, dat_path, alr_path).get(part)
    return was is not None and was == now
