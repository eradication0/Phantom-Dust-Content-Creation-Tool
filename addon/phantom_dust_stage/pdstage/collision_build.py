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
CHUNK_CELL = 60.0             # grouping of triangles added by patch() (the fallback's in-place writer)
CHUNK_MAX_TRIS = 8            # (patch() only)
# The game's own chunking, measured on every retail stage file (FIELD_MAP.md, "Collision chunks"):
# - the stage list (header 0x94): the triangles' bounding box cut into 16 x 16 x 16 equal cells; a chunk holds the
#   triangles of one surface kind whose centroid lies in one cell (st32: all 256 chunks; st04 896 cells for 897
#   chunks, st03 1052 / 1039, st07 808 / 800), in x, then y, then z order; up to 205 triangles in one chunk;
# - an object's list (object definition +0x18): one chunk per surface kind (612 lists, 674 chunks, never two chunks
#   of one kind; up to 308 triangles).
# Each chunk is one broad-phase object of the character query (its sphere and box); the triangle grid the game builds
# at load does not depend on the chunking. One triangle per chunk (the old 60-unit cells, at most 8 triangles) made
# the stage lists up to 3x as many chunks: st32's .dat grew from 41 KB to 110 KB.
STAGE_GRID = 16
OBJECT_GRID = 1
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


def build_block(triangles, grid=STAGE_GRID, vlist_type=VLIST_TYPE):
    """triangles: iterable of (v0, v1, v2, surface_type). Chunks as the game's files have them: the triangles of one
    surface kind whose centroid lies in one of grid x grid x grid equal cells of their bounding box (STAGE_GRID for a
    stage list, OBJECT_GRID for an object's list). Returns (block_bytes, stats)."""
    index, verts, groups, skipped = {}, [], {}, 0
    kept = []

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
        kept.append((t, st))
    if kept:
        lo = [min(verts[i][k] for t, _ in kept for i in t) for k in range(3)]
        hi = [max(verts[i][k] for t, _ in kept for i in t) for k in range(3)]
        size = [(hi[k] - lo[k]) / grid for k in range(3)]
        for t, st in kept:
            c = [sum(verts[i][k] for i in t) / 3 for k in range(3)]
            cell = tuple(min(grid - 1, int((c[k] - lo[k]) / size[k])) if size[k] > 0 else 0 for k in range(3))
            groups.setdefault(cell + (st,), []).append(t)
    if len(verts) > MAX_VERTS:
        raise ValueError('%d vertices; one vertex list holds at most %d' % (len(verts), MAX_VERTS))

    out = bytearray()
    nchunks = 0
    for key in sorted(groups):                          # x, then y, then z, then the surface kind
        out += chunk_record(key[3], verts, groups[key])
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


# ---------------------------------------------------------------- edits written into the file's own records

PATCH_TOLERANCE = 2e-3        # game units: float32 rounding through Blender leaves less; an edit moves more


def _close(p, q, tol):
    return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol and abs(p[2] - q[2]) <= tol


def _home(b, recs, start):
    """An earlier copy of this collision block in the file (the game's own block, left in place when an earlier
    export appended an edited copy): (offset, records, vertices) with the same records in the same order, or
    None. The game's maps never hold two blocks, so only an export of this kind leaves one."""
    for r in recs[:-1]:
        raw = bytes(b[r.offset:r.offset + 0x0C + r.size])
        at = bytes(b).find(raw, 0, start)
        if at < 0:
            continue
        home = at - (r.offset - start)
        if home < 0:
            return None
        try:
            hrecs, hvl = dat.collision(b, home)
        except (struct.error, IndexError):
            return None
        if len(hvl) != 1 or len(hrecs) > len(recs) or \
                any((h.kind, h.type) != (n.kind, n.type) for h, n in zip(hrecs[:-1], recs[:-1])):
            return None
        return home, hrecs, hvl[0]
    return None


