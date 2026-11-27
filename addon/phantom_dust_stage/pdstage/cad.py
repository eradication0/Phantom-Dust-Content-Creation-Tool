"""The AI navigation mesh: com/stNN/comdataV.cad (read and write).

The computer-controlled players find their way with it; it is not collision. The game opens
com\\st(stage % 10)\\comdata(variant).cad, so st02, st12 and st22 share one file (st32 uses st02's), and no file is
read on stages with stage % 10 == 1 (st01). Layout from Tinkerer_Red's format reference (section 2), checked against
every game file and PDUWP.exe:

Fixed-capacity form, always 674,312 bytes:
    0x0000  u32 vertex count (unread; highest quad index + 1), 1000 x f32 xyz vertices
    0x2EE4  u32 polygon count, 128 x 84-byte polygons:
            u32 flags, i32[8] ids, u32[4] quad vertex indices, u16[16] link indices (0xFFFF = unused)
    0x58E8  u32 link count, 512 x 44-byte links:
            f32[3] endpoint A, f32[3] endpoint B (the portal; the AI walks to its midpoint), i32 polygon A,
            i32 polygon B, u32 flags (1 = one-way: only A -> B, used for drops), f32 cost (= the distance between
            the two polygons' centres in every game file), u32 blocker polygon (with flag 2)
    0xB0EC  u32 nav point count, 30 x (f32 xyz, u32 polygon, u32 id, f32 radius)
    0xB3C0  u32 jump point count, 30 x (f32 xyz, u32 polygon): landing spots of jump pads
    0xB5A4  five 128 x 128 u32 route matrices (offset into the pool, 0xFFFFFFFF = no route); M0 normal routes,
            M2 while the AI's move mode is 2, M1 / M3 detours (tried after M0 when a polygon is closed), M4 last resort
    0x5B5A4 128 x u8 substitute polygon (where to head when the target is off the mesh; 255 = none)
    0x5B624 u32 pool bytes used, 0x5B628 300,000-byte route pool: a route i -> j is the polygons after i, ending j

Polygon flags: 1 = depends on stage objects (an object standing on it closes it; tested for ground at load),
2 = jump pad polygon, 4 / 8 are set by the game at run time (no ground / covered by an object). Polygon ids: on a
pad polygon the jump points it can reach (0-based); elsewhere 1 + nav point index and 31 + jump point index of the
points lying on it.

Polygons are quads, clockwise seen from above in game x / z. The routes, link costs, ids and per-polygon link lists
are computed here on writing; the rest is the scene's.
"""
import heapq
import math
import struct

BATTLE_SIZE = 674312
MAX_VERTS = 1000
MAX_POLYS = 128
MAX_LINKS = 512
MAX_NAV = 30
MAX_JUMP = 30
MAX_POLY_LINKS = 16
MAX_POLY_IDS = 8
POOL = 300000

F_OBJECTS = 1
F_JUMP = 2
L_ONE_WAY = 1
L_RAY = 2

O_VERTS, O_POLYS, O_LINKS, O_NAV, O_JUMP = 0x0, 0x2EE4, 0x58E8, 0xB0EC, 0xB3C0
O_MATS, O_SUB, O_USED, O_POOL = 0xB5A4, 0x5B5A4, 0x5B624, 0x5B628
NO_ROUTE = 0xFFFFFFFF


# ---------------------------------------------------------------- reading

