"""Import a map's placed objects (props, breakables, jump pads, stairs...) and effects into the add-on's layout.

  Objects                       role Objects
    Collapsing Floor            one collection per behaviour + settings, named after the behaviour
      st03_bridgeA              one mesh per game object type (its intact model); every placement is a linked
      st03_bridgeA.001          duplicate of it
        collider_st03_bridgeA   parts parented to the first placement, in the object's own space, named by
        break_st03_bridgeA 1    what they do (the export reads the prefix):
          ...sub                  collider_ / collider_broken_ / collider_debris_  collision per state
        stay_st03_bridgeA 8       break_  broken piece that falls as physics debris
        debris_st03_bridgeA       stay_   broken piece that stays where it is
                                  debris_ the debris model
                                  a piece's own children (its shadow, extra detail) move with it
  Effects                       role Effects
    Steam, Sound emitter...     one collection per effect kind; every empty keeps the game's own entry
                                (pd_effect_raw), exported back with its new position, turn and scale

What the add-on can't write back is dropped on export: object animations (Spiral Highway's bridges, Storm
Refinery's container) and placements of other stage variants (only one variant is imported). The objects' own
effects (dust when they break) are kept and written back when exporting over the same map.
"""
import struct
import tempfile
from collections import Counter

import bpy
from mathutils import Matrix

from ._lib import alr, alr_build, anim_build, dat, effects_build, objects_build
from . import convert as cv
from . import surfaces
from . import visuals as vis

NONE = 0xFFFFFFFF
PRESET_OF = {(v[0], v[1]): k for k, v in objects_build.PRESETS.items() if v[0] is not None}


def _title(preset, cat, typ):
    if preset == 'GAME':
        return 'Game Type %d-%d' % (cat, typ)
    return objects_build.LABELS.get(preset, preset.replace('_', ' ').title())


def _collider_tris(b, off):
    """An object's own collision chain: [(v0, v1, v2, surface)] in its local game space."""
    recs, vlists = dat.collision(b, base=off)
    out = []
    for r in recs:
        if r.kind != dat.KIND_MESH or r.vlist is None or r.vlist >= len(vlists):
            continue
        vs = vlists[r.vlist].verts
        for a, bb, c, _attr, _n in r.tris:
            out.append((vs[a], vs[bb], vs[c], r.type))
    return out


def _tris_mesh(name, tris, scale):
    verts, index, faces = [], {}, []
    for t in tris:
        f = []
        for v in t[:3]:
            k = tuple(round(x, 4) for x in v)
            if k not in index:
                index[k] = len(verts)
                verts.append(cv.to_blender(v, scale))
            f.append(index[k])
        if len(set(f)) == 3:
            faces.append(cv.flip_winding(f))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    me.update()
    return me


def _root_records(b, h, root):
    if root is None or root == NONE or root >= len(h['roots']):
        return []
    return alr.meshes(b, h['roots'][root])


def _node0(records):
    nodes = records[0]['nodes'] if records else []
    return nodes[0]['values'] if nodes and 'values' in nodes[0] else (0.0, 0.0, 0.0, 0.0)


STAY_MARKERS = (alr_build.STAY_MARKER, 0xC3500000)    # node +0x2C: the game leaves this piece in place

# Name prefixes of an object's parts (longest first). The export reads these; pd_part is the fallback.
PREFIXES = (('collider_broken_', 'collider_broken'), ('collider_debris_', 'collider_debris'),
            ('collider_', 'collider'), ('break_', 'broken'), ('stay_', 'broken'), ('debris_', 'debris'))


def part_kind(ob):
    n = ob.name.lower()
    for pre, kind in PREFIXES:
        if n.startswith(pre):
            return kind
    return ob.get('pd_part')


def _effect_block(b, off):
    """An object's own effect table (EF00, u16 count, u16 size, entries) as raw bytes."""
    if off == NONE or off + 8 > len(b) or b[off:off + 4] != b'EF00':
        return None
    size = struct.unpack_from('<H', b, off + 6)[0]
    return bytes(b[off:off + 8 + size])


def _anim_block(b, off):
    """An object's own animation (a chain of node blocks, pdstage/anim_build.py) as raw bytes."""
    if off == NONE or off + 8 > len(b):
        return None
    n = anim_build.block_length(b, off)
    return bytes(b[off:off + n]) if n > 8 else None


