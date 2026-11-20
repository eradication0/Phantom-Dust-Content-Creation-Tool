"""Build a stNN.dat collision block from triangles.

Output is the byte block that header 0x94 points at: kind-3 triangle chunks followed by one kind-8
vertex list (the order every map uses), ended by an 0xFF byte. Use append_collision() to put it in a
.dat; the game builds its spatial grid from these records at load time.

Triangles are (v0, v1, v2, surface_type) with v = (x, y, z), y up. Winding sets the stored normal:
normal = normalize((v1 - v0) x (v2 - v0)).
"""
import math
import random
import struct

from . import dat

MAX_VERTS = 0xFFFF            # u16 indices
CHUNK_CELL = 60.0             # spatial grouping size (game units); map chunks are similar in size
CHUNK_MAX_TRIS = 8            # map chunks hold 1-11 triangles
VLIST_TYPE = 0x23             # type byte of the vertex-list record in most maps (st04 uses 0x21)


# ---------------------------------------------------------------- smallest enclosing sphere

def _sphere_from(ps):
    if not ps:
        return (0.0, 0.0, 0.0), -1.0
    if len(ps) == 1:
        return ps[0], 0.0
    if len(ps) == 2:
        c = tuple((ps[0][i] + ps[1][i]) / 2 for i in range(3))
        return c, math.dist(c, ps[0])
    if len(ps) == 3:
        a, b, c = ps
        ab = [b[i] - a[i] for i in range(3)]
        ac = [c[i] - a[i] for i in range(3)]
        n = _cross(ab, ac)
        d = 2 * _dot(n, n)
        if d < 1e-12:                                   # collinear: widest pair
            return max((_sphere_from([p, q]) for p, q in ((a, b), (a, c), (b, c))), key=lambda s: s[1])
        t = _cross(n, ab)
        u = _cross(ac, n)
        off = [(_dot(ab, ab) * u[i] + _dot(ac, ac) * t[i]) / d for i in range(3)]
        ctr = tuple(a[i] + off[i] for i in range(3))
        return ctr, math.dist(ctr, a)
    a, b, c, e = ps                                      # 4 points: circumsphere
    m = [[b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)], [e[i] - a[i] for i in range(3)]]
    rhs = [_dot(r, r) / 2 for r in m]
    det = _det3(m)
    if abs(det) < 1e-9:
        return max((_sphere_from([p, q, r]) for p, q, r in ((a, b, c), (a, b, e), (a, c, e), (b, c, e))), key=lambda s: s[1])
    sol = []
    for k in range(3):
        mk = [row[:] for row in m]
        for r in range(3):
            mk[r][k] = rhs[r]
        sol.append(_det3(mk) / det)
    ctr = tuple(a[i] + sol[i] for i in range(3))
    return ctr, math.dist(ctr, a)


def enclosing_sphere(points):
    """Smallest sphere containing all points (Welzl, iterative move-to-front)."""
    pts = list(dict.fromkeys(points))
    random.Random(0).shuffle(pts)
    eps = 1e-4

    def inside(s, p):
        return math.dist(s[0], p) <= s[1] + eps

    def mtf(n, boundary):
        s = _sphere_from(boundary)
        if len(boundary) == 4:
            return s
        for i in range(n):
            if not inside(s, pts[i]):
                s = mtf(i, boundary + [pts[i]])
        return s
    return mtf(len(pts), [])


def _cross(u, v):
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


def _dot(u, v):
    return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]


def _det3(m):
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


# ---------------------------------------------------------------- records

def chunk_record(surface_type, verts, tris):
    """One kind-3 record. verts: the full vertex list; tris: list of (a, b, c) indices."""
    used = [verts[i] for t in tris for i in t]
    mn = tuple(min(p[k] for p in used) for k in range(3))
    mx = tuple(max(p[k] for p in used) for k in range(3))
    centre, _ = enclosing_sphere(used)
    radius = max(math.dist(centre, p) for p in used)
    body = bytearray()
    body += struct.pack('<3f', *centre) + struct.pack('<f', radius)
    body += struct.pack('<3f', *mn) + struct.pack('<3f', *mx)
    body += struct.pack('<HHI', len(tris), 0, 0)          # count, pad, vertex list 0
    for a, b, c in tris:
        A, B, C = verts[a], verts[b], verts[c]
        n = _cross([B[i] - A[i] for i in range(3)], [C[i] - A[i] for i in range(3)])
        l = math.sqrt(_dot(n, n))
        body += struct.pack('<4H', a, b, c, 0) + struct.pack('<3f', *(x / l for x in n))
    return struct.pack('<4B2I', surface_type, dat.KIND_MESH, 0x03, 0xFF, len(body) - 0x00, 0) + body


def vertex_record(verts, vlist_type=VLIST_TYPE):
    body = b''.join(struct.pack('<3f', *v) for v in verts)
    return struct.pack('<4B2I', vlist_type, dat.KIND_VERTS, 0x03, 0xFF, len(body), 0) + body


def build_block(triangles, cell=CHUNK_CELL, max_tris=CHUNK_MAX_TRIS, vlist_type=VLIST_TYPE):
    """triangles: iterable of (v0, v1, v2, surface_type). Returns (block_bytes, stats)."""
    index, verts, groups, skipped = {}, [], {}, 0

    def vid(v):
        key = tuple(round(x, 4) for x in v)
        if key not in index:
            index[key] = len(verts)
            verts.append(tuple(float(x) for x in v))
        return index[key]

    for v0, v1, v2, st in triangles:
        n = _cross([v1[i] - v0[i] for i in range(3)], [v2[i] - v0[i] for i in range(3)])
        if _dot(n, n) < 1e-10:
            skipped += 1                                    # zero-area triangle
            continue
        t = (vid(v0), vid(v1), vid(v2))
        if len({*t}) < 3:
            skipped += 1
            continue
        c = [(v0[i] + v1[i] + v2[i]) / 3 for i in range(3)]
        key = (st,) + tuple(math.floor(c[i] / cell) for i in range(3))
        groups.setdefault(key, []).append(t)
    if len(verts) > MAX_VERTS:
        raise ValueError('%d vertices; one vertex list holds at most %d' % (len(verts), MAX_VERTS))

    out = bytearray()
    nchunks = 0
    for key in sorted(groups):
        ts = groups[key]
        for i in range(0, len(ts), max_tris):
            out += chunk_record(key[0], verts, ts[i:i + max_tris])
            nchunks += 1
    out += vertex_record(verts, vlist_type)
    out += b'\xFF'
    return bytes(out), dict(triangles=sum(len(g) for g in groups.values()), chunks=nchunks,
                            vertices=len(verts), skipped=skipped, bytes=len(out))


def append_collision(dat_bytes, block):
    """Return a new .dat with the block appended (4-byte aligned) and header 0x94 / 0x138 updated."""
    b = bytearray(dat_bytes)
    b += b'\0' * (-len(b) % 4)
    off = len(b)
    b += block
    struct.pack_into('<I', b, dat.H_COLLISION, off)
    struct.pack_into('<I', b, dat.H_FILE_SIZE, len(b))
    return bytes(b)
