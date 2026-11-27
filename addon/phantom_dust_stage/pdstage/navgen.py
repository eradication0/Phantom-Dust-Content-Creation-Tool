"""Build an AI navigation mesh (cad.py model) from a map's collision, and the links between nav polygons.

Pure Python: the caller passes a ray caster, cast(origin, direction, distance) -> (position, normal, index,
distance) or None, over the collision triangles in game space (y up). In Blender that is a mathutils BVHTree.

How it works:
1. A grid of columns (cell size CELL) over the walkable collision. Rays straight down find every floor in a
   column: surfaces flat enough to stand on (SLOPE), not a wall-only or respawn surface, above the fall-out
   height, with room for a fighter above (CLEAR).
2. Neighbouring floor cells are joined when their heights differ by at most STEP and no wall stands between
   them (a ray across at knee height).
3. Joined cells are merged into the largest rectangles that stay within FLAT of their first cell's height; the
   rectangles are the nav quads (the game holds 128). Too many: the grid gets coarser and tiny islands go.
4. Links: where a quad's edge meets another quad at the same height (a two-way link), or overlooks a lower one
   within DROP (a one-way link down, as the game's own drops).
5. Jump pads: the pad's quad gets the jump flag and jump points on the quads within reach above it.
6. Quads under breakable objects get the "depends on objects" flag, as the game's own: the AI avoids them while
   the object stands.
"""
import math

from . import cad

CELL = 10.0          # first grid size (game units); coarser if the result is too big
STEP = 12.0          # height a fighter walks up between neighbouring cells
CLEAR = 16.0         # free height above a floor
SLOPE = 0.65         # floor normal y at least (about 50 degrees)
FLAT = 20.0          # height range within one quad
MAX_SIDE = 160.0     # longest quad side
DROP = 220.0         # highest drop the AI takes (the game's own go to about 220)
KNEE = 6.0           # wall test height above the floor
NO_FLOOR = {0x11, 0x12, 0x14, 0x1F}    # respawn, character wall, ledge guard, camera wall
KILL_HEIGHT = 0.0


def _tri_normal(a, b, c):
    u = [b[k] - a[k] for k in range(3)]
    w = [c[k] - a[k] for k in range(3)]
    n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
    ln = math.sqrt(sum(x * x for x in n)) or 1.0
    return tuple(x / ln for x in n)


def floors(tris, cast, cell):
    """{(ix, iz): [y, ...]} floor heights per column (highest first), and the grid origin."""
    walk = [t for t in tris if t[3] not in NO_FLOOR and abs(_tri_normal(*t[:3])[1]) >= SLOPE
            and max(t[0][1], t[1][1], t[2][1]) > KILL_HEIGHT]
    if not walk:
        return {}, (0.0, 0.0)
    xs = [v[0] for t in walk for v in t[:3]]
    zs = [v[2] for t in walk for v in t[:3]]
    top = max(v[1] for t in tris for v in t[:3]) + 50.0
    bottom = min(v[1] for t in walk for v in t[:3]) - 1.0
    x0, z0 = min(xs), min(zs)
    nx, nz = int((max(xs) - x0) / cell) + 1, int((max(zs) - z0) / cell) + 1
    out = {}
    for ix in range(nx):
        x = x0 + (ix + 0.5) * cell
        for iz in range(nz):
            z = z0 + (iz + 0.5) * cell
            y = top
            levels = []
            while y > bottom:
                hit = cast((x, y, z), (0.0, -1.0, 0.0), y - bottom)
                if hit is None:
                    break
                p, n, idx, _d = hit
                t = tris[idx]
                hy = p[1]
                if (t[3] not in NO_FLOOR and abs(n[1]) >= SLOPE and hy > KILL_HEIGHT
                        and cast((x, hy + 0.5, z), (0.0, 1.0, 0.0), CLEAR) is None):
                    if not levels or levels[-1] - hy > STEP:
                        levels.append(hy)
                y = hy - 0.05
            if levels:
                out[(ix, iz)] = levels
    return out, (x0, z0)


def _joined(cells, cast, cell, origin, a, ya, b, yb):
    if abs(ya - yb) > STEP:
        return False
    x0, z0 = origin
    pa = (x0 + (a[0] + 0.5) * cell, max(ya, yb) + KNEE, z0 + (a[1] + 0.5) * cell)
    d = ((b[0] - a[0]) * cell, 0.0, (b[1] - a[1]) * cell)
    ln = math.sqrt(d[0] ** 2 + d[2] ** 2)
    return cast(pa, (d[0] / ln, 0.0, d[2] / ln), ln) is None


