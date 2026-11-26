"""Independent structure check of a stage .dat / .alr pair (plain Python, no Blender, no add-on code).

  python tools/check_stage.py <original.dat> <original.alr> <exported.dat> <exported.alr>

Written for this repository from separate notes on the game's file formats (stage tables, stage collision, ALR
models), as a second opinion next to pdstage's readers. Prints PROBLEMS (the
exported pair is not valid: header words out of range, wrong section tags, placements or object definitions out of
range, broken collision chunks, EF00 / CP00 / MD00 sizes, ALR header / resource buffer / chunk chains, materials,
vertex buffers and draws out of range, a vertex buffer whose stride and mask are not its format's) and DIFFERENCES
(content compared with the original: names, placements, object definitions, collision triangles, effects, start
points, MD00, model roots, per-root draws / triangles / shaders, texture names). Every file of the 2017 PC game
checked against itself gives 0 and 0.
"""
import hashlib
import struct
import sys
from collections import Counter

NONE = 0xFFFFFFFF
FORMAT_LAYOUTS = {1: (24, 0xCF), 3: (32, 0x30CF), 5: (28, 0x64F), 7: (16, 0xF), 8: (20, 0x8F), 9: (20, 0xC7),
                  11: (16, 0x87), 16: (12, 0x7), 17: (24, 0x647), 21: (24, 0x1000C7), 22: (28, 0x3000C7),
                  23: (32, 0x7000C7), 24: (16, 0x47), 26: (40, 0x78000CF), 29: (36, 0x1030CF), 30: (28, 0x100CF),
                  31: (32, 0x10304F), 33: (32, 0x3000CF), 37: (28, 0x304F)}
B40 = ' 0123456789abcdefghijklmnopqrstuvwxyz_-' + '?'


def u32(b, o):
    return struct.unpack_from('<I', b, o)[0]


def b40(w):
    if w == NONE:
        return ''
    s = ''
    for _ in range(6):
        s = B40[w % 40] + s
        w //= 40
    return s.strip()


# ------------------------------------------------------------------ dat

