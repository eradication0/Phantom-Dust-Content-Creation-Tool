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

Object animations (Spiral Highway's iron roads, Storm Refinery's container) are Actions on the broken pieces
(stage_extras.py). The objects' own effects (dust when they break) are kept and written back when exporting over the
same map.
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
    verts, index, faces, seen = [], {}, [], set()
    for t in tris:
        f = []
        for v in t[:3]:
            k = tuple(round(x, 4) for x in v)
            if k not in index:
                index[k] = len(verts)
                verts.append(cv.to_blender(v, scale))
            f.append(index[k])
        if len(set(f)) == 3:
            if frozenset(f) in seen:
                # the same corners as an earlier triangle (st02's car: 74 repeated triangles and 2 back faces):
                # Blender would merge the two faces, so this one gets its own copies of the corners
                n0 = len(verts)
                verts.extend([verts[i] for i in f])
                f = [n0, n0 + 1, n0 + 2]
            seen.add(frozenset(f))
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
            ('collider_', 'collider'), ('break_', 'broken'), ('stay_', 'broken'), ('debris_', 'debris'),
            ('shadow_', 'shadow'))


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
    merged = {}
    for p in places:                 # the same placement in several lists: one object, with every list it is in
        key = (p['object'], p['category'], p['type'], tuple(p['extra']), tuple(p['pos']), tuple(p['rot']))
        if key in merged:
            merged[key]['slots'].append(p['slot'])
        else:
            merged[key] = dict(p, slots=[p['slot']])
    places = list(merged.values())
    h = alr.header(b_alr)
    texs = alr.textures(b_alr)

    root = bpy.data.collections.new('Objects')
    parent.children.link(root)
    root.pd_role = 'OBJECTS'

    by_object = {}
    for p in places:
        by_object.setdefault(p['object'], []).append(p)

    groups, report_parts, looks = {}, Counter(), {}
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
            # the export makes one definition per model inside a collection, with the colliders and pieces of the
            # placement that holds them: a definition with the same model as another one in the collection but
            # other colliders or pieces (st05 kanbanM1 / kanbanM2) goes to a collection of its own
            look = repr([(m['box'], m['indices']) for m in intact])
            parts_of = repr(([_collider_tris(b_dat, entry[6 + k]) if entry[6 + k] != NONE else [] for k in range(3)],
                             [(m['node'], m['box']) for m in broken], [(m['node'], m['box']) for m in debris]))
            seen_parts = looks.setdefault(key, {}).setdefault(look, [])
            if parts_of not in seen_parts:
                seen_parts.append(parts_of)
            if seen_parts.index(parts_of):
                key = key + (seen_parts.index(parts_of),)
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
            main_kind = Counter(t[3] for t in col).most_common(1)[0][0] if col else None
            if no_model:                                  # e.g. jump pads: only the trigger collider
                own = [t for t in col if t[3] == main_kind]  # its main surface kind; others: collider parts
                me = _tris_mesh(name, own, scale) if own else bpy.data.meshes.new(name)
            first = None
            snd_off = struct.unpack_from('<I', b_dat, 0xF8)[0]
            snd_row = struct.unpack_from('<8H', b_dat, snd_off + oid * 16)                 if snd_off != 0xFFFFFFFF and snd_off + (oid + 1) * 16 <= len(b_dat) else None
            for p in ps:
                ob = bpy.data.objects.new(name, me)
                if no_model:
                    ob['pd_no_model'] = True
                    ob.display_type = 'WIRE'
                ob.location = cv.to_blender(p['pos'], scale)
                ob.rotation_euler = Matrix(cv.rot_to_blender(p['rot'])).to_euler('XYZ')   # full rotation
                if preset != 'JUMP_PAD' and any(p['extra']):
                    ob['pd_extra'] = list(p['extra'])
                if (p['category'], p['type']) != (cat, typ):
                    # the behaviour class is the placement's own (+0x04 table, +0x05 class): one model can be placed
                    # with several (st03 chairs: 2-3 collapse in place and 2-18 shatter when touched; st01 walls
                    # 2-66 / 2-73; st09 triggers 4-1 / 4-3 / 4-7)
                    ob['pd_class'] = [int(p['category']), int(p['type'])]
                if preset == 'JUMP_PAD' and p['extra'][0] != tc.pd_jump_power:
                    # one pad model, several powers (Sein: 200 and 250): this pad keeps its own
                    ob['pd_jump_power'] = int(p['extra'][0])
                from . import roundtrip
                if roundtrip.ENABLED:                     # fallback only: its entry in the .dat
                    ob['pd_placement'] = p['offset']
                if not col and not no_model:
                    ob['pd_no_collider'] = True                  # the game's object has no collision
                if no_model and main_kind is not None:
                    ob.pd_surface = '%02X' % main_kind           # the trigger's surface kind (jump pads: 01)
                # what the add-on has no setting for, per object definition: on every placement of it, so the
                # export keeps definitions that share a model but not these apart (st06 oilcanA / oilcanB)
                ob['pd_root_values'] = [list(_node0(r)) for r in (intact, broken, debris)]
                if snd_row is not None:
                    ob['pd_object_sounds'] = list(snd_row)
                # the placement lists it is in (0 the default, 1 + variant): also when the map has one list only,
                # which need not be list 0 (st24 has list 3 alone: its objects show in variant 2 only)
                ob['pd_layouts'] = sorted(set(p['slots']))
                ob.hide_render = True
                tc.objects.link(ob)
                first = first or ob
            # moving objects (containers, iron roads): Actions on the broken pieces, made below (stage_extras)
            anims = [entry[3 + k] if entry[3 + k] != NONE and _anim_block(b_dat, entry[3 + k]) else None
                     for k in range(3)]
            for k in (0, 2):
                if anims[k] is not None:
                    report_parts['animations of state %d not represented' % k] += 1
            fx = [_effect_block(b_dat, entry[9 + k]) for k in range(3)]
            if any(fx):
                first['pd_object_effects'] = [x.hex() if x else '' for x in fx]
                first['pd_object_effects_map'] = stage or ''
                report_parts['effect tables'] += 1
            if intact and not no_model:
                # the intact model's own shadow volume (sshadow / sshadowch / sshadowc on a joint of its own): the
                # shadow the object casts, gone when it breaks; written back on that joint (objects_export)
                # one mesh per volume (each of the game's shadow draws: their edge strips stay within it)
                for j, rec in enumerate(intact):
                    sm = vis.build_mesh('shadow_%s %d' % (name, j), b_alr, h, texs, [rec], scale, image_of, stage,
                                        shadows=True)
                    if sm is not None:
                        _part(sm.name, sm, 'shadow', first, tc, True)
                        report_parts['shadow volumes'] += 1
            for k, (pre, label) in enumerate((('collider_', 'colliders'), ('collider_broken_', 'broken colliders'),
                                              ('collider_debris_', 'debris colliders'))):
                if not cols[k]:
                    continue
                # one collider per surface kind (the game's lists hold one chunk per kind: st09 a06_isupub 06 and
                # 12); a model-less object's main kind is its own mesh
                kinds = sorted({t[3] for t in cols[k]} - ({main_kind} if (k == 0 and no_model) else set()))
                for j, st in enumerate(kinds):
                    cname = pre + name + ('' if j == 0 else ' %02X' % st)
                    c = _part(cname, _tris_mesh(cname, [t for t in cols[k] if t[3] == st], scale), pre.rstrip('_'),
                              first, tc, k > 0)
                    c.pd_surface = '%02X' % st
                    report_parts[label] += 1
            if broken:
                pieces, nodes = _pieces(broken)
                vals = {top: int(round(nodes[top]['values'][0])) if top < len(nodes) else 0 for top in pieces}
                tc.pd_pieces_hurt = (tc.pd_pieces_hurt and not fresh) or any(vals.values())
                piece_of = {}
                for k, top in enumerate(sorted(pieces), 1):
                    node = nodes[top] if top < len(nodes) else {}
                    stay = node.get('marker') in STAY_MARKERS
                    pname = '%s%s %d' % ('stay_' if stay else 'break_', name, k)
                    own = pieces[top].get(top, [])
                    pm = (vis.build_mesh(pname, b_alr, h, texs, own, scale, image_of, stage) if own else None) \
                        or bpy.data.meshes.new(pname)
                    piece = _part(pname, pm, 'broken', first, tc, True)
                    piece['pd_piece_value'] = vals[top]      # the game's own number, kept for the export
                    piece_of[top] = piece
                    for j, sub in enumerate(sorted(n for n in pieces[top] if n != top), 1):
                        sm = vis.build_mesh('%s sub %d' % (pname, j), b_alr, h, texs, pieces[top][sub], scale,
                                            image_of, stage)
                        if sm is not None:
                            _part(sm.name, sm, 'sub', piece, tc, True)
                    j = 0
                    for sub in sorted(pieces[top]):
                        for rec in pieces[top][sub]:
                            # the piece's shadow volumes (on a joint under the piece: they fly with it), one mesh each
                            sm = vis.build_mesh('%s shadow %d' % (pname, j), b_alr, h, texs, [rec], scale, image_of,
                                                stage, shadows=True)
                            if sm is not None:
                                j += 1
                                _part(sm.name, sm, 'sub', piece, tc, True)
                                report_parts['piece shadow volumes'] += 1
                    report_parts['stay pieces' if stay else 'break pieces'] += 1
                if anims[1] is not None:
                    from . import stage_extras

                    def top_of(i, nodes=nodes):
                        seen = 0
                        while i < len(nodes) and nodes[i]['parent'] not in (None, 0) and seen < 64:
                            i, seen = nodes[i]['parent'], seen + 1
                        return i
                    done, lost = stage_extras.import_piece_animation(b_dat, anims[1], nodes, piece_of, top_of, scale,
                                                                     name)
                    report_parts['animated pieces'] += done
                    if lost:
                        report_parts['piece animation tracks not represented'] += len(lost)
            elif anims[1] is not None:
                report_parts['animations of state 1 not represented'] += 1
            if debris:
                dm = vis.build_mesh('debris_' + name, b_alr, h, texs, debris, scale, image_of, stage)
                if dm is not None:
                    _part(dm.name, dm, 'debris', first, tc, True)
                    report_parts['debris models'] += 1
                for j, rec in enumerate(debris):
                    dm = vis.build_mesh('debris_shadow_%s %d' % (name, j), b_alr, h, texs, [rec], scale, image_of,
                                        stage, shadows=True)
                    if dm is not None:
                        _part(dm.name, dm, 'debris', first, tc, True)
                        report_parts['debris shadow volumes'] += 1
    text = '%d objects (%d types in %d collections' % (len(places), len(by_object), len(groups))
    text += ''.join(', %d %s' % (n, k) for k, n in sorted(report_parts.items())) + ')'
    if len(slots) > 1:
        text += '; placement lists %s' % ', '.join(str(s) for s in slots)
    return text


