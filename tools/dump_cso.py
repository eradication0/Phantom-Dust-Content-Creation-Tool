"""Print a game shader (.cso, DirectX bytecode, shader model 4): its constant names and a disassembly.

  python tools/dump_cso.py <game folder>/SD_vs.cso <game folder>/SD_ps.cso

The game's shaders keep their constant names (cSPECULAR, cDL_COL, ...), which is how the stage material
settings were read (FORMATS.md, "Stage materials"). Plain Python, no Microsoft tools needed.
"""
import struct
import sys

OPS = ("add and break breakc call callc case continue continuec cut default deriv_rtx deriv_rty discard div dp2 dp3 "
       "dp4 else emit emitthencut endif endloop endswitch eq exp frc ftoi ftou ge iadd if ieq ige ilt imad imax imin "
       "imul ine ineg ishl ishr itof label ld ld_ms log loop lt mad min max customdata mov movc mul ne nop not or "
       "resinfo ret retc round_ne round_ni round_pi round_z rsq sample sample_c sample_c_lz sample_l sample_d sample_b "
       "sqrt switch sincos udiv ult uge umul umad umax umin ushr utof xor dcl_resource dcl_constantbuffer dcl_sampler "
       "dcl_index_range dcl_gs_out_topo dcl_gs_in_prim dcl_max_out dcl_input dcl_input_sgv dcl_input_siv dcl_input_ps "
       "dcl_input_ps_sgv dcl_input_ps_siv dcl_output dcl_output_sgv dcl_output_siv dcl_temps dcl_indexable_temp "
       "dcl_global_flags").split()
TYPES = {0: 'r', 1: 'v', 2: 'o', 3: 'x', 4: 'l', 6: 's', 7: 't', 8: 'cb', 9: 'icb', 0xC: 'oDepth'}


def cstr(b, o):
    return b[o:b.index(b'\0', o)].decode('latin1')


def chunks(b):
    n = struct.unpack_from('<I', b, 0x1C)[0]
    out = {}
    for i in range(n):
        off = struct.unpack_from('<I', b, 0x20 + 4 * i)[0]
        tag = b[off:off + 4].decode()
        size = struct.unpack_from('<I', b, off + 4)[0]
        out[tag] = b[off + 8:off + 8 + size]
    return out