def rectangles(cells, cast, cell, origin):
    """Greedy largest rectangles of joined cells: [(ix0, iz0, ix1, iz1, {(ix, iz): y})] (ix1 / iz1 exclusive)."""
    level = {}                                       # (ix, iz, k) -> y
    for (ix, iz), ys in cells.items():
        for k, y in enumerate(ys):
            level[(ix, iz, k)] = y
    used = set()
    join_cache = {}

    def joined(a, b):
        key = (a, b) if a < b else (b, a)
        if key not in join_cache:
            join_cache[key] = _joined(cells, cast, cell, origin, a[:2], level[a], b[:2], level[b])
        return join_cache[key]

    def pick(ix, iz, near):
        """The free level in column (ix, iz) joined to `near` (a level key), or None."""
        for k in range(len(cells.get((ix, iz), ()))):
            key = (ix, iz, k)
            if key not in used and joined(near, key):
                return key
        return None

    maxn = max(1, int(MAX_SIDE / cell))
    out = []
    for seed in sorted(level, key=lambda k: (k[1], k[0], k[2])):
        if seed in used:
            continue
        y0 = level[seed]
        best = None
        for order in ('xz', 'zx'):
            rect = {seed[:2]: seed}
            ix0, iz0 = seed[0], seed[1]
            w = h = 1
            # first direction
            while (w if order == 'xz' else h) < maxn:
                nxt = (ix0 + w, iz0) if order == 'xz' else (ix0, iz0 + h)
                prev = rect[(nxt[0] - 1, nxt[1])] if order == 'xz' else rect[(nxt[0], nxt[1] - 1)]
                key = pick(nxt[0], nxt[1], prev)
                if key is None or abs(level[key] - y0) > FLAT:
                    break
                rect[nxt] = key
                if order == 'xz':
                    w += 1
                else:
                    h += 1
            # second direction: whole rows / columns
            while (h if order == 'xz' else w) < maxn:
                row = {}
                ok = True
                span = range(w) if order == 'xz' else range(h)
                for s in span:
                    pos = (ix0 + s, iz0 + h) if order == 'xz' else (ix0 + w, iz0 + s)
                    back = rect[(pos[0], pos[1] - 1)] if order == 'xz' else rect[(pos[0] - 1, pos[1])]
                    key = pick(pos[0], pos[1], back)
                    if key is None or key in row.values() or abs(level[key] - y0) > FLAT:
                        ok = False
                        break
                    if s:                            # joined along the row as well
                        side = row[(pos[0] - 1, pos[1])] if order == 'xz' else row[(pos[0], pos[1] - 1)]
                        if not joined(side, key):
                            ok = False
                            break
                    row[pos] = key
                if not ok:
                    break
                rect.update(row)
                if order == 'xz':
                    h += 1
                else:
                    w += 1
            if best is None or len(rect) > len(best[2]):
                best = (w, h, rect)
        w, h, rect = best
        used.update(rect.values())
        out.append((seed[0], seed[1], seed[0] + w, seed[1] + h, {c: level[k] for c, k in rect.items()}))
    return out


def _quad(r, cell, origin):
    ix0, iz0, ix1, iz1, ys = r
    x0, z0 = origin

    def corner(ix, iz, cx, cz):
        return (x0 + cx * cell, ys[(ix, iz)], z0 + cz * cell)

    # clockwise seen from above in game x / z, as the game's own
    return [corner(ix0, iz0, ix0, iz0), corner(ix0, iz1 - 1, ix0, iz1),
            corner(ix1 - 1, iz1 - 1, ix1, iz1), corner(ix1 - 1, iz0, ix1, iz0)]


