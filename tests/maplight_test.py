"""Lighting script check (plain Python): every map's script rebuilds byte-identical, and an edit reads back.

  python tests/maplight_test.py <Assets/Data/Map folder>
"""
import glob
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from pdstage import maplight as ml  # noqa: E402

folder = sys.argv[1]
ok = n = 0
for p in sorted(glob.glob(os.path.join(folder, 'st[0-9][0-9].dat'))):
    b = open(p, 'rb').read()
    for v in range(ml.VARIANT_SLOTS):
        off = struct.unpack_from('<I', b, ml.H_SCRIPT + 4 * v)[0]
        if off == 0xFFFFFFFF or off + 8 > len(b):        # st00 is laid out differently
            continue
        ftab = struct.unpack_from('<I', b, off + 4)[0]
        raw = b[off:off + ftab + 12]
        n += 1
        ok += ml.build(ml.parse(raw)) == raw
print('scripts rebuilt identical: %d of %d' % (ok, n))

b = open(os.path.join(folder, 'st04.dat'), 'rb').read()
sc = ml.script_of(b)
ml.set_light(sc, 1, (0.0, -1.0, 0.0), (255, 0, 0), (0, 0, 90))
ml.set_fog(sc, 0, ml.FOG_LINEAR, (10, 20, 30), start=100, end=1500)
nb = ml.write(b, sc)
d = ml.describe(ml.script_of(nb))['sets']
good = (d[1]['diffuse'] == (255, 0, 0) and d[1]['ambient'] == (0, 0, 90) and d[1]['direction'] == (0.0, -1.0, 0.0)
        and d[0]['fog_start'] == 100 and d[0]['fog_end'] == 1500 and d[0]['fog_colour'] == (10, 20, 30)
        and struct.unpack_from('<I', nb, 0x138)[0] == len(nb))
print('edit reads back:', good)
sys.exit(0 if ok == n and good else 1)