def rdef(r):
    cbc, cbo, bc, bo = struct.unpack_from('<IIII', r, 0)
    major = r[0x11]
    vsz = 40 if major >= 5 else 24
    cbs, binds = [], []
    for i in range(bc):
        no, typ, ret, dim, ns, bp, cnt, fl = struct.unpack_from('<8I', r, bo + 32 * i)
        binds.append((cstr(r, no), typ, bp))
    for i in range(cbc):
        no, vc, vo, size, fl, typ = struct.unpack_from('<6I', r, cbo + 24 * i)
        vars_ = []
        for k in range(vc):
            vn, start, vs, vf, to, dv = struct.unpack_from('<6I', r, vo + vsz * k)
            default = None
            if dv:
                default = struct.unpack_from('<%df' % (vs // 4), r, dv)
            vars_.append((cstr(r, vn), start, vs, vf, default))
        cbs.append((cstr(r, no), size, vars_))
    return cbs, binds


def operand(t, i, names):
    tok = t[i]; i += 1
    ncomp = tok & 3
    sel = (tok >> 2) & 3
    otype = (tok >> 12) & 0xFF
    idim = (tok >> 20) & 3
    reps = [(tok >> 22) & 7, (tok >> 25) & 7, (tok >> 28) & 7]
    mod = ''
    if tok >> 31:
        ext = t[i]; i += 1
        m = (ext >> 6) & 0xFF
        mod = {1: '-', 2: '|', 3: '-|'}.get(m, '')
    if otype == 4:   # immediate
        n = 4 if ncomp == 2 else 1
        vals = t[i:i + n]; i += n
        fl = [struct.unpack('<f', struct.pack('<I', v))[0] for v in vals]
        s = 'l(%s)' % ', '.join(('%g' % f) if abs(f) < 1e7 and (v & 0x7F800000) else str(v) for f, v in zip(fl, vals))
        return s, i
    name = TYPES.get(otype, 'T%d' % otype)
    idx = []
    for d in range(idim):
        rep = reps[d]
        if rep == 0:
            idx.append(str(t[i])); i += 1
        elif rep == 2:
            sub, i = operand(t, i, names); idx.append(sub)
        elif rep == 3:
            v = t[i]; i += 1
            sub, i = operand(t, i, names); idx.append('%s+%d' % (sub, v))
        else:
            idx.append('?'); i += 1
    if name in ('cb',) and len(idx) == 2:
        s = 'cb%s[%s]' % (idx[0], idx[1])
        nm = names.get((int(idx[0]), int(idx[1]))) if idx[1].isdigit() else None
        if nm:
            s += '{%s}' % nm
    else:
        s = name + ''.join(idx[:1]) + ''.join('[%s]' % x for x in idx[1:])
    comp = ''
    if ncomp == 2:
        if sel == 0:
            m = (tok >> 4) & 0xF
            comp = '.' + ''.join('xyzw'[k] for k in range(4) if m >> k & 1) if m != 0xF else ''
        elif sel == 1:
            sw = (tok >> 4) & 0xFF
            comp = '.' + ''.join('xyzw'[(sw >> (2 * k)) & 3] for k in range(4))
        else:
            comp = '.' + 'xyzw'[(tok >> 4) & 3]
    s = s + comp
    if mod == '-':
        s = '-' + s
    elif mod == '|':
        s = '|%s|' % s
    elif mod == '-|':
        s = '-|%s|' % s
    return s, i


def disasm(sh, names):
    t = struct.unpack('<%dI' % (len(sh) // 4), sh)
    i = 2
    lines = []
    while i < len(t):
        tok = t[i]
        op = tok & 0x7FF
        if op == 53:
            ln = t[i + 1]
            lines.append('customdata (%d dwords)' % ln)
            i += ln
            continue
        ln = (tok >> 24) & 0x7F
        end = i + ln
        name = OPS[op] if op < len(OPS) else 'op%d' % op
        if tok & (1 << 13) and op < 88:
            name += '_sat'
        if op in (31, 3, 5, 13, 63):
            name += '_nz' if tok & (1 << 18) else '_z'
        j = i + 1
        ext = tok >> 31
        while ext:
            ext = t[j] >> 31
            j += 1
        if op >= 88 and op not in (88, 89, 90, 95, 96, 97, 98, 99, 100, 101, 102, 103):
            lines.append('%s %s' % (name, ' '.join(str(x) for x in t[j:end])))
        else:
            ops = []
            try:
                while j < end:
                    s, j = operand(t, j, names)
                    ops.append(s)
                    if op in (89, 88, 90, 95, 96, 97, 98, 99, 100, 101, 102, 103):
                        ops += [str(x) for x in t[j:end]]
                        break
            except Exception as e:
                ops.append('<err %s>' % e)
            lines.append('%s %s' % (name, ', '.join(ops)))
        i = end if ln else i + 1
    return lines


def main(paths):
    for p in paths:
        b = open(p, 'rb').read()
        c = chunks(b)
        cbs, binds = rdef(c['RDEF'])
        print('=' * 20, p.split('/')[-1])
        print('bindings:', binds)
        names = {}
        slot_of = {n: bp for n, typ, bp in binds if typ == 0}
        for cname, size, vars_ in cbs:
            slot = slot_of.get(cname, 0)
            print('cbuffer %s (cb%d, %d bytes)' % (cname, slot, size))
            for vn, start, vs, vf, d in vars_:
                used = 'used' if vf & 2 else '    '
                print('   %-14s cb%d[%d]%s size %d %s %s' % (vn, slot, start // 16, '.' + 'xyzw'[(start % 16) // 4],
                                                         vs, used, d if d else ''))
                for k in range(0, max(vs, 4), 16):
                    names.setdefault((slot, (start + k) // 16), vn)
        sh = c.get('SHDR') or c.get('SHEX')
        for ln in disasm(sh, names):
            print('  ', ln)


if __name__ == '__main__':
    main(sys.argv[1:])