def read(b):
    """The mesh as a model dict (game units): polys [{quad: 4 x xyz, flags, substitute}], links [{a, b, pa, pb,
    flags, blocker}], navs [{pos, poly, id, radius}], jumps [{pos, poly, pads: [polygon]}]."""
    if len(b) != BATTLE_SIZE:
        raise ValueError('not a battle navigation mesh (%d bytes, expected %d)' % (len(b), BATTLE_SIZE))
    u = lambda o: struct.unpack_from('<I', b, o)[0]
    verts = [struct.unpack_from('<3f', b, 4 + 12 * i) for i in range(MAX_VERTS)]
    n = u(O_POLYS)
    polys, raw_ids = [], []
    for i in range(n):
        o = O_POLYS + 4 + 84 * i
        q = struct.unpack_from('<4I', b, o + 0x24)
        polys.append(dict(quad=[tuple(verts[k]) for k in q], flags=u(o), substitute=b[O_SUB + i]))
        raw_ids.append(struct.unpack_from('<8i', b, o + 4))
    links = []
    for i in range(u(O_LINKS)):
        o = O_LINKS + 4 + 44 * i
        pa, pb = struct.unpack_from('<2i', b, o + 24)
        links.append(dict(a=struct.unpack_from('<3f', b, o), b=struct.unpack_from('<3f', b, o + 12), pa=pa, pb=pb,
                          flags=u(o + 32), blocker=u(o + 40)))
    navs = []
    for i in range(u(O_NAV)):
        x, y, z, poly, nid, r = struct.unpack_from('<3fIIf', b, O_NAV + 4 + 24 * i)
        navs.append(dict(pos=(x, y, z), poly=poly, id=nid, radius=r))
    jumps = []
    for i in range(u(O_JUMP)):
        x, y, z, poly = struct.unpack_from('<3fI', b, O_JUMP + 4 + 16 * i)
        jumps.append(dict(pos=(x, y, z), poly=poly, pads=[]))
    for i, p in enumerate(polys):                 # pad polygon -> the jump points it reaches
        if not p['flags'] & F_JUMP:
            continue
        ids = list(raw_ids[i])
        while len(ids) > 1 and ids[-1] <= 0:      # unused words: -1, or 0 after real entries (st05)
            ids.pop()
        for j in ids:
            if 0 <= j < len(jumps) and i not in jumps[j]['pads']:
                jumps[j]['pads'].append(i)
    return dict(polys=polys, links=links, navs=navs, jumps=jumps)


def read_compact(b):
    """com/st01/comdata.cad (never read by the game): u32 n_verts, n_quads_a, n_quads_b, xyz, u32[4] quads."""
    nv, na, nb = struct.unpack_from('<3I', b, 0)
    if 12 + nv * 12 + (na + nb) * 16 != len(b):
        raise ValueError('size %d does not match the counts' % len(b))
    verts = [struct.unpack_from('<3f', b, 12 + i * 12) for i in range(nv)]
    o = 12 + nv * 12
    quads = [struct.unpack_from('<4I', b, o + i * 16) for i in range(na + nb)]
    return dict(verts=verts, quads_a=quads[:na], quads_b=quads[na:])


# ---------------------------------------------------------------- geometry helpers

def centre(poly):
    q = poly['quad']
    return tuple(sum(v[k] for v in q) / 4.0 for k in range(3))


def contains_xz(poly, p, margin=0.0):
    """p inside the quad seen from above (either winding), within `margin` units of its edges."""
    q = poly['quad']
    sign = 0
    for i in range(4):
        x1, z1 = q[i][0], q[i][2]
        x2, z2 = q[(i + 1) % 4][0], q[(i + 1) % 4][2]
        ln = math.hypot(x2 - x1, z2 - z1) or 1.0
        c = ((x2 - x1) * (p[2] - z1) - (z2 - z1) * (p[0] - x1)) / ln
        if abs(c) <= margin:
            continue
        s = 1 if c > 0 else -1
        if sign and s != sign:
            return False
        sign = s
    return True


def height_at(poly, p):
    """The quad's height under p (inverse-distance mix of its corners)."""
    w = [1.0 / (math.hypot(v[0] - p[0], v[2] - p[2]) + 1e-3) for v in poly['quad']]
    return sum(wi * v[1] for wi, v in zip(w, poly['quad'])) / sum(w)


def poly_at(polys, p, above=40.0, below=60.0):
    """Index of the polygon under (or nearest under) point p, or -1."""
    best, bd = -1, None
    for i, poly in enumerate(polys):
        if contains_xz(poly, p, 0.5):
            dy = p[1] - height_at(poly, p)
            if -above <= dy <= below and (bd is None or abs(dy) < bd):
                best, bd = i, abs(dy)
    if best < 0:                                    # just outside every quad: the nearest centre close by
        for i, poly in enumerate(polys):
            c = centre(poly)
            d = math.dist(c, p)
            if d < 60 and (bd is None or d < bd):
                best, bd = i, d
    return best


# ---------------------------------------------------------------- routes

