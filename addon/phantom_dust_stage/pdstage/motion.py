"""Joint animations: runs of ALR animation chunks (id 5), as the stage file holds them in two places.

- Object animations (OA): object definition words +0x0C..+0x17, one run per state; played when the object is in
  that state (Storm Refinery's ... the pieces of a broken container fall). Each track moves one joint of that
  state's model.
- Animation blobs: header word 0xF4 (u32 count, then u32 length + bytes per blob); an MD00 pair names a blob for
  its model (`Stage_ResolveMd00Models` 0xBE3D0 hands the model the blob's first chunk).

Track (chunk payload, 0x18-byte header): f32 length (frames), u16 joint, u16 rotation key size, u32 translation
keys, u32 rotation keys, u32 scale keys, u16 channel codes (low byte rotation axes, high byte translation axes; 0 =
X Y Z), u16 translation key size (0 = 16). Keys: translation and scale f32 frame + 3 f32; rotation u16 frame + 3 s16
Euler angles. Every track in every stage file uses codes 0, rotation keys of 8 bytes and translation keys of 16
(survey of the 21 stage files, Xbox and PC identical).

How the game samples a track (Xbox `sub_14E760`, the only ALR chunk-5 sampler besides 0x14DE40, both convert
rotation keys with 0x1540B0): for each channel it finds the two keys around the time (wrapping by the length),
interpolates translation and scale linearly, and turns both rotation keys into quaternions (0x1540B0: half angles
from a sine table indexed by (units >> 1) & 0x7FFF, so one unit is pi / 16384 radians; rotation X, then Y, then Z)
and slerps them (0x153E20). A translation key is the joint's whole local position (frame 0 = the joint's rest
position), not an offset; axes a track does not key keep the joint's rest value.

Not quaternions: the rotation words are Euler angles. (An earlier reader of this add-on took them for quaternion
x, y, z; the numbers survived a round trip only because the writer copied them back unchanged.)
"""
import math
import struct

# quaternion (w, x, y, z) of Rz Ry Rx, slerp, 4x4 product, matrix of (q, t, s): the character animation's own
from .character import _q_from_euler as euler_quat, _slerp as slerp, mul, quat_matrix  # noqa: F401

ANIMATION = 5
END = struct.pack('<II', 0, 8)
UNIT = math.pi / 16384.0          # one rotation unit in radians


def read_run(b, off, end=None):
    """Tracks of the run at `off` (until a chunk that is not an animation chunk): list of dict(joint, length,
    T=[(frame, x, y, z)], R=[(frame, rx, ry, rz) radians], S=[(frame, x, y, z)])."""
    end = len(b) if end is None else end
    out, j = [], off
    while j + 8 <= end:
        cid, size = struct.unpack_from('<Ii', b, j)
        if cid != ANIMATION or size < 8:
            break
        p = j + 8
        length, joint, rks, nt, nr, ns, codes, tks = struct.unpack_from('<fHHIIIHH', b, p)
        tks = tks or 16
        if codes != 0 or rks != 8 or tks != 16:
            raise ValueError('track at %#x: channel codes %#x, key sizes %d/%d (not in any stage file)'
                             % (j, codes, tks, rks))
        q = p + 0x18
        T = [struct.unpack_from('<4f', b, q + 16 * k) for k in range(nt)]
        q += 16 * nt
        R = []
        for k in range(nr):
            f, x, y, z = struct.unpack_from('<Hhhh', b, q + 8 * k)
            R.append((float(f), x * UNIT, y * UNIT, z * UNIT))
        q = p + 0x18 + ((16 * nt + 8 * nr + 3) & ~3)
        S = [struct.unpack_from('<4f', b, q + 16 * k) for k in range(ns)]
        out.append(dict(joint=joint, length=length, T=T, R=R, S=S))
        j += size
    return out


def _angle_units(a):
    u = int(round(a / UNIT))
    return ((u + 32768) % 65536) - 32768


