"""Object animations (the .dat object table's [3..5] entries, one per state): read and write.

An animation is a chain of node blocks, ended by u32 0, u32 8:

    u32 5, u32 block size (bytes, header included)
    f32 last frame, u16 node, u16 8, u32 translation keys, u32 rotation keys, f32 0, u16 0, u16 16
    translation keys: f32 frame, f32 x, y, z      (the node's position in the object's own game space)
    rotation keys:    u16 frame, i16 x, y, z      (NOT a quaternion: Euler angles, pi/16384 per unit; see
                                                   pdstage/motion.py, which the export now uses)

Storm Refinery's container (one block, node 0, 269 / 220 keys) and Spiral Highway's iron roads (a block per
piece, 90 keys each) play theirs when they break. Frames are the game's frames.
"""
import math
import struct

END = struct.pack('<II', 0, 8)


def read(b, off):
    """[dict(node, last, T=[(frame, x, y, z)], R=[(frame, x, y, z, w)])] and the chain's byte length."""
    out, j = [], off
    while j + 8 <= len(b):
        tag, size = struct.unpack_from('<II', b, j)
        if tag != 5:
            return out, j + 8 - off
        last, node, _k, nt, nr, _f, _u, _s = struct.unpack_from('<fHHIIfHH', b, j + 8)
        p = j + 0x20
        T = [struct.unpack_from('<4f', b, p + 16 * k) for k in range(nt)]
        p += 16 * nt
        R = []
        for k in range(nr):
            f, x, y, z = struct.unpack_from('<Hhhh', b, p + 8 * k)
            x, y, z = x / 32767.0, y / 32767.0, z / 32767.0
            R.append((f, x, y, z, math.sqrt(max(0.0, 1.0 - x * x - y * y - z * z))))
        out.append(dict(node=node, last=last, T=T, R=R))
        j += size
    return out, j - off


def block_length(b, off):
    """Byte length of the animation chain at `off` (its end marker included)."""
    return read(b, off)[1]


def write(blocks):
    """Bytes of an animation chain from blocks as read() returns them (quaternions are normalised, w made
    positive)."""
    out = bytearray()
    for bl in blocks:
        T, R = list(bl['T']), list(bl['R'])
        last = float(bl.get('last', max([t[0] for t in T] + [r[0] for r in R] + [0])))
        body = bytearray()
        for f, x, y, z in T:
            body += struct.pack('<4f', f, x, y, z)
        for f, x, y, z, w in R:
            n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
            s = -1.0 if w < 0 else 1.0
            q = [max(-32767, min(32767, int(round(s * c / n * 32767)))) for c in (x, y, z)]
            body += struct.pack('<Hhhh', int(round(f)), *q)
        size = 0x20 + len(body)
        out += struct.pack('<IIfHHIIfHH', 5, size, last, bl['node'], 8, len(T), len(R), 0.0, 0, 16) + body
    return bytes(out + END)