def set_effect_fields(ob, f):
    """The effect record's settings on its empty (the transform is the empty's own)."""
    ob['pd_fx_class'] = f['cls']
    ob['pd_fx_when'] = f['when']
    ob['pd_fx_id'] = f['id']
    ob['pd_fx_mode'] = f['mode']
    ob['pd_fx_params'] = list(f['params'])
    ob['pd_fx_values'] = list(f['values'])


def effect_record(ob, scale):
    """An imported effect's record, from its empty: settings from its custom properties, position, turn and scale
    from its own location, rotation and scale."""
    pos = cv.to_game(ob.location, scale)
    rot = cv.rot_to_game([list(r) for r in ob.rotation_euler.to_matrix()])
    s = ob.scale
    return effects_build.record(ob['pd_fx_class'], ob.get('pd_fx_when', 0), ob.get('pd_fx_id', 0xFF),
                                ob.get('pd_fx_mode', 0), pos, rot, (s[0], s[2], s[1]),
                                ob.get('pd_fx_params', ()), ob.get('pd_fx_values', ()))


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
        f = effects_build.fields(raw)
        ob = bpy.data.objects.new('%s %d' % (label, kind), None)
        ob.empty_display_type = 'SPHERE' if kind == 20 else 'ARROWS'
        ob.empty_display_size = 10 * scale
        ob.location = cv.to_blender(f['pos'], scale)
        ob.rotation_euler = Matrix(cv.rot_to_blender(f['rot'])).to_euler('XYZ')   # full turn (Rz Ry Rx)
        ob.scale = (f['scale'][0], f['scale'][2], f['scale'][1])                  # game (x, y, z) -> Blender axes
        set_effect_fields(ob, f)
        ob['pd_effect_map'] = stage or ''            # sounds and effect models only work in this map
        colls[label].objects.link(ob)
    return '%d effects in %d kinds' % (len(es), len(colls))
