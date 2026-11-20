"""Summarise a stage .dat: header, section tags, spawn layouts and collision.

  python tools/dump_dat.py <stNN.dat> [--spawns] [--records N]
"""
import argparse, collections, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from pdstage import dat

ap = argparse.ArgumentParser()
ap.add_argument('file')
ap.add_argument('--spawns', action='store_true', help='print every spawn entry')
ap.add_argument('--records', type=int, default=0, help='print the first N collision records')
a = ap.parse_args()

b = open(a.file, 'rb').read()
h = dat.header(b)
hx = lambda v: '-' if v is None else '%#x' % v
print(a.file, len(b), 'bytes')
print('layout slots ', ' '.join(hx(v) for v in h['layout_slots']))
print('layout counts', ' '.join(hx(v) for v in h['layout_counts']))
print('names %s  objects %s (count %d)  collision %s  EF00 %s  SP00 %s' % (
    hx(h['names']), hx(h['objects']), h['object_count'], hx(h['collision']), hx(h['ef00']), hx(h['sp00'])))
print('section tags:', ' '.join('%s@%#x' % (t, o) for o, t in dat.section_tags(b)))

layouts = dat.spawn_layouts(b)
print('spawn layouts: %d (%s entries)' % (len(layouts), ', '.join(str(len(l)) for l in layouts)))
if a.spawns:
    for li, l in enumerate(layouts):
        for s in l:
            print('  layout %d @%#x pos (%.1f %.1f %.1f) yaw %.2f orbs %s tail %s flags %08x' % (
                li, s.offset, *s.pos, s.yaw, ' '.join('(%.1f %.1f %.1f)' % o for o in s.orbs), s.tail, s.flags))

recs, vlists = dat.collision(b)
print('collision records %d  kinds %s' % (len(recs), dict(collections.Counter(r.kind for r in recs))))
print('surface types', dict(sorted(collections.Counter('%02x' % r.type for r in recs if r.kind == 3).items())))
print('vertex lists %d (%d verts)' % (len(vlists), sum(len(v.verts) for v in vlists)), 'check', dat.check_collision(b))
for r in recs[:a.records]:
    extra = ''
    if r.kind == 3:
        extra = 'c=(%.1f %.1f %.1f) r=%.1f min=(%.1f %.1f %.1f) max=(%.1f %.1f %.1f) vlist=%d ntri=%d' % (
            *r.center, r.radius, *r.bbox_min, *r.bbox_max, r.vlist, len(r.tris))
    elif r.kind == 8:
        extra = 'nverts=%d' % len(r.verts)
    print('  %#7x type %02x kind %d flags %02x size %#x %s' % (r.offset, r.type, r.kind, r.flags, r.size, extra))
