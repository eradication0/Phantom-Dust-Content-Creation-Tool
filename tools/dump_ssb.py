"""Dump a stage's map script (SSB at .dat header 0xD0): functions, strings and the instruction stream, with
pushed numbers shown as floats.

  python tools/dump_ssb.py <stNN.dat> [--raw]

SSB layout (Phantom Dust wiki / Esper-RE ssb.h): u32 header size (0x20), u32 function table offset,
u32 string pool offset (twice), u32 0, u16, u16, u32, u32; then 32-bit instruction words; function table
entries are (2 x u32 base-40 name, u32 offset); strings are NUL-terminated.
"""
import os, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from pdstage import alr

path = sys.argv[1]
b = open(path, 'rb').read()
start, end = struct.unpack_from('<I', b, 0xD0)[0], struct.unpack_from('<I', b, 0xFC)[0]
s = b[start:end]
hsize, ftab, spool, spool2, _pad, m1, m2, unk, _p2 = struct.unpack_from('<5IHHII', s, 0)
print('%s: script %#x..%#x (%d bytes), function table %#x, strings %#x, flags %04x %04x %08x'
      % (os.path.basename(path), start, end, len(s), ftab, spool, m1, m2, unk))
funcs = []
for o in range(ftab, spool, 12):
    t1, t2, off = struct.unpack_from('<3I', s, o)
    funcs.append((off, alr.decode_text(t1, t2)))
print('functions:', ', '.join('%s@%#x' % (n, o) for o, n in funcs))
strings = [x.decode('ascii', 'replace') for x in s[spool:].split(b'\0') if x]
print('strings:', strings[:40])
words = struct.unpack_from('<%dI' % ((ftab - hsize) // 4), s, hsize)
starts = {o: n for o, n in funcs}
out = []
stack = []
i = 0
while i < len(words):
    pos = hsize + i * 4
    if pos in starts:
        out.append('\n[%s]' % starts[pos])
    w = words[i]
    op = w & 0xFFFF
    if '--raw' in sys.argv:
        out.append('%04x: %08x' % (pos, w))
        i += 1
        continue
    if op == 0x000F and i + 1 < len(words):
        f = struct.unpack('<f', struct.pack('<I', words[i + 1]))[0]
        stack.append('%.4g' % f if f == 0 or abs(f) > 1e-30 else '#%08x' % words[i + 1])
        i += 2
        continue
    if op == 0x000E:
        stack.append(str(w >> 16))
        i += 1
        continue
    if op & 0xFF == 0x01:
        n = (w >> 8) & 0xFF
        args, stack[:] = stack[len(stack) - n:], stack[:len(stack) - n]
        out.append('call %04x(%s)' % (w >> 16, ', '.join(args)))
        i += 1
        continue
    out.append('%08x' % w)
    i += 1
print('\n'.join(out))