def write_run(tracks):
    """Bytes of a run (end chunk {0, 8} included) from tracks as read_run returns them."""
    out = bytearray()
    for t in tracks:
        T, R, S = list(t['T']), list(t['R']), list(t.get('S') or [])
        frames = [k[0] for k in T] + [k[0] for k in R] + [k[0] for k in S]
        length = float(t.get('length', max(frames + [0.0])))
        body = b''.join(struct.pack('<4f', *k) for k in T)
        body += b''.join(struct.pack('<H3h', int(round(k[0])), *(_angle_units(a) for a in k[1:4])) for k in R)
        body += b'\0' * (-len(body) % 4)
        body += b''.join(struct.pack('<4f', *k) for k in S)
        out += struct.pack('<IIfHHIIIHH', ANIMATION, 8 + 0x18 + len(body), length, t['joint'], 8, len(T), len(R),
                           len(S), 0, 16) + body
    return bytes(out + END)


# ---------------------------------------------------------------- sampling (as the game does)

def _bracket(keys, time):
    if time <= keys[0][0] or len(keys) == 1:
        return keys[0], keys[0], 0.0
    for k in range(1, len(keys)):
        if time < keys[k][0]:
            a, b = keys[k - 1], keys[k]
            return a, b, (time - a[0]) / ((b[0] - a[0]) or 1.0)
    return keys[-1], keys[-1], 0.0


def sample(track, time):
    """(translation or None, quaternion (w, x, y, z) or None, scale or None) of a track at `time` (frames)."""
    out = []
    for name in ('T', 'S'):
        keys = track[name]
        if not keys:
            out.append(None)
            continue
        a, b, t = _bracket(keys, time)
        out.append(tuple(a[i] + (b[i] - a[i]) * t for i in (1, 2, 3)))
    rot = None
    if track['R']:
        a, b, t = _bracket(track['R'], time)
        rot = slerp(euler_quat(*a[1:4]), euler_quat(*b[1:4]), t)
    return out[0], rot, out[1]


# ---------------------------------------------------------------- 4x4 matrices (column vectors, nested lists)

def inverse_rigid(m):
    """Inverse of a rotation + translation (+ uniform-free scale ignored: the stage joints have scale 1)."""
    r = [[m[c][r] for c in range(3)] for r in range(3)]
    t = [-sum(r[i][k] * m[k][3] for k in range(3)) for i in range(3)]
    return [r[0] + [t[0]], r[1] + [t[1]], r[2] + [t[2]], [0.0, 0.0, 0.0, 1.0]]


def matrix_euler(m):
    """Game Euler angles (rx, ry, rz) of the rotation part of m (m = Rz * Ry * Rx)."""
    cy = math.hypot(m[0][0], m[1][0])
    ry = math.atan2(-m[2][0], cy)
    if cy > 1e-6:
        return math.atan2(m[2][1], m[2][2]), ry, math.atan2(m[1][0], m[0][0])
    return math.atan2(-m[1][2], m[1][1]), ry, 0.0


def matrix_euler_near(m, prev):
    """matrix_euler, but at the gimbal lock (Y near +-90 degrees, where only X - Z or X + Z is defined) the split
    nearest the previous key's angles `prev`: written again and again, the split no longer wanders (each cycle moved
    it a few units)."""
    rx, ry, rz = matrix_euler(m)
    if prev is None or math.hypot(m[0][0], m[1][0]) > 1e-2:
        return rx, ry, rz
    best, err = (rx, ry, rz), None
    for cand in ((rx - rz + prev[2], ry, prev[2]), (rx + rz - prev[2], ry, prev[2])):
        q = quat_matrix(euler_quat(*cand))
        e = max(abs(q[i][k] - m[i][k]) for i in range(3) for k in range(3))
        if e < 5e-4 and (err is None or e < err):
            best, err = cand, e
    return best


def joint_local(node, track=None, time=0.0):
    """A joint's local matrix: its rest values (node dict t, rot, scale), the track's channels over them."""
    t, q, s = (tuple(node['t']), euler_quat(*node['rot']), tuple(node['scale']))
    if track is not None:
        tt, tq, ts = sample(track, time)
        t, q, s = tt or t, tq or q, ts or s
    return quat_matrix(q, t, s)


def frames_of(track):
    """Every key frame of a track (all channels), sorted."""
    return sorted({k[0] for ch in ('T', 'R', 'S') for k in track[ch]})
