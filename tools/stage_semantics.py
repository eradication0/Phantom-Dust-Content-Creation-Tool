"""What the game reads from a stage .dat, compared between the game file and a rebuilt one (tolerances in game units).

python tools/stage_semantics.py <repository> <game .dat> <rebuilt .dat> -> one line of results (JSON on the last line)
Checks: spawns (positions, facing, orb points), collision (triangles per surface kind, as sets), placements per list
(class, phase / argument, position, turn as a matrix), each placement's object: its collision triangle count and its
hit / piece sounds, effects (records as sets, values within tolerance), light script (values), MD00 pairs, SP00,
blob list and enter chunks (bytes).
"""
import json
import math
import struct
import sys

repo, a_path, b_path = sys.argv[1:4]
sys.path.insert(0, repo)
from pdstage import alr, dat, effects_build, maplight, objects_build  # noqa: E402

A, B = open(a_path, 'rb').read(), open(b_path, 'rb').read()
import os  # noqa: E402
a_alr, b_alr = (p[:-4] + '.alr' for p in (a_path, b_path))
AL = open(a_alr, 'rb').read() if os.path.isfile(a_alr) else None
BL = open(b_alr, 'rb').read() if os.path.isfile(b_alr) else None
out = {}
if dat.layout_kind(A) != 'stage':
    out['kind'] = 'not a stage file: ' + ('identical' if A == B else 'differs')
    print(json.dumps(out))
    sys.exit(0)

# spawns
la, lb = dat.spawn_layouts(A), dat.spawn_layouts(B)
d = 0.0
ok = len(la) == len(lb) and all(len(x) == len(y) for x, y in zip(la, lb))
for x, y in zip(la, lb):
    for s, t in zip(x, y):
        d = max(d, max(abs(p - q) for p, q in zip(s.pos, t.pos)),
                abs(math.atan2(math.sin(s.yaw - t.yaw), math.cos(s.yaw - t.yaw))) * 100,
                max(abs(p - q) for o1, o2 in zip(s.orbs, t.orbs) for p, q in zip(o1, o2)))
out['spawns'] = 'same (max %.4f)' % d if ok and d < 0.01 else 'DIFFER (max %.4f, counts %s)' % (
    d, [len(x) for x in lb])


def tri_key(t, q=0.01):
    v = sorted(tuple(round(c / q) for c in p) for p in t[:3])
    return (t[4],) + tuple(v)


ta = sorted(tri_key(t) for t in dat.triangles(A))
tb = sorted(tri_key(t) for t in dat.triangles(B))
from collections import Counter  # noqa: E402
ca, cb = Counter(ta), Counter(tb)
miss = sum((ca - cb).values())
extra = sum((cb - ca).values())
if miss or extra:                                     # 0.01 grid boundaries: look again with a tolerance
    def near(t, pool):
        flat = lambda k: [c for p in k[1:] for c in p]          # grid units of 0.01
        ft = flat(t)
        return any(t[0] == u[0] and all(abs(p - q) <= 2 for p, q in zip(ft, flat(u))) for u in pool)
    left = list((ca - cb).elements())
    pool = list((cb - ca).elements())
    miss = sum(1 for t in left if not near(t, pool))
out['collision'] = '%d triangles, %s' % (len(ta), 'same' if not miss else '%d not matched' % miss)

# placements
na, tab_a, pa = objects_build.read_objects(A)
nb, tab_b, pb = objects_build.read_objects(B)


def rot_m(r):
    rx, ry, rz = r
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    return (cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx, sz * cy, sz * sy * sx + cz * cx,
            sz * sy * cx - cz * sx, -sy, cy * sx, cy * cx)


def col_count(b, table, oid):
    if not 0 <= oid < len(table) or table[oid][6] == dat.NONE:
        return 0
    recs, _v = dat.collision(b, base=table[oid][6])
    return sum(len(r.tris) for r in recs if r.kind == dat.KIND_MESH)


def snd(b, oid):
    o = struct.unpack_from('<I', b, 0xF8)[0]
    if o == dat.NONE or o + (oid + 1) * 16 > len(b):
        return None
    return struct.unpack_from('<8H', b, o + oid * 16)[1:3]


_roots = {}