def _dijkstra(adj, s, n, closed=()):
    dist = [math.inf] * n
    prev = [-1] * n
    dist[s] = 0.0
    h = [(0.0, s)]
    while h:
        d, u = heapq.heappop(h)
        if d > dist[u]:
            continue
        if u != s and u in closed:                 # may end on a closed polygon, not pass through it
            continue
        for v, c in adj[u]:
            nd = d + c
            if nd < dist[v] - 1e-6:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(h, (nd, v))
    return dist, prev


def steps(model):
    """Allowed polygon steps (a, b, cost): links (one-way ones only A -> B) and jump pad -> landing polygon."""
    polys = model['polys']
    cen = [centre(p) for p in polys]
    out = {}
    for l in model['links']:
        c = math.dist(cen[l['pa']], cen[l['pb']])
        for a, b in ((l['pa'], l['pb']),) + (() if l['flags'] & L_ONE_WAY else ((l['pb'], l['pa']),)):
            out[(a, b)] = min(out.get((a, b), math.inf), c)
    for j in model['jumps']:
        for pad in j['pads']:
            if 0 <= j['poly'] < len(polys) and j['poly'] != pad:
                out[(pad, j['poly'])] = min(out.get((pad, j['poly']), math.inf), math.dist(cen[pad], cen[j['poly']]))
    return out


def route_tables(model, closed=()):
    """next-hop paths: {(i, j): [polygons after i ... j]} of shortest routes."""
    n = len(model['polys'])
    adj = [[] for _ in range(n)]
    for (a, b), c in steps(model).items():
        adj[a].append((b, c))
    routes = []
    for s in range(n):
        dist, prev = _dijkstra(adj, s, n, closed)
        routes.append(prev)
    return routes


class _Pool:
    def __init__(self):
        self.data = bytearray()

    def add_tree(self, s, prev, n):
        """Offsets of every route from s. The route s -> j is read from its offset up to the byte j, so every
        polygon on one leaf's path (the polygons after s) shares that path's start."""
        children = [[] for _ in range(n)]
        for v in range(n):
            if v != s and prev[v] >= 0:
                children[prev[v]].append(v)
        offs = {}
        stack = [(s, [])]
        while stack:
            v, path = stack.pop()
            if v != s:
                path = path + [v]
            if not children[v] and path:
                start = len(self.data)
                self.data += bytes(path)
                for node in path:
                    offs.setdefault(node, start)
            for c in children[v]:
                stack.append((c, path))
        return offs


def _matrix(model, closed, pool):
    n = len(model['polys'])
    m = [[NO_ROUTE] * MAX_POLYS for _ in range(MAX_POLYS)]
    for s, prev in enumerate(route_tables(model, closed)):
        offs = pool.add_tree(s, prev, n)
        for j, o in offs.items():
            m[s][j] = o
    return m


# ---------------------------------------------------------------- writing

def check(model):
    """Problems that stop the export (list of text)."""
    out = []
    n = len(model['polys'])
    if n > MAX_POLYS:
        out.append('%d nav polygons; the game holds at most %d' % (n, MAX_POLYS))
    if 4 * n > MAX_VERTS:
        out.append('%d nav vertices; the game holds at most %d' % (4 * n, MAX_VERTS))
    if len(model['links']) > MAX_LINKS:
        out.append('%d nav links; the game holds at most %d' % (len(model['links']), MAX_LINKS))
    if len(model['navs']) > MAX_NAV:
        out.append('%d nav points; the game holds at most %d' % (len(model['navs']), MAX_NAV))
    if len(model['jumps']) > MAX_JUMP:
        out.append('%d jump points; the game holds at most %d' % (len(model['jumps']), MAX_JUMP))
    for k, l in enumerate(model['links']):
        if not (0 <= l['pa'] < n and 0 <= l['pb'] < n):
            out.append('link %d names a polygon that does not exist' % k)
            break
    return out


