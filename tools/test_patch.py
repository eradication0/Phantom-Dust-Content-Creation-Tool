"""The in-game test edits used to confirm the formats. Writes a NEW file; never edits in place.

  python tools/test_patch.py orbs-stack       <in.dat> <out.dat>         every orb on orb 1
  python tools/test_patch.py spawns-up        <in.dat> <out.dat> [dy]    spawns raised (default 250)
  python tools/test_patch.py spawns-flip      <in.dat> <out.dat>         spawns turned 180 degrees
  python tools/test_patch.py collision-shift  <in.dat> <out.dat> [dy]    all collision moved (default -15)
  python tools/test_patch.py collision-append <in.dat> <out.dat> [dy]    copy collision to the end of the
        file, move only the copy (default -15), repoint header 0x94 and the file size at 0x138

To try one in game: back up the map's stNN.dat, copy the output over it, play that map,
then restore the backup.
"""
import math, os, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from pdstage import dat

if len(sys.argv) < 4:
    sys.exit(__doc__)
cmd, src, dst = sys.argv[1:4]
arg = float(sys.argv[4]) if len(sys.argv) > 4 else None
if os.path.abspath(src) == os.path.abspath(dst):
    sys.exit('refusing to overwrite the input; write to a new file')
b = bytearray(open(src, 'rb').read())

if cmd in ('orbs-stack', 'spawns-up', 'spawns-flip'):
    n = 0
    for layout in dat.spawn_layouts(b):
        for s in layout:
            if cmd == 'orbs-stack':
                s.orbs = [s.orbs[0]] * 3
            elif cmd == 'spawns-up':
                s.pos = (s.pos[0], s.pos[1] + (250.0 if arg is None else arg), s.pos[2])
            else:
                s.yaw = math.atan2(math.sin(s.yaw + math.pi), math.cos(s.yaw + math.pi))
            dat.write_spawn(b, s)
            n += 1
    print(cmd, 'changed', n, 'spawn entries')
elif cmd in ('collision-shift', 'collision-append'):
    dy = -15.0 if arg is None else arg
    recs, _ = dat.collision(b)
    if cmd == 'collision-append':
        start = recs[0].offset
        end = recs[-1].offset + recs[-1].size + 0xC + 1      # include the 0xFF end marker
        assert b[end - 1] == 0xFF
        b += b'\0' * (-len(b) % 4)
        new = len(b)
        b += b[start:end]
        struct.pack_into('<I', b, dat.H_COLLISION, new)
        struct.pack_into('<I', b, dat.H_FILE_SIZE, len(b))
        print('collision copied from %#x-%#x to %#x; file size %#x' % (start, end, new, len(b)))
        recs, _ = dat.collision(b)                            # now the copy
    for r in recs:
        o = r.offset
        if r.kind == dat.KIND_VERTS:
            for i in range(len(r.verts)):
                a = o + 0xC + i * 12 + 4
                struct.pack_into('<f', b, a, struct.unpack_from('<f', b, a)[0] + dy)
        elif r.kind in (1, dat.KIND_MESH):
            for a in (o + 0x10, o + 0x20, o + 0x2C):   # centre y, bbox min y, bbox max y
                struct.pack_into('<f', b, a, struct.unpack_from('<f', b, a)[0] + dy)
    print(cmd, 'moved', len(recs), 'records by', dy)
else:
    sys.exit(__doc__)
open(dst, 'wb').write(b)
print('wrote', dst)