def _islands(rects):
    """Rectangles grouped into touching groups (index lists)."""
    owner = {}
    for i, r in enumerate(rects):
        for c in r[4]:
            owner.setdefault(c, []).append(i)
    parent = list(range(len(rects)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, r in enumerate(rects):
        for (ix, iz), y in r[4].items():
            for d in ((1, 0), (0, 1)):
                for j in owner.get((ix + d[0], iz + d[1]), ()):
                    if j != i and abs(rects[j][4][(ix + d[0], iz + d[1])] - y) <= STEP:
                        parent[find(i)] = find(j)
    groups = {}
    for i in range(len(rects)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


# ---------------------------------------------------------------- links

def links(polys, blocked=None, sample=4.0):
    """Links between nav quads (cad model links): two-way where an edge meets a quad at about the same height,
    one-way down where it overlooks a lower quad within DROP. blocked(p, q) -> True stops a link (a wall or a
    railing between the two points)."""
    found = {}
    bucket = {}
    BK = 40.0
    for j, o in enumerate(polys):
        xs = [v[0] for v in o['quad']]
        zs = [v[2] for v in o['quad']]
        for bx in range(int(math.floor(min(xs) / BK)), int(math.floor(max(xs) / BK)) + 1):
            for bz in range(int(math.floor(min(zs) / BK)), int(math.floor(max(zs) / BK)) + 1):
                bucket.setdefault((bx, bz), []).append(j)
    for i, p in enumerate(polys):
        q = p['quad']
        c = cad.centre(p)
        for e in range(4):
            a, b = q[e], q[(e + 1) % 4]
            ln = math.hypot(b[0] - a[0], b[2] - a[2])
            if ln < 1e-3:
                continue
            # outward normal (away from the centre) in x / z
            nx, nz = (b[2] - a[2]) / ln, -(b[0] - a[0]) / ln
            mid = ((a[0] + b[0]) / 2, (a[2] + b[2]) / 2)
            if (mid[0] - c[0]) * nx + (mid[1] - c[2]) * nz < 0:
                nx, nz = -nx, -nz
            steps = max(1, int(ln / sample))
            runs = []                                 # [(target, one_way, t0, t1)]
            for s in range(steps):
                t = (s + 0.5) / steps
                ex, ey, ez = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)
                pt = (ex + nx * 1.5, ey, ez + nz * 1.5)
                tgt, ow = -1, False
                for j in bucket.get((int(math.floor(pt[0] / BK)), int(math.floor(pt[2] / BK))), ()):
                    o = polys[j]
                    if j == i or not cad.contains_xz(o, pt, 0.0):
                        continue
                    dy = ey - cad.height_at(o, pt)
                    if abs(dy) <= STEP:
                        tgt, ow = j, False
                        break
                    if STEP < dy <= DROP and (tgt < 0 or ow):
                        tgt, ow = j, True
                if tgt >= 0 and blocked is not None:
                    hy = cad.height_at(polys[tgt], pt)
                    if blocked((ex - nx * 2, max(ey, hy) + KNEE if not ow else ey + KNEE, ez - nz * 2),
                               (pt[0] + nx * 2, (max(ey, hy) if not ow else ey) + KNEE, pt[2] + nz * 2)):
                        tgt = -1
                if runs and runs[-1][0] == tgt and runs[-1][1] == ow:
                    runs[-1][3] = t
                else:
                    runs.append([tgt, ow, t, t])
            for tgt, ow, t0, t1 in runs:
                if tgt < 0:
                    continue
                t0 -= 0.5 / steps
                t1 += 0.5 / steps
                pa = tuple(a[k] + (b[k] - a[k]) * t0 for k in range(3))
                pb = tuple(a[k] + (b[k] - a[k]) * t1 for k in range(3))
                span = math.hypot(pb[0] - pa[0], pb[2] - pa[2])
                if span < 4.0:
                    continue
                key = (i, tgt, True) if ow else (min(i, tgt), max(i, tgt), False)
                if key not in found or found[key][2] < span:
                    found[key] = (pa, pb, span, i, tgt)
    out = []
    for (x, y, ow), (pa, pb, span, i, tgt) in found.items():
        if not ow and (y, x, True) in found:          # a same-height link beats a drop between the same two
            continue
        if ow and (min(x, y), max(x, y), False) in found:
            continue
        out.append(dict(a=pa, b=pb, pa=i if ow else x, pb=tgt if ow else y, flags=cad.L_ONE_WAY if ow else 0,
                        blocker=0, span=span))
    # the game lists at most 16 links per quad: keep the widest two-way ones first
    out.sort(key=lambda l: (l['flags'], -l['span']))
    count = [0] * len(polys)
    kept = []
    for l in out:
        if count[l['pa']] < cad.MAX_POLY_LINKS and count[l['pb']] < cad.MAX_POLY_LINKS:
            count[l['pa']] += 1
            count[l['pb']] += 1
            kept.append(l)
    for l in kept:
        l.pop('span', None)
    return kept


# ---------------------------------------------------------------- jump pads and objects

def _closest_in(poly, p):
    xs = [v[0] for v in poly['quad']]
    zs = [v[2] for v in poly['quad']]
    c = cad.centre(poly)
    x = min(max(p[0], min(xs)), max(xs))
    z = min(max(p[2], min(zs)), max(zs))
    # a little inside, towards the centre
    dx, dz = c[0] - x, c[2] - z
    d = math.hypot(dx, dz)
    if d > 8:
        x, z = x + dx / d * 8, z + dz / d * 8
    return (x, cad.height_at(poly, (x, 0, z)), z)


def add_jumps(model, pads):
    """pads: [(pos, power)]: flag each pad's quad and give it jump points on the quads in reach above it."""
    polys = model['polys']
    jumps = model['jumps']
    for pos, power in pads:
        i = cad.poly_at(polys, pos)
        if i < 0:
            continue
        polys[i]['flags'] |= cad.F_JUMP
        reach = min(160.0, 0.6 * power + 30.0)
        cands = []
        for j, o in enumerate(polys):
            if j == i:
                continue
            lp = _closest_in(o, pos)
            up = lp[1] - pos[1]
            d = math.hypot(lp[0] - pos[0], lp[2] - pos[2])
            if STEP < up <= 0.95 * power and d <= reach:
                cands.append((d, j, lp))
        cands.sort()
        for d, j, lp in cands[:3]:
            if len(jumps) >= cad.MAX_JUMP:
                break
            jumps.append(dict(pos=lp, poly=j, pads=[i]))


def flag_objects(model, boxes):
    """boxes: [(min xyz, max xyz)] of breakable objects: quads under them depend on objects (flag 1)."""
    for p in model['polys']:
        xs = [v[0] for v in p['quad']]
        zs = [v[2] for v in p['quad']]
        ys = [v[1] for v in p['quad']]
        for lo, hi in boxes:
            if (lo[0] < max(xs) and hi[0] > min(xs) and lo[2] < max(zs) and hi[2] > min(zs)
                    and lo[1] < max(ys) + 20 and hi[1] > min(ys) - 5):
                p['flags'] |= cad.F_OBJECTS
                break


# ---------------------------------------------------------------- all together

def _subset(model, keep):
    """The model with only the polygons in `keep` (indices renumbered; links and jumps that lose an end go)."""
    keep = sorted(keep)
    new = {o: n for n, o in enumerate(keep)}
    polys = [model['polys'][i] for i in keep]
    links_ = [dict(l, pa=new[l['pa']], pb=new[l['pb']]) for l in model['links'] if l['pa'] in new and l['pb'] in new]
    jumps = []
    for j in model['jumps']:
        pads = [new[p] for p in j['pads'] if p in new]
        if j['poly'] in new and pads:
            jumps.append(dict(j, poly=new[j['poly']], pads=pads))
    return dict(polys=polys, links=links_, navs=[], jumps=jumps)


def reachable(model, starts):
    """Polygons a fighter can get to from any of `starts` (walking, dropping, jump pads)."""
    adj = {}
    for (a, b) in cad.steps(model):
        adj.setdefault(a, []).append(b)
    seen = set(starts)
    todo = list(starts)
    while todo:
        u = todo.pop()
        for v in adj.get(u, ()):
            if v not in seen:
                seen.add(v)
                todo.append(v)
    return seen


def main_angle(tris):
    """The map's main direction (radians, 0..90 degrees): the grid is turned to it, so roads at an angle get
    long quads instead of stairs. From the floor edges' directions, weighted by length."""
    hist = [0.0] * 90
    for t in tris:
        if abs(_tri_normal(*t[:3])[1]) < SLOPE:
            continue
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            dx, dz = b[0] - a[0], b[2] - a[2]
            ln = math.hypot(dx, dz)
            if ln > 1:
                hist[int(math.degrees(math.atan2(dz, dx)) % 90) % 90] += ln
    smooth = [hist[i - 1] + 2 * hist[i] + hist[(i + 1) % 90] for i in range(90)]
    best = max(range(90), key=lambda i: smooth[i])
    return math.radians(best + 0.5) if smooth[best] > 1.5 * (sum(smooth) / 90.0) and best not in (0, 89) else 0.0


def _turn(p, c, s):
    return (p[0] * c - p[2] * s, p[1], p[0] * s + p[2] * c)


def generate(tris, cast, pads=(), boxes=(), spawns=(), progress=None):
    """tris: [(v0, v1, v2, surface)] game space; pads [(pos, power)]; boxes [(min, max)] of breakables; spawns
    [pos]: only floor a fighter can reach from a spawn is kept. Returns (model, report text)."""
    ang = main_angle(tris)
    if ang:                                          # work in a frame turned to the map's main direction
        c, s = math.cos(-ang), math.sin(-ang)
        back = (math.cos(ang), math.sin(ang))
        raw_cast = cast

        def cast(o, d, dist):
            hit = raw_cast(_turn(o, *back), _turn(d, *back), dist)
            if hit is None:
                return None
            return (_turn(hit[0], c, s), _turn(hit[1], c, s)) + tuple(hit[2:])

        tris = [(_turn(t[0], c, s), _turn(t[1], c, s), _turn(t[2], c, s), t[3]) for t in tris]
        pads = [(_turn(p, c, s), pw) for p, pw in pads]
        spawns = [_turn(p, c, s) for p in spawns]
        game_boxes = boxes                           # applied after turning back
        model, report = _generate(tris, cast, pads, (), spawns, progress)
        for p in model['polys']:
            p['quad'] = [_turn(v, *back) for v in p['quad']]
        for l in model['links']:
            l['a'], l['b'] = _turn(l['a'], *back), _turn(l['b'], *back)
        for j in model['jumps']:
            j['pos'] = _turn(j['pos'], *back)
        flag_objects(model, game_boxes)
        return model, report + ', turned %.0f degrees' % math.degrees(ang)
    return _generate(tris, cast, pads, boxes, spawns, progress)


def _generate(tris, cast, pads, boxes, spawns, progress):

    def blocked(p, q):
        d = [q[k] - p[k] for k in range(3)]
        ln = math.sqrt(sum(x * x for x in d))
        return ln > 1e-3 and cast(p, tuple(x / ln for x in d), ln) is not None

    sizes = (CELL, 12.0, 14.0, 17.0, 20.0, 24.0, 28.0, 34.0, 40.0)
    best = None
    for cell in sizes:
        cells, origin = floors(tris, cast, cell)
        if not cells:
            raise ValueError('no floor found in the collision (Colliders, or Visuals marked as collision)')
        rects = rectangles(cells, cast, cell, origin)
        groups = _islands(rects)
        total = sum(len(r[4]) for r in rects)
        keep = set()
        for g in groups:                             # little islands (a crate top) go
            if sum(len(rects[i][4]) for i in g) >= max(4, 0.005 * total):
                keep.update(g)
        rects = [r for i, r in enumerate(rects) if i in keep]
        if len(rects) > 3 * cad.MAX_POLYS and cell != sizes[-1]:
            if progress:
                progress(cell, len(rects))
            continue
        polys = [dict(quad=_quad(r, cell, origin), flags=0, substitute=255, cells=len(r[4])) for r in rects]
        model = dict(polys=polys, links=links(polys, blocked), navs=[], jumps=[])
        add_jumps(model, pads)
        if spawns:
            starts = {i for i in (cad.poly_at(polys, sp, above=30, below=80) for sp in spawns) if i >= 0}
            if starts:
                model = _subset(model, reachable(model, starts))
        if progress:
            progress(cell, len(model['polys']))
        best = model
        if len(model['polys']) <= cad.MAX_POLYS:
            break
    model = best
    if len(model['polys']) > cad.MAX_POLYS:
        # still too many on the coarsest grid: the smallest quads go
        order = sorted(range(len(model['polys'])), key=lambda i: -model['polys'][i]['cells'])
        model = _subset(model, order[:cad.MAX_POLYS])
    for p in model['polys']:
        p.pop('cells', None)
    flag_objects(model, boxes)
    for p, s in zip(model['polys'], cad.substitutes(model)):
        p['substitute'] = s
    report = '%d nav quads (grid %g), %d links, %d jump points' % (len(model['polys']), cell,
                                                                   len(model['links']), len(model['jumps']))
    return model, report
