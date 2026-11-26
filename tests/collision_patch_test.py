"""Collision edits written into the file's own records (collision_build.patch), no Blender needed.

  python tests/collision_patch_test.py <Assets/Data/Map folder> [stNN ...]

For each map: the file's own triangles give the file back; one surface type moved 5 units changes only its
triangles' records and vertices (the file keeps its size when no vertex is shared with another type, else the
block is appended once); taking the move back gives the game's file back (byte for byte, but for a value whose
move crosses a power of two: float32 rounding, at most a few bytes); one triangle removed,
then put back; one triangle added, then taken away. Every result is read back with dat.triangles and
dat.check_collision.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'addon', 'phantom_dust_stage'))
from pdstage import collision_build as cb, dat  # noqa: E402

mdir = sys.argv[1]
stages = sys.argv[2:] or sorted(n[:-4] for n in os.listdir(mdir)
                                if n.endswith('.dat') and n.startswith('st') and '_' not in n)
fails = 0


S = 0.1                     # Blender units per game unit (the add-on's default)


def blend(v):
    """A game position as the import stores it (32-bit float of value * S) and the export reads it back."""
    return tuple(struct.unpack('<f', struct.pack('<f', x * S))[0] / S for x in v)


def scene_of(b):
    """What the add-on's import gives back as collision: per surface type, the file's triangles in order."""
    tris = dat.triangles(b)
    return [(blend(v0), blend(v1), blend(v2), st) for st in sorted({t[4] for t in tris})
            for v0, v1, v2, _n, st2 in tris if st2 == st]


def check(name, ok, info=''):
    global fails
    print('%-44s %s %s' % (name, 'PASS' if ok else 'FAIL', info))
    fails += 0 if ok else 1


def valid(b):
    c = dat.check_collision(b)
    return c['bad_index'] == 0 and c['bad_normal'] == 0 and c['flipped'] == 0, c


def same_tris(b, want, tol=0.01):
    """The file's triangles are `want` (same corners in the same order, same surface), up to float rounding."""
    got = [(t[0], t[1], t[2], t[4]) for t in dat.triangles(b)]
    if len(got) != len(want):
        return False
    cells = {}
    for i, g in enumerate(got):
        cells.setdefault((g[3],) + tuple(round(x) for x in g[0]), []).append(i)
    free = set(range(len(got)))
    for w in want:
        hit = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for i in cells.get((w[3], round(w[0][0]) + dx, round(w[0][1]) + dy, round(w[0][2]) + dz), ()):
                        if i in free and all(abs(a - c) <= tol for p, q in zip(got[i][:3], w[:3]) for a, c in zip(p, q)):
                            hit = i
                            break
                    if hit is not None:
                        break
                if hit is not None:
                    break
            if hit is not None:
                break
        if hit is None:
            return False
        free.discard(hit)
    return True


def diff_bytes(a, b):
    return sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))


for st in stages:
    p = os.path.join(mdir, st + '.dat')
    o = open(p, 'rb').read()
    if dat.layout_kind(o) != 'stage' or not dat.triangles(o):
        print('%s: no stage collision, skipped' % st)
        continue
    sc = scene_of(o)
    r = cb.patch(o, sc, scale=S)
    check(st + ' untouched', r is not None and r[0] == o)
    # move every triangle of the first surface type by 5 units up
    t0 = sc[0][3]
    moved = [((v0[0], v0[1] + 5, v0[2]), (v1[0], v1[1] + 5, v1[2]), (v2[0], v2[1] + 5, v2[2]), s) if s == t0
             else (v0, v1, v2, s) for v0, v1, v2, s in sc]
    e1, s1 = cb.patch(o, moved, scale=S)
    ok, c = valid(e1)
    check(st + ' move type %02X' % t0, ok and same_tris(e1, moved),
          '%d moved, %d new vertices, %s, %d bytes differ, size %+d' % (
              s1['moved'], s1['new_vertices'], 'in place' if s1['in_place'] else 'appended', diff_bytes(o, e1),
              len(e1) - len(o)))
    e2, s2 = cb.patch(e1, [tuple((v[0], v[1] - 5, v[2]) for v in x[:3]) + (x[3],) if x[3] == t0 else x
                           for x in scene_of(e1)], scale=S)     # the export re-imported, the move taken back
    # exact, except where a value and value + 5 lie in different powers of two (float32 loses a bit there)
    check(st + ' move taken back', len(e2) == len(o) and diff_bytes(o, e2) <= 16 and same_tris(e2, sc),
          '%s, %d bytes differ, size %+d' % ('identical' if e2 == o else 'float rounding', diff_bytes(o, e2),
                                            len(e2) - len(o)))
    # remove the last triangle of the first type, then put it back
    k = max(i for i, t in enumerate(sc) if t[3] == t0)
    fewer = sc[:k] + sc[k + 1:]
    e3, s3 = cb.patch(o, fewer, scale=S)
    ok, c = valid(e3)
    check(st + ' remove one triangle', ok and same_tris(e3, fewer), '%d removed, size %+d' % (s3['removed'], len(e3) - len(o)))
    e4, _ = cb.patch(e3, sc, scale=S)
    ok, c = valid(e4)
    check(st + ' removed triangle put back', ok and same_tris(e4, sc),
          '%d bytes differ, size %+d (put back as a new record)' % (diff_bytes(o, e4), len(e4) - len(o)))
    # add a triangle, then take it away
    v0 = sc[0][0]
    more = sc + [((v0[0] + 100, v0[1] + 50, v0[2]), (v0[0] + 100, v0[1] + 50, v0[2] + 40),
                  (v0[0] + 140, v0[1] + 50, v0[2]), 0x08)]
    e5, s5 = cb.patch(o, more, scale=S)
    ok, c = valid(e5)
    check(st + ' add one triangle', ok and same_tris(e5, more), '%d added, size %+d' % (s5['added'], len(e5) - len(o)))
    e6, _ = cb.patch(e5, sc, scale=S)
    ok, c = valid(e6)
    check(st + ' added triangle taken away', ok and same_tris(e6, sc),
          '%d bytes differ, size %+d' % (diff_bytes(o, e6), len(e6) - len(o)))
print('RESULT: %d failure(s)' % fails)