def root_values(al, table, oid):
    """The object's model roots as the game reads them for its behaviour: the first joint's values (hits, damage,
    debris stays) of the intact, broken and debris roots and the broken root's joint count (its pieces)."""
    if al is None or not 0 <= oid < len(table):
        return None
    key = (id(al), oid)
    if key not in _roots:
        h = alr.header(al)
        out = []
        for k in range(3):
            r = table[oid][k]
            if r == dat.NONE or r >= len(h['roots']):
                out.append(None)
                continue
            ms = alr.meshes(al, h['roots'][r])
            nodes = ms[0]['nodes'] if ms else []
            pieces = sum(1 for n in nodes if n.get('parent') == 0) if k == 1 else None
            out.append((tuple(round(v, 2) for v in nodes[0]['values']) if nodes else (), pieces) if ms else 'empty')
        _roots[key] = tuple(out)
    return _roots[key]


def pkey(b, table, p, al=None):
    return (p['slot'], p['category'], p['type'], tuple(p['extra']), tuple(round(c, 1) for c in p['pos']),
            tuple(round(c, 2) for c in rot_m(p['rot'])), col_count(b, table, p['object']), snd(b, p['object']),
            root_values(al, table, p['object']))


use_alr = AL is not None and BL is not None
ka = Counter(pkey(A, tab_a, p, AL if use_alr else None) for p in pa)
kb = Counter(pkey(B, tab_b, p, BL if use_alr else None) for p in pb)
out['placements'] = '%d in lists %s, %s' % (len(pa), sorted({p['slot'] for p in pa}),
                                            ('same (class, position, turn, collider size, sounds%s)'
                                             % (', model roots: hits, damage, debris, pieces' if use_alr else ''))
                                            if ka == kb else
                                            '%d not matched of %d (rebuilt has %d)' % (sum((ka - kb).values()), len(pa), len(pb)))


def ekey(raw):
    f = effects_build.fields(raw)
    return (f['cls'], f['when'], f['id'], f['mode'], tuple(f['params']),
            tuple(round(c, 1) for c in f['pos']), tuple(round(c, 2) for c in rot_m(f['rot'])),
            tuple(round(abs(c), 3) for c in f['scale']), tuple(round(c, 3) for c in f['values']))


ea = Counter(ekey(A[e['offset']:e['offset'] + 0x5C]) for e in dat.effects(A))
eb = Counter(ekey(B[e['offset']:e['offset'] + 0x5C]) for e in dat.effects(B))
out['effects'] = '%d, %s' % (sum(ea.values()), 'same' if ea == eb else '%d not matched' % sum((ea - eb).values()))


def light(b):
    s = next((s for s in (maplight.script_of(b, v) for v in range(8)) if s), None)
    if s is None:
        return None
    return maplight.describe(s)


def close(x, y):
    if isinstance(x, dict):
        return isinstance(y, dict) and x.keys() == y.keys() and all(close(x[k], y[k]) for k in x)
    if isinstance(x, (list, tuple)):
        return isinstance(y, (list, tuple)) and len(x) == len(y) and all(close(p, q) for p, q in zip(x, y))
    if isinstance(x, float) or isinstance(y, float):
        return abs(x - y) <= max(1e-3, 1e-5 * abs(x))
    return x == y


out['light script'] = 'none' if light(A) is None and light(B) is None else (
    'same values' if close(light(A), light(B)) else 'DIFFER')
ma, mb = dat.md00(A), dat.md00(B)
out['md00 pairs'] = 'same' if (ma and mb and ma[2] == mb[2]) or ma == mb else 'DIFFER'


def section(b, word, end_words):
    o = struct.unpack_from('<I', b, word)[0]
    if o == dat.NONE:
        return None
    starts = sorted({struct.unpack_from('<I', b, w)[0] for w in range(0x04, 0x138, 4)
                     if w not in range(0x30, 0x5C, 4) and w != 0x60} - {dat.NONE} | {len(b)})
    nxt = next(s for s in starts if s > o)
    return bytes(b[o:nxt])


for name, word in (('SP00', 0x9C), ('blob list', 0xF4), ('enter chunks', 0xFC)):
    sa, sb = section(A, word, None), section(B, word, None)
    if sa is None and sb is None:
        out[name] = 'none'
    else:
        # the span to the next section can end with the next section's tag: compare the shorter one
        n = min(len(sa or b''), len(sb or b''))
        out[name] = 'same' if sa is not None and sb is not None and sa[:n] == sb[:n] and n >= min(len(sa), len(sb)) - 4 \
            else 'DIFFER'
print(json.dumps(out))