def _pieces(records):
    """A broken model's pieces: {top node: {node: [records]}}. A piece is a child of the root node; its own
    children (shadow mesh, extra detail) belong to it and move with it."""
    nodes = records[0]['nodes'] if records else []

    def top(i):
        seen = 0
        while i < len(nodes) and nodes[i]['parent'] not in (None, 0) and seen < 64:
            i, seen = nodes[i]['parent'], seen + 1
        return i
    out = {}
    for m in records:
        out.setdefault(top(m['node']), {}).setdefault(m['node'], []).append(m)
    for i, n in enumerate(nodes):                    # pieces without a mesh of their own still count
        if n['parent'] == 0 and i not in out:
            out[i] = {}
    return out, nodes


def _part(name, me, kind, parent, coll, hidden):
    ob = bpy.data.objects.new(name, me)
    ob['pd_part'] = kind
    ob.parent = parent
    ob.hide_render = True
    coll.objects.link(ob)
    if kind.startswith('collider'):
        ob.display_type = 'WIRE'
    if hidden:                                      # broken pieces / debris overlap the model: hidden (eye icon)
        try:
            ob.hide_set(True)
        except RuntimeError:
            pass
    return ob


def import_objects(context, b_dat, b_alr, parent, scale, stage, variant=0):
    names, table, places = objects_build.read_objects(b_dat)
    if not places:
        return 'no objects'
    slots = sorted({p['slot'] for p in places})
    slot = variant if variant in slots else 0 if 0 in slots else slots[0]   # slot 2 = the map's second layout
    places = [p for p in places if p['slot'] == slot]
    h = alr.header(b_alr)
    texs = alr.textures(b_alr)

    root = bpy.data.collections.new('Objects')
    parent.children.link(root)
    root.pd_role = 'OBJECTS'

    by_object = {}
    for p in places:
        by_object.setdefault(p['object'], []).append(p)

    groups, report_parts = {}, Counter()
    with tempfile.TemporaryDirectory() as tmp:
        cache = {}
        image_of = lambda t: vis._image(b_alr, texs[t], cache, tmp)
        for oid in sorted(by_object):
            ps = by_object[oid]
            if not 0 <= oid < len(table):
                continue
            entry = table[oid]
            name = (names[oid] if oid < len(names) else '').strip('_') or 'object_%d' % oid
            cat, typ = ps[0]['category'], ps[0]['type']
            preset = PRESET_OF.get((cat, typ), 'GAME')
            intact = _root_records(b_alr, h, entry[0])
            broken = _root_records(b_alr, h, entry[1])
            debris = _root_records(b_alr, h, entry[2])
            hits = max(1, int(round(_node0(intact)[2])))
            damage = int(round(_node0(debris or intact)[1]))     # on the debris root, else the intact root
            stays = bool(debris) and _node0(debris)[0] == 0
            power = ps[0]['extra'][0] if preset == 'JUMP_PAD' else 0
            key = (preset, cat, typ, hits, damage, stays, power)
            fresh = key not in groups
            if fresh:
                tc = bpy.data.collections.new(_title(preset, cat, typ) + (' dmg:%d' % damage if damage else ''))
                root.children.link(tc)
                tc.pd_preset = preset
                tc.pd_category, tc.pd_type = cat, typ
                tc.pd_hits, tc.pd_damage, tc.pd_debris_stays = hits, damage, stays
                if preset == 'JUMP_PAD':
                    tc.pd_jump_power = max(1, power)
                groups[key] = tc
            tc = groups[key]

            cols = [_collider_tris(b_dat, entry[6 + k]) if entry[6 + k] != NONE else [] for k in range(3)]
            col = cols[0]
            me = vis.build_mesh(name, b_alr, h, texs, intact, scale, image_of, stage)
            no_model = me is None
            if no_model:                                  # e.g. jump pads: only the trigger collider
                me = _tris_mesh(name, col, scale) if col else bpy.data.meshes.new(name)
            first = None
            for p in ps:
                ob = bpy.data.objects.new(name, me)
                if no_model:
                    ob['pd_no_model'] = True
                    ob.display_type = 'WIRE'
                ob.location = cv.to_blender(p['pos'], scale)
                ob.rotation_euler = Matrix(cv.rot_to_blender(p['rot'])).to_euler('XYZ')   # full rotation
                if preset != 'JUMP_PAD' and any(p['extra']):
                    ob['pd_extra'] = list(p['extra'])
                ob.hide_render = True
                tc.objects.link(ob)
                first = first or ob
            # what the add-on has no setting for, kept on the first placement and written back on export
            first['pd_root_values'] = [list(_node0(r)) for r in (intact, broken, debris)]
            anims = [_anim_block(b_dat, entry[3 + k]) for k in range(3)]
            if any(anims):                                # moving objects (containers, iron roads): kept as is
                first['pd_object_anims'] = [x.hex() if x else '' for x in anims]
                report_parts['animations'] += 1
            snd_off = struct.unpack_from('<I', b_dat, 0xF8)[0]
            if snd_off != 0xFFFFFFFF and snd_off + (oid + 1) * 16 <= len(b_dat):
                first['pd_object_sounds'] = list(struct.unpack_from('<8H', b_dat, snd_off + oid * 16))
            fx = [_effect_block(b_dat, entry[9 + k]) for k in range(3)]
            if any(fx):
                first['pd_object_effects'] = [x.hex() if x else '' for x in fx]
                first['pd_object_effects_map'] = stage or ''
                report_parts['effect tables'] += 1
            for k, (pre, label) in enumerate((('collider_', 'colliders'), ('collider_broken_', 'broken colliders'),
                                              ('collider_debris_', 'debris colliders'))):
                if not cols[k] or (k == 0 and no_model):
                    continue
                st = Counter(t[3] for t in cols[k]).most_common(1)[0][0]
                c = _part(pre + name, _tris_mesh(pre + name, cols[k], scale), pre.rstrip('_'), first, tc, k > 0)
                c.pd_surface = '%02X' % st
                report_parts[label] += 1
            if broken:
                pieces, nodes = _pieces(broken)
                vals = {top: int(round(nodes[top]['values'][0])) if top < len(nodes) else 0 for top in pieces}
                tc.pd_pieces_hurt = (tc.pd_pieces_hurt and not fresh) or any(vals.values())
                for k, top in enumerate(sorted(pieces), 1):
                    node = nodes[top] if top < len(nodes) else {}
                    stay = node.get('marker') in STAY_MARKERS
                    pname = '%s%s %d' % ('stay_' if stay else 'break_', name, k)
                    own = pieces[top].get(top, [])
                    pm = (vis.build_mesh(pname, b_alr, h, texs, own, scale, image_of, stage) if own else None) \
                        or bpy.data.meshes.new(pname)
                    piece = _part(pname, pm, 'broken', first, tc, True)
                    piece['pd_piece_value'] = vals[top]      # the game's own number, kept for the export
                    for j, sub in enumerate(sorted(n for n in pieces[top] if n != top), 1):
                        sm = vis.build_mesh('%s sub %d' % (pname, j), b_alr, h, texs, pieces[top][sub], scale,
                                            image_of, stage)
                        if sm is not None:
                            _part(sm.name, sm, 'sub', piece, tc, True)
                    report_parts['stay pieces' if stay else 'break pieces'] += 1
            if debris:
                dm = vis.build_mesh('debris_' + name, b_alr, h, texs, debris, scale, image_of, stage)
                if dm is not None:
                    _part(dm.name, dm, 'debris', first, tc, True)
                    report_parts['debris models'] += 1
    text = '%d objects (%d types in %d collections' % (len(places), len(by_object), len(groups))
    text += ''.join(', %d %s' % (n, k) for k, n in sorted(report_parts.items())) + ')'
    if len(slots) > 1:
        text += '; variant %d of %d imported' % (slots.index(slot) + 1, len(slots))
    return text


