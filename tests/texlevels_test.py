"""Every mip level of every plain texture of a game data folder: decoded (pdstage/texlevels.py) and encoded again in
the game's own format. Uncompressed formats (B8G8R8A8, B5G6R5, B4G4R4A4, B5G5R5A1, linear or swizzled) must give the
game's bytes back; DXT1 / DXT3 / DXT5 decode to within block re-encoding error (mean per channel: 4, levels
under 4 x 4 texels 12; measured 3.50 at worst on the 2017 PC and the Xbox files, since the DXT1 encoder also tries
the 3-colour mode the game's own files use: 9.69 before, and st12 / st22 b_tu_c_14s_0 level 7 failed). Also checks the
lower-levels image layout (texlevels.mip_atlas / levels_from_atlas) gives every level back.

python tests/texlevels_test.py <Map folder> [...]
"""
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'addon', 'phantom_dust_stage'))
from pdstage import alr, texlevels as tl  # noqa: E402

fails, n, worst = 0, 0, 0.0
for d in sys.argv[1:]:
    for f in sorted(glob.glob(os.path.join(d, 'st*.alr'))):
        b = open(f, 'rb').read()
        ro = alr.header(b)['resource_offset']
        for t in alr.textures(b):
            levels = tl.decode_texture(b, t, ro)
            if levels is None:
                continue
            n += 1
            storage, swz = tl.storage_of(t['raw_format'])
            swz = swz and not t['npot']
            p = ro + t['offset']
            for k, lv in enumerate(levels):
                h, w = lv.shape[:2]
                size = tl.level_bytes(storage, w, h)
                enc = tl.encode_level(lv, storage, swz, punch=storage == 'dxt1' and bool((levels[0][..., 3] < 128).any()))
                if storage in tl.BPP:
                    if enc != b[p:p + size]:
                        print('FAIL bytes', os.path.basename(f), t['name'], storage, 'level', k)
                        fails += 1
                else:
                    back = tl.decode_level(enc, storage, w, h)
                    e = float(np.abs(back.astype(float) - lv.astype(float)).mean())
                    worst = max(worst, e)
                    # levels under 4 x 4 (2 x 2, 1 x 1: a few texels of one block) get a looser bound
                    if e > (4.0 if w * h >= 16 else 12.0):
                        print('FAIL dxt', os.path.basename(f), t['name'], storage, 'level', k, round(e, 2))
                        fails += 1
                p += size
            if tl.raw_format_byte(storage, swz) != t['raw_format']:
                print('FAIL format byte', os.path.basename(f), t['name'], hex(t['raw_format']))
                fails += 1
            if len(levels) > 1:
                aw, ah, px = tl.mip_atlas(levels[1:])
                back = tl.levels_from_atlas(px, aw, ah, t['width'], t['height'], t['mips'])
                if back is None or any((x != y).any() for x, y in zip(back, levels[1:])):
                    print('FAIL atlas', os.path.basename(f), t['name'])
                    fails += 1
print('%d textures, %d failures, worst DXT re-encode error %.2f' % (n, fails, worst))
sys.exit(1 if fails else 0)