def write(model):
    """The 674,312-byte file for a model (see read). Raises ValueError when it does not fit."""
    problems = check(model)
    if problems:
        raise ValueError('; '.join(problems))
    polys, links, navs, jumps = model['polys'], model['links'], model['navs'], model['jumps']
    n = len(polys)
    b = bytearray(BATTLE_SIZE)
    # vertices: four per polygon, as the game's own files
    struct.pack_into('<I', b, O_VERTS, 4 * n)
    for i, p in enumerate(polys):
        for k, v in enumerate(p['quad']):
            struct.pack_into('<3f', b, 4 + 12 * (4 * i + k), *v)
    # ids per polygon
    ids = [[] for _ in range(n)]
    for j, jp in enumerate(jumps):
        for pad in jp['pads']:
            if 0 <= pad < n and polys[pad]['flags'] & F_JUMP:
                ids[pad].append(j)
    for k, nv in enumerate(navs):
        if 0 <= nv['poly'] < n and not polys[nv['poly']]['flags'] & F_JUMP:
            ids[nv['poly']].append(k + 1)
    for j, jp in enumerate(jumps):
        if 0 <= jp['poly'] < n and not polys[jp['poly']]['flags'] & F_JUMP:
            ids[jp['poly']].append(31 + j)
    plinks = [[] for _ in range(n)]
    for k, l in enumerate(links):
        for p in {l['pa'], l['pb']}:
            if len(plinks[p]) < MAX_POLY_LINKS:
                plinks[p].append(k)
    struct.pack_into('<I', b, O_POLYS, n)
    for i, p in enumerate(polys):
        o = O_POLYS + 4 + 84 * i
        w = (ids[i] + [-1] * MAX_POLY_IDS)[:MAX_POLY_IDS]
        struct.pack_into('<I8i4I16H', b, o, p['flags'], *w, *(4 * i + k for k in range(4)),
                         *(plinks[i] + [0xFFFF] * MAX_POLY_LINKS)[:MAX_POLY_LINKS])
    cen = [centre(p) for p in polys]
    struct.pack_into('<I', b, O_LINKS, len(links))
    for k, l in enumerate(links):
        struct.pack_into('<6f2iIfI', b, O_LINKS + 4 + 44 * k, *l['a'], *l['b'], l['pa'], l['pb'], l['flags'],
                         math.dist(cen[l['pa']], cen[l['pb']]), l.get('blocker', 0))
    struct.pack_into('<I', b, O_NAV, len(navs))
    for k, nv in enumerate(navs):
        struct.pack_into('<3fIIf', b, O_NAV + 4 + 24 * k, *nv['pos'], max(0, nv['poly']), nv.get('id', k),
                         nv.get('radius', 100.0))
    struct.pack_into('<I', b, O_JUMP, len(jumps))
    for k, jp in enumerate(jumps):
        struct.pack_into('<3fI', b, O_JUMP + 4 + 16 * k, *jp['pos'], max(0, jp['poly']))
    # routes: M0 / M2 the shortest; M1 / M3 / M4 avoid polygons that depend on objects (detours)
    pool = _Pool()
    m0 = _matrix(model, (), pool)
    obj = {i for i, p in enumerate(polys) if p['flags'] & F_OBJECTS}
    m1 = _matrix(model, obj, pool) if obj else m0
    if len(pool.data) > POOL:
        raise ValueError('the AI routes need %d bytes, the game holds %d: use fewer nav polygons'
                         % (len(pool.data), POOL))
    for k, m in enumerate((m0, m1, m0, m1, m1)):
        base = O_MATS + 0x10000 * k
        for r in range(MAX_POLYS):
            struct.pack_into('<128I', b, base + 512 * r, *m[r])
    for i in range(MAX_POLYS):
        b[O_SUB + i] = (polys[i].get('substitute', 255) & 0xFF) if i < n else 255
    struct.pack_into('<I', b, O_USED, len(pool.data))
    b[O_POOL:O_POOL + len(pool.data)] = pool.data
    return bytes(b)


def substitutes(model):
    """Per polygon: the most central polygon of its connected part (smallest summed route length)."""
    n = len(model['polys'])
    adj = [[] for _ in range(n)]
    for (a, c), cost in steps(model).items():
        adj[a].append((c, cost))
    dists = [_dijkstra(adj, s, n)[0] for s in range(n)]
    out = []
    for i in range(n):
        part = [j for j in range(n) if dists[i][j] < math.inf]
        out.append(min(part, key=lambda j: sum(dists[j][k] for k in part if dists[j][k] < math.inf)) if part else 255)
    return out