class Dat:
    def __init__(self, b, probs):
        self.b, self.p = b, probs
        self.short = b[:4] == b'ST00' and u32(b, 4) == 0x28
        if b[:4] != b'ST00':
            probs.append('dat: magic %r' % b[:4]) if not b[:2] == b'AR' else None
            self.kind = 'area'
            return
        self.kind = 'short' if self.short else 'stage'
        if self.short:
            if u32(b, 0x24) != len(b):
                probs.append('dat: short header file size %d != %d' % (u32(b, 0x24), len(b)))
            return
        if u32(b, 0x138) != len(b):
            probs.append('dat: header file size 0x%X != 0x%X' % (u32(b, 0x138), len(b)))
        for w in list(range(0x04, 0x30, 4)) + [0x5C] + list(range(0x64, 0x138, 4)):
            v = u32(b, w)
            if v != NONE and not (0x13C <= v <= len(b)):
                probs.append('dat: header word 0x%X = 0x%X out of range' % (w, v))

    def ok(self, o, n=0):
        return o != NONE and 0 <= o and o + n <= len(self.b)

    def tag_at(self, o, tag, before=False):
        at = o - 4 if before else o
        if not self.ok(at, 4) or self.b[at:at + 4] != tag:
            self.p.append('dat: expected %s %s 0x%X, found %r' % (tag.decode(), 'before' if before else 'at', o,
                                                                  self.b[at:at + 4] if self.ok(at, 4) else None))
            return False
        return True

    def names(self):
        o, n = u32(self.b, 0x5C), u32(self.b, 0x60)
        if o == NONE:
            return []
        self.tag_at(o, b'NM00', True)
        out, p = [], o
        for _ in range(n):
            e = self.b.find(b'\0', p)
            if e < 0:
                self.p.append('dat: NM00 runs off the file')
                break
            out.append(self.b[p:e].decode('latin1'))
            p = e + 1
        return out

    def placements(self):
        out = []
        n_obj = u32(self.b, 0x60)
        for k in range(11):
            o, n = u32(self.b, 4 + 4 * k), u32(self.b, 0x30 + 4 * k)
            if o == NONE or n == NONE:
                continue
            if not self.ok(o, 0x24 * n):
                self.p.append('dat: placement list %d (%d entries) runs off the file' % (k, n))
                continue
            for i in range(n):
                e = o + 0x24 * i
                obj, tbl, cls, ph, arg, res = struct.unpack_from('<i4BI', self.b, e)
                pos = struct.unpack_from('<3f', self.b, e + 0xC)
                rot = struct.unpack_from('<3f', self.b, e + 0x18)
                if not 0 <= (obj & 0xFFFF) < n_obj:
                    self.p.append('dat: placement %d/%d object %d >= %d definitions' % (k, i, obj, n_obj))
                out.append((k, obj, tbl, cls, ph, arg, tuple(round(x, 3) for x in pos), tuple(round(x, 4) for x in rot)))
        return out

    def collision(self, base, what):
        recs, pools, o = [], [], base
        while True:
            if not self.ok(o, 1):
                self.p.append('dat: %s collision runs off the file at 0x%X' % (what, o))
                return [], []
            if self.b[o] == 0xFF:
                break
            kind, shape, flags, part, size, _r = struct.unpack_from('<4B2I', self.b, o)
            if not self.ok(o, 12 + size):
                self.p.append('dat: %s collision chunk at 0x%X size %d off the file' % (what, o, size))
                return [], []
            if shape == 8:
                pools.append([struct.unpack_from('<3f', self.b, o + 12 + 12 * i) for i in range(size // 12)])
            elif shape == 3:
                n, _u36, pool = struct.unpack_from('<HHI', self.b, o + 0x34)
                if size != 0x30 + 20 * n:
                    self.p.append('dat: %s collision mesh at 0x%X size %d != 0x30 + 20 * %d' % (what, o, size, n))
                tris = [struct.unpack_from('<4H3f', self.b, o + 0x3C + 20 * i) for i in range(n)]
                recs.append((kind, flags, part, pool, tris))
            else:
                self.p.append('dat: %s collision chunk at 0x%X has shape %d' % (what, o, shape))
            o += 12 + size
        out = []
        for kind, flags, part, pool, tris in recs:
            if pool >= len(pools):
                self.p.append('dat: %s collision mesh uses pool %d of %d' % (what, pool, len(pools)))
                continue
            vs = pools[pool]
            for t in tris:
                if max(t[:3]) >= len(vs):
                    self.p.append('dat: %s collision triangle index %d >= %d' % (what, max(t[:3]), len(vs)))
                    break
                out.append((kind, tuple(sorted(tuple(round(c, 2) for c in vs[i]) for i in t[:3]))))
        return out, pools

    def object_defs(self, n_roots):
        o, n = u32(self.b, 0x90), u32(self.b, 0x60)
        if o == NONE:
            return []
        self.tag_at(o, b'OB00', True)
        out = []
        for i in range(n):
            e = o + 56 * i
            if not self.ok(e, 56):
                self.p.append('dat: object definition %d off the file' % i)
                break
            w = struct.unpack_from('<12i', self.b, e)
            for m in w[0:3]:
                if m != -1 and n_roots is not None and not 0 <= m < n_roots:
                    self.p.append('dat: object %d model %d not a root of the .alr (%d roots)' % (i, m, n_roots))
            for a in w[3:6]:
                if a != -1 and not self.ok(a, 8):
                    self.p.append('dat: object %d animation offset 0x%X off the file' % (i, a))
            cols = []
            for c in w[6:9]:
                if c != -1:
                    cols.append(len(self.collision(c, 'object %d' % i)[0]))
            for f in w[9:12]:
                if f != -1:
                    self.tag_at(f, b'EF00')
            out.append((w[0:3], tuple(cols)))
        return out

    def effects(self):
        o = u32(self.b, 0x98)
        if o == NONE:
            return []
        if not self.tag_at(o, b'EF00'):
            return []
        n, size = struct.unpack_from('<HH', self.b, o + 4)
        if size != 92 * n:
            self.p.append('dat: EF00 byte size %d != 92 * %d' % (size, n))
        return [self.b[o + 8 + 92 * i:o + 8 + 92 * (i + 1)] for i in range(n)]

    def start_groups(self):
        out = []
        for w in range(0xA4, 0xC0, 4):
            o = u32(self.b, w)
            if o == NONE:
                continue
            if not self.tag_at(o, b'CP00'):
                continue
            count, _z, size = struct.unpack_from('<BBH', self.b, o + 4)
            if size != 80 * count:
                self.p.append('dat: CP00 at 0x%X byte size %d != 80 * %d' % (o, size, count))
            g = []
            for i in range(count):
                e = o + 8 + 80 * i
                g.append(tuple(round(x, 3) for x in struct.unpack_from('<4f', self.b, e)) +
                         tuple(round(x, 3) for x in struct.unpack_from('<9f', self.b, e + 0x14)) +
                         struct.unpack_from('<I6I', self.b, e + 0x10)[:1] + struct.unpack_from('<6I', self.b, e + 0x38))
            out.append(tuple(g))
        return out

    def md00(self, n_roots, n_blobs):
        o = u32(self.b, 0xA0)
        if o == NONE:
            return None
        if not self.tag_at(o, b'MD00'):
            return None
        s0, s1, slots = struct.unpack_from('<3I', self.b, o + 4)
        p = o + 16 + s0 + s1
        pairs = []
        while self.ok(p, 8):
            m, blob = struct.unpack_from('<2i', self.b, p)
            if m == 0:
                break
            if m != -1 and n_roots is not None and not 0 <= m < n_roots:
                self.p.append('dat: MD00 pair %d model %d not a root (%d roots)' % (len(pairs), m, n_roots))
            if blob != -1 and n_blobs is not None and not 0 <= blob < n_blobs:
                self.p.append('dat: MD00 pair %d blob %d of %d' % (len(pairs), blob, n_blobs))
            pairs.append((m, blob))
            p += 8
        else:
            self.p.append('dat: MD00 pair list not ended')
        return slots, self.b[o + 16:o + 16 + s0 + s1], pairs

    def blobs(self):
        o = u32(self.b, 0xF4)
        if o == NONE:
            return None
        n, p = u32(self.b, o), o + 4
        out = []
        for _ in range(n):
            if not self.ok(p, 4):
                self.p.append('dat: blob list off the file')
                break
            ln = u32(self.b, p)
            out.append(hashlib.sha1(self.b[p + 4:p + 4 + ln]).hexdigest()[:12])
            p += 4 + ln
        return out

    def scripts(self):
        out = []
        for w in (0xD0, 0xD4, 0xD8):
            o = u32(self.b, w)
            out.append(None if o == NONE else hashlib.sha1(self.b[o:o + 64]).hexdigest()[:12])
        return out


def dat_summary(b, probs, n_roots):
    d = Dat(b, probs)
    if d.kind != 'stage':
        return dict(kind=d.kind)
    blobs = d.blobs()
    col, _ = d.collision(u32(b, 0x94), 'stage') if u32(b, 0x94) != NONE else ([], [])
    s = dict(kind='stage', names=d.names(), placements=Counter(d.placements()), objects=d.object_defs(n_roots),
             collision=Counter(col), effects=Counter(d.effects()), starts=d.start_groups(),
             md00=d.md00(n_roots, len(blobs) if blobs is not None else None), blobs=blobs)
    if u32(b, 0xF8) != NONE and not d.ok(u32(b, 0xF8), 16 * u32(b, 0x60)):
        probs.append('dat: object sound table off the file')
    return s


# ------------------------------------------------------------------ alr

def alr_summary(b, probs):
    if u32(b, 0) != 0x11:
        probs.append('alr: first chunk id %d' % u32(b, 0))
        return None
    hsize, ver, ro, nroot, rs = u32(b, 4), b[8], u32(b, 0xC), u32(b, 0x10) & 0xFFFF, u32(b, 0x14)
    if ver != 0x52:
        probs.append('alr: version 0x%X' % ver)
    if ro + rs != len(b):
        probs.append('alr: resource 0x%X + 0x%X != file size 0x%X' % (ro, rs, len(b)))
    if ro % 0x1000:
        probs.append('alr: resource offset 0x%X not 0x1000-aligned' % ro)
    rb = b[ro:]
    texs = []
    if u32(b, hsize) == 0x15:
        n = u32(b, hsize + 8) & 0xFFFF
        for i in range(n):
            e = hsize + 12 + 28 * i
            _c, off, _l, fmt, size, n0, n1 = struct.unpack_from('<7I', b, e)
            code, mips, lw, lh = (fmt >> 8) & 0xFF, (fmt >> 16) & 0xF, (fmt >> 20) & 0xF, (fmt >> 24) & 0xF
            if off >= rs and not (off == 0 and rs == 0):
                probs.append('alr: texture %d offset 0x%X past the resource buffer (0x%X)' % (i, off, rs))
            texs.append((b40(n0) + b40(n1), code, lw, lh, mips))
    roots = []
    for r in range(nroot):
        off = struct.unpack_from('<i', b, 0x20 + 4 * r)[0]
        if off <= 0:
            roots.append(None)
            continue
        mats, vbs, joints, draws, shaders = [], [], 0, 0, Counter()
        tris = 0
        o = off
        while True:
            if o + 8 > ro:
                probs.append('alr: root %d chain runs into the resource buffer' % r)
                break
            cid, size = struct.unpack_from('<Ii', b, o)
            if cid == 0:
                break
            if size < 8:
                probs.append('alr: root %d chunk 0x%X size %d' % (r, cid, size))
                break
            if cid == 0x01:
                n = struct.unpack_from('<H', b, o + 8)[0]
                mats = []
                for i in range(n):
                    e = o + 12 + 0x4C * i
                    sh = b40(u32(b, e)) + b40(u32(b, e + 4))
                    tx = struct.unpack_from('<4H', b, e + 0x18)
                    stages = struct.unpack_from('<H', b, e + 0x16)[0]
                    for s in range(4):
                        if (stages >> (4 * s)) & 0xF and tx[s] != 0xFFFF and tx[s] >= len(texs):
                            probs.append('alr: root %d material %d texture %d >= %d' % (r, i, tx[s], len(texs)))
                    mats.append(sh)
            elif cid == 0x03:
                joints = struct.unpack_from('<H', b, o + 8)[0]
            elif cid == 0x16:
                n = u32(b, o + 8)
                vbs = []
                for i in range(n):
                    e = o + 12 + 28 * i
                    fmt, stride, stride2 = b[e], b[e + 1], b[e + 2]
                    mask, count = u32(b, e + 4), u32(b, e + 8)
                    doff = u32(b, e + 0x14)
                    lay = FORMAT_LAYOUTS.get(fmt)
                    if lay is None:
                        probs.append('alr: root %d vertex buffer %d unknown format %d' % (r, i, fmt))
                    elif (stride, mask) != lay:
                        probs.append('alr: root %d vertex buffer %d format %d stride %d mask 0x%X (game: %d, 0x%X)'
                                     % (r, i, fmt, stride, mask, lay[0], lay[1]))
                    if stride != stride2:
                        probs.append('alr: root %d vertex buffer %d strides %d/%d' % (r, i, stride, stride2))
                    if doff + count * stride > rs:
                        probs.append('alr: root %d vertex buffer %d data 0x%X+%d*%d past the buffer 0x%X'
                                     % (r, i, doff, count, stride, rs))
                    vbs.append((count, fmt))
            elif cid == 0x02:
                mat, joint, vb, prim = struct.unpack_from('<4H', b, o + 8 + 0x38)
                vstart, vcount, icount = struct.unpack_from('<3I', b, o + 8 + 0x40)
                draws += 1
                if mat >= len(mats):
                    probs.append('alr: root %d draw at 0x%X material %d >= %d' % (r, o, mat, len(mats)))
                else:
                    shaders[mats[mat]] += 1
                if vb >= len(vbs):
                    probs.append('alr: root %d draw at 0x%X vertex buffer %d >= %d' % (r, o, vb, len(vbs)))
                elif icount:
                    idx = struct.unpack_from('<%dH' % icount, b, o + 8 + 0x60)
                    if max(idx) >= vbs[vb][0]:
                        probs.append('alr: root %d draw at 0x%X index %d >= %d vertices' % (r, o, max(idx), vbs[vb][0]))
                if joints and joint >= joints:
                    probs.append('alr: root %d draw at 0x%X joint %d >= %d' % (r, o, joint, joints))
                if prim not in (5, 6):
                    probs.append('alr: root %d draw at 0x%X primitive %d' % (r, o, prim))
                if icount:                       # non-degenerate triangles (strips carry degenerate joins)
                    idx = struct.unpack_from('<%dH' % icount, b, o + 8 + 0x60)
                    ts = [idx[k:k + 3] for k in range(0, icount - 2, 3)] if prim == 5 else \
                        [idx[k:k + 3] for k in range(icount - 2)]
                    tris += sum(1 for t in ts if len(set(t)) == 3)
            o += size
        roots.append((draws, tris, tuple(sorted(shaders.items()))))
    return dict(textures=texs, roots=roots, n_roots=nroot)


def compare(orig_dat, orig_alr, new_dat, new_alr):
    probs, diffs = [], []
    a_alr = alr_summary(orig_alr, [])
    n_alr = alr_summary(new_alr, probs) if new_alr is not None else a_alr
    a = dat_summary(orig_dat, [], a_alr['n_roots'] if a_alr else None)
    n = dat_summary(new_dat, probs, n_alr['n_roots'] if n_alr else None)
    for k in a:
        if a[k] != n.get(k):
            if isinstance(a[k], Counter):
                diffs.append('dat %s: %d -> %d entries (%d only in original, %d only in new)'
                             % (k, sum(a[k].values()), sum(n[k].values()), sum((a[k] - n[k]).values()),
                                sum((n[k] - a[k]).values())))
            elif isinstance(a[k], list):
                diffs.append('dat %s: %d -> %d entries, %d differ' % (k, len(a[k]), len(n[k] or []),
                                                                     sum(x != y for x, y in zip(a[k], n[k] or []))))
            else:
                diffs.append('dat %s differs' % k)
    if a_alr and n_alr:
        if a_alr['textures'] != n_alr['textures']:
            an, nn = Counter(a_alr['textures']), Counter(n_alr['textures'])
            diffs.append('alr textures: %d -> %d (%d only in original, %d only in new)'
                         % (len(a_alr['textures']), len(n_alr['textures']), sum((an - nn).values()), sum((nn - an).values())))
        for i, (x, y) in enumerate(zip(a_alr['roots'], n_alr['roots'])):
            if x != y:
                diffs.append('alr root %d: %s -> %s' % (i, x and x[:2], y and y[:2]))
        if a_alr['n_roots'] != n_alr['n_roots']:
            diffs.append('alr roots: %d -> %d' % (a_alr['n_roots'], n_alr['n_roots']))
    return probs, diffs


if __name__ == '__main__':
    r = lambda p: open(p, 'rb').read()
    probs, diffs = compare(r(sys.argv[1]), r(sys.argv[2]), r(sys.argv[3]), r(sys.argv[4]))
    print('PROBLEMS %d' % len(probs))
    for p in probs[:40]:
        print('  ' + p)
    print('DIFFERENCES %d' % len(diffs))
    for d in diffs[:60]:
        print('  ' + d)
