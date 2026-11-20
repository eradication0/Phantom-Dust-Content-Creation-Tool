"""Reader for com/stNN/comdata*.cad: most likely the AI navigation data (not confirmed in game).

Small format (only com/st01/comdata.cad): u32 n_verts, u32 n_quads_a, u32 n_quads_b,
n_verts x f32 xyz, then (n_quads_a + n_quads_b) x u32[4] vertex indices.

Battle maps use com/stNN/comdataN.cad instead: always 674,312 bytes, starting with u32 count and
then xyz points; the rest is not decoded. read() rejects those.
"""
import struct

BATTLE_SIZE = 674312


def read(b):
    if len(b) == BATTLE_SIZE:
        raise ValueError('map comdataN.cad (674,312 bytes): this format is not decoded yet')
    nv, na, nb = struct.unpack_from('<3I', b, 0)
    expected = 12 + nv * 12 + (na + nb) * 16
    if expected != len(b):
        raise ValueError('size %d does not match counts (expected %d)' % (len(b), expected))
    o = 12
    verts = [struct.unpack_from('<3f', b, o + i * 12) for i in range(nv)]
    o += nv * 12
    quads = [struct.unpack_from('<4I', b, o + i * 16) for i in range(na + nb)]
    return dict(verts=verts, quads_a=quads[:na], quads_b=quads[na:])
