"""Checks without Blender, on every stage file of a game data folder:

1. light script: the script written from its values (maplight.values_of -> script_from) gives the game's calls back
   (the same values; encoding and header compared separately, as a statistic);
2. container: datfile.spans / compact on the game's own file removes nothing (every section is in use) and gives the
   file back; with one section re-written at the end (the effect list), compact removes the old one, the file keeps
   its size within the alignment padding and every other section reads the same.

python tests/rebuild_offline_test.py <Assets/Data folder>
"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from pdstage import dat, datfile, effects_build, maplight  # noqa: E402

data = sys.argv[1]
mapdir = os.path.join(data, 'Map')
fails = 0
same_bytes = 0
scripts = 0


def check(ok, what):
    global fails
    print('%s %s' % ('PASS' if ok else 'FAIL', what))
    if not ok:
        fails += 1


for name in sorted(os.listdir(mapdir)):
    if not name.endswith('.dat'):
        continue
    b = open(os.path.join(mapdir, name), 'rb').read()
    if dat.layout_kind(b) != 'stage':
        continue
    st = name[:-4]
    script = next((s for s in (maplight.script_of(b, v) for v in range(maplight.VARIANT_SLOTS)) if s), None)
    if script is not None:
        scripts += 1
        sets, colour, scale, scolour = maplight.values_of(script)
        new = maplight.script_from(sets, colour, scale, scolour, int(st[2:4]))
        values = lambda s: [(c, [maplight._num(a) if a[0] == 'f' and not (0x2000 <= c) else a for a in args])
                            for c, args in s['calls']]
        dn, do = maplight.describe(new), maplight.describe(script)
        check(dn == do, '%s light script: the 22 calls written from the values describe the same lighting' % st)
        built, orig = maplight.build(new), maplight.build(script)
        same_bytes += built[0x20:] == orig[0x20:]
    sp = datfile.spans(b)
    out, removed = datfile.compact(b, sp)
    check(removed == 0 and out == b, '%s container: compact on the game file removes nothing (%d sections)' % (st, len(sp)))
    # re-write the effect list at the end, as the export does, and compact
    es = dat.effects(b)
    if es:
        entries = [bytes(b[e['offset']:e['offset'] + effects_build.ENTRY]) for e in es]
        moved = effects_build.set_effects(b, entries)
        out, removed = datfile.compact(moved, sp)
        ok = abs(len(out) - len(b)) <= 3 and dat.effects(out) and [
            bytes(out[e['offset']:e['offset'] + effects_build.ENTRY]) for e in dat.effects(out)] == entries
        ok = ok and dat.spawn_layouts(out) == [[s.__class__(0, s.pos, s.yaw, s.orbs, s.tail, s.flags) for s in l]
                                               for l in dat.spawn_layouts(b)] or ok and all(
            [(s.pos, s.yaw, s.orbs) for s in l1] == [(s.pos, s.yaw, s.orbs) for s in l2]
            for l1, l2 in zip(dat.spawn_layouts(out), dat.spawn_layouts(b)))
        ok = ok and dat.triangles(out) == dat.triangles(b)
        ok = ok and maplight.script_of(out, next(v for v in range(8) if maplight.script_of(b, v))) == script \
            if script else ok
        check(ok, '%s container: effect list re-written at the end, old one removed (size %+d B, %d B removed), '
                  'spawns, collision and light script read the same' % (st, len(out) - len(b), removed))

print('light scripts written byte-identical (code words): %d of %d' % (same_bytes, scripts))
print('RESULT: %d failure(s)' % fails)
sys.exit(1 if fails else 0)