def _f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def patch(dat_bytes, triangles, tol=PATCH_TOLERANCE, scale=None):
    """Write edited collision into the .dat's own records instead of a rebuilt block.

    triangles: (v0, v1, v2, surface_type) as build_block takes them (the whole collision of the scene). Each is
    matched with the file's triangle it came from: per surface type in file order when the counts agree (what an
    import gives back), else by position. Untouched triangles and records keep their bytes and order. A moved
    triangle keeps its place and attribute word with new corners: a vertex that only moved triangles use is moved
    in the vertex list; one shared with triangles that stay is left, and the moved ones use a vertex already at
    their position or a new one appended to the list. Its normal is recomputed only when its shape changed. A
    record with moved triangles gets its box again, its centre and radius moved along when the whole record moved
    by one offset (else computed again). Removed triangles leave their record, added ones go into new records
    before the vertex list.

    When nothing has to grow (no triangle added or removed, no new vertex), everything is written in place and the
    file keeps its size. Otherwise the block, with the same records, is appended to the file (header 0x94 and 0x138
    updated; the game's own block stays where it was, unused). Exporting again on top of such a file: values back
    within `tol` of the game's own block take its bytes, and when the result is that block again, header 0x94
    points back at it and the appended copy is cut off (so taking an edit back gives the game's file back).

    scale: the Blender units per game unit the triangles came through (an import stores each vertex as a 32-bit
    float of value * scale). Given, a moved corner is written as the file's value plus how far it moved from where
    the import put it, so moving it back gives the file's value again exactly instead of float noise.

    Returns (bytes, stats) or None when the file's collision is not in the shape this expects (one vertex list at
    the end, kinds 3 and 8 only): use build_block() then."""
    b = bytearray(dat_bytes)
    start = struct.unpack_from('<I', b, dat.H_COLLISION)[0]
    if start == dat.NONE:
        return None
    recs, vlists = dat.collision(b)
    if len(vlists) != 1 or any(r.kind not in (dat.KIND_MESH, dat.KIND_VERTS) for r in recs) \
            or any(r.kind == dat.KIND_MESH and r.vlist != 0 for r in recs) or recs[-1].kind != dat.KIND_VERTS:
        return None
    vl = vlists[0]
    old = [tuple(v) for v in vl.verts]
    base = []                                     # (record, triangle, (a, b, c), surface)
    for ri, r in enumerate(recs):
        if r.kind == dat.KIND_MESH:
            for ti, t in enumerate(r.tris):
                if max(t[:3]) >= len(old):
                    return None
                base.append((ri, ti, t[:3], r.type))
    scene = [(tuple(map(float, v0)), tuple(map(float, v1)), tuple(map(float, v2)), st)
             for v0, v1, v2, st in triangles]

    by_type_base, by_type_scene = {}, {}
    for i, x in enumerate(base):
        by_type_base.setdefault(x[3], []).append(i)
    for i, x in enumerate(scene):
        by_type_scene.setdefault(x[3], []).append(i)
    kept, moved, added = set(), {}, []           # base ids kept; base id -> scene triangle; scene ids added

    def corners(i):
        return [old[k] for k in base[i][2]]

    for st in sorted(set(by_type_base) | set(by_type_scene)):
        bi, si = by_type_base.get(st, []), by_type_scene.get(st, [])
        if len(bi) == len(si):
            for i, j in zip(bi, si):
                if all(_close(p, q, tol) for p, q in zip(corners(i), scene[j][:3])):
                    kept.add(i)
                else:
                    moved[i] = scene[j]
            continue
        cells = {}                                 # by position: the counts changed (triangles added or removed)
        for i in bi:
            c = corners(i)
            cells.setdefault(tuple(math.floor(sum(p[k] for p in c) / 3.0) for k in range(3)), []).append(i)
        free = set(bi)
        for j in si:
            s = scene[j][:3]
            cen = [math.floor(sum(p[k] for p in s) / 3.0) for k in range(3)]
            hit = next((i for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
                        for i in cells.get((cen[0] + dx, cen[1] + dy, cen[2] + dz), ())
                        if i in free and all(_close(p, q, tol) for p, q in zip(corners(i), s))), None)
            if hit is None:
                added.append(j)
            else:
                free.discard(hit)
                kept.add(hit)
    removed = set(range(len(base))) - kept - set(moved)
    if scale:
        imp = float('%.6g' % scale)                # the scale as the import used it (as typed)

        def from_file(k, p):                       # the file's value + the move since the import
            q = old[k]
            return tuple(q[a] + (p[a] - _f32(q[a] * imp) / scale) for a in range(3))
        moved = {i: tuple(from_file(k, p) for k, p in zip(base[i][2], s[:3])) + (s[3],) for i, s in moved.items()}
    stats = dict(moved=len(moved), removed=len(removed), new_vertices=0, records=0)
    home = _home(b, recs, start)
    if not moved and not added and not removed and home is None:
        stats.update(triangles=len(base), added=0, in_place=True)
        return bytes(b), stats

    # where each moved corner goes
    fixed = {k for i in kept for k in base[i][2]}
    want = {}
    for i, s in moved.items():
        for k, p in zip(base[i][2], s[:3]):
            want.setdefault(k, []).append(p)
    staying = {}                                   # position -> index, of vertices that do not move

    def key(p):
        return tuple(round(x, 2) for x in p)
    for k, p in enumerate(old):
        if k in fixed or k not in want:
            staying.setdefault(key(p), []).append(k)

    def staying_at(p):
        return next((k for k in staying.get(key(p), ()) if _close(old[k], p, tol)), None)
    final = list(old)
    for k, ps in want.items():
        if k not in fixed and all(_close(ps[0], p, tol) for p in ps) and not _close(old[k], ps[0], tol):
            final[k] = ps[0]
    extra, at = [], {}

    def vertex_for(p, k=None):
        s = staying_at(p)                          # a vertex that stays there (e.g. an edit taken back)
        if s is not None:
            return s
        if k is not None and _close(final[k], p, tol):
            return k
        kk = tuple(round(x, 3) for x in p)
        if kk not in at:
            at[kk] = len(final) + len(extra)
            extra.append(p)
        return at[kk]

    new_tris = {i: tuple(vertex_for(p, k) for k, p in zip(base[i][2], s[:3])) for i, s in moved.items()}
    groups = {}                                    # added triangles: new records, grouped as build_block does
    for j in added:
        v0, v1, v2, st = scene[j]
        n = _cross([v1[k] - v0[k] for k in range(3)], [v2[k] - v0[k] for k in range(3)])
        if _dot(n, n) < 1e-10:
            continue
        t = tuple(vertex_for(p) for p in (v0, v1, v2))
        if len(set(t)) < 3:
            continue
        c = [(v0[k] + v1[k] + v2[k]) / 3 for k in range(3)]
        groups.setdefault((st,) + tuple(math.floor(c[k] / CHUNK_CELL) for k in range(3)), []).append(t)
    # vertices moved before a corner reused one that stays (taking an edit back) are free again
    in_use = {k for t in new_tris.values() for k in t}
    for k in want:
        if final[k] is not old[k] and k not in in_use:
            final[k] = old[k]
    allv = final + extra
    if len(allv) > MAX_VERTS:
        return None
    hv = home[2].verts if home else []
    hbytes = (lambda k: bytes(b[home[2].offset + 0x0C + 12 * k:home[2].offset + 0x18 + 12 * k])) if home else None

    def vbytes(k):
        p = allv[k]
        if k < len(hv) and _close(hv[k], p, tol):  # back where the game's own block has it: its exact bytes
            return hbytes(k)
        if k < len(old) and p is old[k]:
            return bytes(b[vl.offset + 0x0C + 12 * k:vl.offset + 0x18 + 12 * k])
        return struct.pack('<3f', *p)

    by_rec = {}
    for i in set(moved) | removed:
        by_rec.setdefault(base[i][0], []).append(i)
    tri_id = {(x[0], x[1]): i for i, x in enumerate(base)}
    records = {}                                   # record index -> new record bytes
    for ri in by_rec:
        r = recs[ri]
        raw = bytes(b[r.offset + 0x3C:r.offset + 0x0C + r.size])
        body, ids, shift = bytearray(), [], []
        for ti in range(len(r.tris)):
            i = tri_id[(ri, ti)]
            if i in removed:
                continue
            ent = bytearray(raw[ti * 20:(ti + 1) * 20])
            if i in moved:
                a, bb, c = new_tris[i]
                A, B, C = allv[a], allv[bb], allv[c]
                oa, ob, oc = (old[k] for k in base[i][2])
                d = [A[k] - oa[k] for k in range(3)]
                rigid = _close([B[k] - ob[k] for k in range(3)], d, tol) and \
                    _close([C[k] - oc[k] for k in range(3)], d, tol)
                shift.append(d if rigid else None)
                struct.pack_into('<3H', ent, 0, a, bb, c)
                if not rigid:                      # turned or reshaped: a new normal
                    n = _cross([B[k] - A[k] for k in range(3)], [C[k] - A[k] for k in range(3)])
                    ln = math.sqrt(_dot(n, n))
                    if ln > 0:
                        struct.pack_into('<3f', ent, 8, *(x / ln for x in n))
            ids.append(i)
            body += ent
        if not ids:
            records[ri] = b''                       # every triangle of the record removed
            continue
        used = [allv[k] for i in ids for k in (new_tris[i] if i in new_tris else base[i][2])]
        mn = tuple(min(p[k] for p in used) for k in range(3))
        mx = tuple(max(p[k] for p in used) for k in range(3))
        if len(ids) == len(r.tris) and len(shift) == len(ids) and all(
                s is not None and _close(s, shift[0], tol) for s in shift):
            centre, radius = tuple(r.center[k] + shift[0][k] for k in range(3)), r.radius   # moved as a whole
        else:
            centre, _ = enclosing_sphere(used)
            radius = max(math.dist(centre, p) for p in used)
        head = bytearray(b[r.offset:r.offset + 0x3C])
        struct.pack_into('<I', head, 4, 0x30 + len(body))
        struct.pack_into('<3f', head, 0x0C, *centre)
        struct.pack_into('<f', head, 0x18, radius)
        struct.pack_into('<3f', head, 0x1C, *mn)
        struct.pack_into('<3f', head, 0x28, *mx)
        struct.pack_into('<H', head, 0x34, len(ids))
        rec = bytes(head + body)
        if home and ri < len(home[1]) - 1:         # back where the game's own record has it: its exact bytes
            h = home[1][ri]
            hraw = bytes(b[h.offset:h.offset + 0x0C + h.size])
            if len(hraw) == len(rec) and rec[:0x0C] == hraw[:0x0C] and all(
                    rec[o:o + 4] == hraw[o:o + 4] or (o >= 0x0C and abs(struct.unpack_from('<f', rec, o)[0]
                                                                         - struct.unpack_from('<f', hraw, o)[0]) <= tol)
                    for o in range(0, len(rec), 4)):
                rec = hraw
        records[ri] = rec

    allv = final + extra
    new_recs = [chunk_record(k[0], allv, ts[i:i + CHUNK_MAX_TRIS])
                for k in sorted(groups) for ts in (groups[k],) for i in range(0, len(ts), CHUNK_MAX_TRIS)]
    stats.update(triangles=len(kept) + len(moved) + sum(len(g) for g in groups.values()),
                 added=sum(len(g) for g in groups.values()), new_vertices=len(extra),
                 records=len(records) + len(new_recs))
    if not extra and not new_recs and home is None \
            and all(len(nb) == recs[ri].size + 0x0C for ri, nb in records.items()):
        for ri, nb in records.items():             # nothing grows: in place, the file keeps its size
            b[recs[ri].offset:recs[ri].offset + len(nb)] = nb
        for k in range(len(old)):
            if final[k] is not old[k]:
                b[vl.offset + 0x0C + 12 * k:vl.offset + 0x18 + 12 * k] = vbytes(k)
        stats['in_place'] = True
        return bytes(b), stats
    head = bytearray()
    for ri, r in enumerate(recs[:-1]):
        head += records.get(ri, bytes(b[r.offset:r.offset + 0x0C + r.size]))
    for nr in new_recs:
        head += nr
    nv = len(allv)
    if home is not None and not extra:             # vertices an earlier export appended and nothing uses now
        refs = set()
        for i, x in enumerate(base):
            if i not in removed:
                refs.update(new_tris.get(i, x[2]))
        while nv > len(hv) and nv - 1 not in refs:
            nv -= 1
    vrec = bytearray(b[vl.offset:vl.offset + 0x0C])
    struct.pack_into('<I', vrec, 4, 12 * nv)
    vrec += b''.join(vbytes(k) for k in range(nv))
    block = bytes(head + vrec + b'\xFF')
    if home is not None:
        hb = bytes(b[home[0]:home[0] + len(block)])
        if hb == block:                             # the game's own block again: point back at it
            struct.pack_into('<I', b, dat.H_COLLISION, home[0])
            if _block_end(b, start) == len(b):
                del b[start:]                       # the copy an earlier export appended at the end
            struct.pack_into('<I', b, dat.H_FILE_SIZE, len(b))
            stats['in_place'] = True
            stats['back_home'] = True
            return bytes(b), stats
    if start != dat.NONE and _block_end(b, start) == len(b) and home is not None:
        del b[start:]                               # replace the copy an earlier export appended
    off = len(b)                                    # appended as is (the game's blocks are not aligned either)
    b += block
    struct.pack_into('<I', b, dat.H_COLLISION, off)
    struct.pack_into('<I', b, dat.H_FILE_SIZE, len(b))
    stats['in_place'] = False
    return bytes(b), stats


def _block_end(b, start):
    """Offset just after the 0xFF that ends the collision chain starting at `start`."""
    o = start
    while b[o] != 0xFF:
        o += struct.unpack_from('<I', b, o + 4)[0] + 0x0C
    return o + 1