def import_effects(context, b_dat, parent, scale, stage=None):
    es = dat.effects(b_dat)
    if not es:
        return 'no effects'
    root = bpy.data.collections.new('Effects')
    parent.children.link(root)
    root.pd_role = 'EFFECTS'
    colls = {}
    for e in es:
        raw = bytes(b_dat[e['offset']:e['offset'] + effects_build.ENTRY])
        kind = raw[0]
        label = effects_build.KINDS.get(kind, 'kind %d' % kind).split(' (')[0].capitalize()
        if label not in colls:
            c = bpy.data.collections.new(label)
            root.children.link(c)
            c.pd_effect = 'GAME'
            colls[label] = c
        rx, ry, rz = struct.unpack_from('<3f', raw, 0x10)
        ob = bpy.data.objects.new('%s %d' % (label, kind), None)
        ob.empty_display_type = 'SPHERE' if kind == 20 else 'ARROWS'
        ob.empty_display_size = 10 * scale
        ob.location = cv.to_blender(e['pos'], scale)
        ob.rotation_euler = (0.0, 0.0, cv.yaw_to_blender(ry))
        ob['pd_effect_raw'] = raw.hex()
        ob['pd_effect_map'] = stage or ''            # sounds and effect models only work in this map
        colls[label].objects.link(ob)
    return '%d effects in %d kinds' % (len(es), len(colls))
