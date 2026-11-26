"""Stage sections as Blender data: sprite types (SP00), the enter lights (light list of the enter chunk stream),
the stage model list (MD00) with its animation blobs, and object animations (OA). Import and export.

  PD_<stage>
    Sprites                     one mesh object per sprite type the game makes: "Sprite 07 e3_02_dxt5_1"
                                  pd_sprite_number   the entry number (effect records name sprites by number)
                                  pd_sprite_capacity quads the type can have alive (the loader reserves 128 bytes each)
                                  pd_sprite_blend    render-state kind (pdstage/sp00.py BLEND)
                                  mesh: one quad per frame, frame k at local y = k * FRAME_STEP; the quad's corners
                                  are the frame's extent (x, z), its UVs the frame's texture rectangle; the material's
                                  image is the texture (looked up by name in the model file)
    Enter Lights                one Blender light per record of the enter stream's light list (the town's lamps;
                                on a battle map both executables place them too): pd_light_index (the light object
                                it fills), pd_light_kind (1 directional, 2/3 point, 5 hemisphere), pd_light_mask,
                                colour, energy = intensity, location = position
    Stage Models                one empty per MD00 slot in use: "MD16 st02_mdl_particle"
                                  pd_md00_slot        the slot effect records name (effect model slot 24 + slot)
                                  pd_game_model_root  the model: still the game file's model of that number (the
                                                      model's meshes and effect chunks are not Blender data yet)
                                  children: the model's joints as empties (pd_joint, rest pose = the joint's), each
                                  with an Action when the slot has an animation blob: keys = the joint's local
                                  translation / rotation (Euler XZY = the game's X, Y, Z angles on the mirrored
                                  axes) / scale as the game samples them; frame = game frame; the
                                  action's manual frame range = the track length
  object animations: on the broken pieces (break_/stay_) of a type's first placement, an Action keying the pieces'
  delta transforms (delta_location, delta_rotation_quaternion): the piece's motion away from its rest pose, frame =
  game frame. A root-joint animation (the whole broken model moves) is one Action shared by all pieces.
"""
import struct

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import convert as cv
from .pdstage import alr, dat, enter, motion, sp00

FRAME_STEP = 0.25            # Blender units between a sprite's frames (local y)
TOWN_SLOTS, STAGE_SLOTS = 16, 80


def _child_collection(root, name):
    c = bpy.data.collections.new(name)
    root.children.link(c)
    c['pd_section'] = name
    return c


def find_collection(scene, name):
    for c in bpy.data.collections:
        if c.get('pd_section') == name and scene.user_of_id(c):
            return c
    return None


def _prop(idb, key, value, desc):
    idb[key] = value
    try:
        idb.id_properties_ui(key).update(description=desc)
    except (TypeError, AttributeError):
        pass


# ---------------------------------------------------------------- game <-> Blender transforms

def game_to_blender(m, scale):
    """A game 4x4 (column vectors) as a Blender Matrix: P m P with the translation scaled."""
    o = (0, 2, 1)
    r = [[m[o[i]][o[j]] for j in range(3)] for i in range(3)]
    t = [m[o[i]][3] * scale for i in range(3)]
    return Matrix(((r[0][0], r[0][1], r[0][2], t[0]), (r[1][0], r[1][1], r[1][2], t[1]),
                   (r[2][0], r[2][1], r[2][2], t[2]), (0, 0, 0, 1)))


def blender_to_game(bm, scale):
    o = (0, 2, 1)
    return [[bm[o[i]][o[j]] for j in range(3)] + [bm[o[i]][3] / scale] for i in range(3)] + [[0.0, 0.0, 0.0, 1.0]]


# ---------------------------------------------------------------- actions

def new_action(name, obs, slot_name):
    act = bpy.data.actions.new(name)
    slot = act.slots.new(id_type='OBJECT', name=slot_name)
    for ob in obs:
        ad = ob.animation_data or ob.animation_data_create()
        ad.action = act
        ad.action_slot = slot
    from bpy_extras import anim_utils
    return act, anim_utils.action_ensure_channelbag_for_slot(act, slot)


def set_curve(cb, path, index, frames, values):
    fc = cb.fcurves.new(path, index=index)
    fc.keyframe_points.add(len(frames))
    co = []
    for f, v in zip(frames, values):
        co += [float(f), float(v)]
    fc.keyframe_points.foreach_set('co', co)
    for k in fc.keyframe_points:
        k.interpolation = 'LINEAR'
    fc.update()
    return fc


def curves_of(ob):
    """{data_path: {index: fcurve}} of the object's assigned action slot, or {}."""
    ad = ob.animation_data
    if ad is None or ad.action is None or ad.action_slot is None:
        return {}
    from bpy_extras import anim_utils
    cb = anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)
    out = {}
    for fc in (cb.fcurves if cb else []):
        out.setdefault(fc.data_path, {})[fc.array_index] = fc
    return out


def _keys(curves, path, n):
    """Sorted key frames of the curves of `path` and an evaluator frame -> tuple of n values (None if absent)."""
    cs = curves.get(path)
    if not cs:
        return [], None
    frames = sorted({round(k.co[0], 4) for fc in cs.values() for k in fc.keyframe_points})
    default = (1.0, 0.0, 0.0, 0.0) if n == 4 else ((1.0,) * 3 if path.endswith('scale') else (0.0,) * 3)
    return frames, (lambda f: tuple(cs[i].evaluate(f) if i in cs else default[i] for i in range(n)))


def _set_frame_range(act, length):
    act.use_frame_range = True
    act.frame_start, act.frame_end = 0.0, max(float(length), 1.0)


def _length(act):
    return float(act.frame_end) if act.use_frame_range else float(act.frame_range[1])


# ---------------------------------------------------------------- SP00 sprites

def _sprite_image(name):
    want = sp00.game_name(name)
    for img in bpy.data.images:
        if 'pd_texture_number' in img and img.name.lower()[:12] == want:
            return img
    return None


def import_sprites(context, b_dat, b_alr, root, scale):
    s = sp00.read(b_dat)
    if s is None:
        return 'no sprite types'
    names = {t['name'] for t in alr.textures(b_alr)} if b_alr else None
    coll = _child_collection(root, 'Sprites')
    made = 0
    for i, e in enumerate(s['entries']):
        if e['name'] == 'NOUSE' or (names is not None and sp00.game_name(e['name']) not in names):
            continue                                     # no texture: the game can make nothing of it
        # entries the loader makes no pool for (capacity 0) are kept too: game code reads some of them by number
        # (the rain streaks of families 3 and 9 draw sprite 40, e3a_drop01, capacity 0: Xbox 0x105410; without
        # it the engine drew white streaks on st03 / st13 / st23). Their whole frame list is shown
        frames = s['lists'][e['list']][:e['frames']] if sp00.active(e, names) else s['lists'][e['list']]
        verts, faces, uvs = [], [], []
        for k, f in enumerate(frames):
            l, t, r, btm, u0, v0, u1, v1 = f
            y = k * FRAME_STEP
            base = len(verts)
            verts += [(l * scale, y, t * scale), (r * scale, y, t * scale), (r * scale, y, btm * scale),
                      (l * scale, y, btm * scale)]
            faces.append((base, base + 1, base + 2, base + 3))
            uvs += [(u0, 1 - v0), (u1, 1 - v0), (u1, 1 - v1), (u0, 1 - v1)]
        img = _sprite_image(e['name'])
        label = img.name if img else sp00.game_name(e['name'])
        me = bpy.data.meshes.new('Sprite %02d %s' % (i, label))
        me.from_pydata(verts, [], faces)
        uvl = me.uv_layers.new(name='UVMap')
        for li, loop in enumerate(me.loops):
            uvl.data[li].uv = uvs[loop.vertex_index]
        mat = bpy.data.materials.new(me.name)
        mat.use_nodes = True
        if img is not None:
            nt = mat.node_tree
            tex = nt.nodes.new('ShaderNodeTexImage')
            tex.image = img
            bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
            if bsdf is not None:
                nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
                nt.links.new(tex.outputs['Alpha'], bsdf.inputs['Alpha'])
        me.materials.append(mat)
        ob = bpy.data.objects.new(me.name, me)
        _prop(ob, 'pd_sprite_number', i, 'Sprite entry number: effect records name sprite types by number')
        _prop(ob, 'pd_sprite_capacity', e['capacity'], 'Quads of this type alive at once (128 bytes each)')
        if e['frames'] != len(frames):
            _prop(ob, 'pd_sprite_played', e['frames'], 'Frames of the list the type plays (0: a type the loader '
                  'does not make)')
        _prop(ob, 'pd_sprite_blend', e['blend'], 'Render-state kind: ' + '; '.join(
            '%d %s' % (k, v[0]) for k, v in sorted(sp00.BLEND.items())))
        ob.hide_render = True
        coll.objects.link(ob)
        made += 1
    return '%d sprite types' % made


def sprite_images(scene):
    """The images the sprite types' materials show (written into the .alr: SP00 names its textures)."""
    coll = find_collection(scene, 'Sprites')
    out = []
    for ob in (coll.all_objects if coll else []):
        for m in (ob.data.materials if ob.type == 'MESH' else []):
            if m and m.use_nodes:
                out += [n.image for n in m.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image and n.image.size[0]]
    return list({i.name: i for i in out}.values())


def gather_sprites(scene, scale):
    coll = find_collection(scene, 'Sprites')
    if coll is None:
        return None
    out = {}
    for ob in coll.all_objects:
        if ob.type != 'MESH' or 'pd_sprite_number' not in ob:
            continue
        me = ob.data
        img = None
        for m in me.materials:
            if m and m.use_nodes:
                img = next((n.image for n in m.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image), None)
                if img:
                    break
        if img is None:
            raise ValueError('%s: its material has no image (the sprite texture)' % ob.name)
        uvl = me.uv_layers.active
        frames = []
        for poly in me.polygons:
            corners = []
            for li in poly.loop_indices:
                v = me.vertices[me.loops[li].vertex_index].co
                uv = uvl.data[li].uv if uvl else (0.0, 0.0)
                corners.append((v.x / scale, v.y, v.z / scale, uv[0], 1 - uv[1]))
            l, r = min(c[0] for c in corners), max(c[0] for c in corners)
            t, btm = max(c[2] for c in corners), min(c[2] for c in corners)
            near = lambda x, z: min(corners, key=lambda c: (c[0] - x) ** 2 + (c[2] - z) ** 2)
            lt, rb = near(l, t), near(r, btm)
            y = sum(c[1] for c in corners) / len(corners)
            frames.append((y, (l, t, r, btm, lt[3], lt[4], rb[3], rb[4])))
        frames.sort(key=lambda f: f[0])
        from .visuals_export import game_texture_name     # the name the image is written under in the .alr
        out[int(ob['pd_sprite_number'])] = dict(texture=game_texture_name(img.name) + '.dds',
                                                capacity=int(ob['pd_sprite_capacity']),
                                                blend=int(ob['pd_sprite_blend']), frames=[f for _y, f in frames])
        if 'pd_sprite_played' in ob:
            out[int(ob['pd_sprite_number'])]['played'] = int(ob['pd_sprite_played'])
    return out


# ---------------------------------------------------------------- enter lights

KIND_TYPE = {1: 'SUN', 2: 'POINT', 3: 'POINT', 5: 'SUN'}


def import_enter_lights(context, b_dat, root, scale, stage):
    town = (int(stage[2:4]) % 10 == 9) if stage[2:4].isdigit() else False
    e = enter.read(b_dat, 0, 32 if town else 0)
    if not e['present']:
        return 'no enter stream'
    if e['other']:
        return 'enter stream: chunk ids %s not represented' % sorted(set(e['other']))
    if not e['lights']:
        return 'enter stream empty'
    coll = _child_collection(root, 'Enter Lights')
    for L in e['lights']:
        ld = bpy.data.lights.new('Enter light %d' % L['index'], KIND_TYPE.get(L['kind'], 'POINT'))
        ld.color = tuple(c / 255.0 for c in L['colour'])
        ld.energy = L['intensity']
        ob = bpy.data.objects.new(ld.name, ld)
        ob.location = cv.to_blender(L['position'], scale)
        _prop(ob, 'pd_light_index', L['index'], 'The light object this record fills (draw light lists refer to it)')
        _prop(ob, 'pd_light_kind', L['kind'], '1 directional, 2 and 3 point, 5 hemisphere')
        _prop(ob, 'pd_light_mask', L['mask'], 'Masks 2 / 4 of the characters\' light choice (0x14FF50)')
        if any(L['vector']):
            _prop(ob, 'pd_light_vector', list(L['vector']), 'Direction (directional) or axis (hemisphere), game space')
        if L['kind'] == 1:
            _prop(ob, 'pd_light_value_36', L['value_36'], 'Directional lights: the value copied to the light +0x60')
        coll.objects.link(ob)
    return '%d enter lights' % len(e['lights'])


def gather_enter_lights(scene, scale):
    coll = find_collection(scene, 'Enter Lights')
    if coll is None:
        return []
    out = []
    for ob in coll.all_objects:
        if ob.type != 'LIGHT' or 'pd_light_index' not in ob:
            continue
        out.append(dict(index=int(ob['pd_light_index']), kind=int(ob.get('pd_light_kind', 2)),
                        colour=tuple(round(c * 255) for c in ob.data.color), intensity=float(ob.data.energy),
                        position=cv.to_game(tuple(ob.matrix_world.translation), scale),
                        vector=tuple(ob.get('pd_light_vector', (0.0, 0.0, 0.0))), mask=int(ob.get('pd_light_mask', 0)),
                        value_36=float(ob.get('pd_light_value_36', 0.0))))
    out.sort(key=lambda L: L['index'])
    return out


# ---------------------------------------------------------------- MD00 model list and its animation blobs

def _blobs(b):
    """The animation blobs (header word 0xF4: u32 count, then u32 length + bytes per blob)."""
    bo, out = struct.unpack_from('<I', b, 0xF4)[0], []
    if bo != 0xFFFFFFFF:
        q = bo + 4
        for _ in range(struct.unpack_from('<I', b, bo)[0]):
            n = struct.unpack_from('<I', b, q)[0]
            out.append(bytes(b[q + 4:q + 4 + n]))
            q += 4 + n
    return out


def _skeleton(b_alr, root_index):
    h = alr.header(b_alr)
    if root_index >= len(h['roots']):
        return []
    for off, t, size in alr.chain(b_alr, h['roots'][root_index]):
        if t == 3:
            n = struct.unpack_from('<H', b_alr, off + 8)[0]
            out = []
            for j in range(n):
                v = struct.unpack_from('<9fHHHHI', b_alr, off + 16 + 64 * j)
                out.append(dict(t=v[0:3], rot=v[3:6], scale=v[6:9], parent=None if v[12] == 0xFFFF else v[12]))
            return out
    return []


def import_md00(context, b_dat, b_alr, root, scale):
    md = dat.md00(b_dat)
    if md is None:
        return 'no stage model list'
    names, _anims, pairs = md
    blobs = _blobs(b_dat)
    coll = _child_collection(root, 'Stage Models')
    made = animated = 0
    for slot, (model, blob) in enumerate(pairs):
        if model < 0 and blob < 0:
            continue
        label = names[slot][:-4] if names[slot].lower().endswith('.alm') else names[slot]
        e = bpy.data.objects.new('MD%02d %s' % (slot, label), None)
        e.empty_display_type = 'CUBE'
        e.empty_display_size = 5 * scale
        _prop(e, 'pd_md00_slot', slot, 'Stage model slot: effect records name effect model 24 + slot')
        if model >= 0:
            _prop(e, 'pd_game_model_root', model, 'The model: the game file\'s model of this number (its meshes and '
                                                  'effect chunks are not Blender data yet)')
        coll.objects.link(e)
        made += 1
        if blob < 0 or model < 0:
            continue
        tracks = motion.read_run(blobs[blob], 0)
        nodes = _skeleton(b_alr, model) if b_alr else []
        joints = []
        for j, nd in enumerate(nodes):
            je = bpy.data.objects.new('MD%02d j%d' % (slot, j), None)
            je.empty_display_type = 'PLAIN_AXES'
            je.empty_display_size = 2 * scale
            je.parent = joints[nd['parent']] if nd['parent'] is not None and nd['parent'] < j else e
            # game Euler X, then Y, then Z (Rz Ry Rx) is Blender Euler XZY with angles (-x, -z, -y) on the mirrored
            # axes: the keys keep the game's own angles, no decomposition on export (no drift at the gimbal lock)
            je.rotation_mode = 'XZY'
            je.matrix_basis = game_to_blender(motion.joint_local(nd), scale)
            _prop(je, 'pd_joint', j, 'Joint number of the model\'s skeleton')
            coll.objects.link(je)
            joints.append(je)
        for t in tracks:
            if t['joint'] >= len(joints):
                continue
            je = joints[t['joint']]
            act, cb = new_action('MD%02d %s j%d' % (slot, label, t['joint']), [je], je.name)
            _track_to_curves(cb, t, scale, absolute=True)
            _set_frame_range(act, t['length'])
            animated += 1
    return '%d stage model slots (%d joint animations)' % (made, animated)


def _track_to_curves(cb, t, scale, absolute):
    if t['T']:
        fr = [k[0] for k in t['T']]
        vals = [cv.to_blender(k[1:4], scale) for k in t['T']]
        for i in range(3):
            set_curve(cb, 'location', i, fr, [v[i] for v in vals])
    if t['R']:
        fr = [k[0] for k in t['R']]
        for i, (gi, sign) in enumerate(((1, -1.0), (3, -1.0), (2, -1.0))):    # Blender XZY: (-x, -z, -y)
            set_curve(cb, 'rotation_euler', i, fr, [sign * k[gi] for k in t['R']])
    if t['S']:
        fr = [k[0] for k in t['S']]
        for i, gi in enumerate((0, 2, 1)):
            set_curve(cb, 'scale', i, fr, [k[1 + gi] for k in t['S']])


def _curves_to_track(ob, joint, scale, length):
    cs = curves_of(ob)
    t = dict(joint=joint, length=length, T=[], R=[], S=[])
    fr, ev = _keys(cs, 'location', 3)
    for f in fr:
        t['T'].append((f,) + cv.to_game(ev(f), scale))
    fr, ev = _keys(cs, 'rotation_euler', 3)
    if fr and ob.rotation_mode == 'XZY':
        for f in fr:
            e = ev(f)
            t['R'].append((f, -e[0], -e[2], -e[1]))
        fr = []
    else:
        fr, ev = _keys(cs, 'rotation_quaternion', 4)
    prev = None
    for f in fr:
        q = Quaternion(ev(f)).normalized()
        g = blender_to_game(q.to_matrix().to_4x4(), scale)
        prev = motion.matrix_euler_near(g, prev)
        t['R'].append((f,) + prev)
    fr, ev = _keys(cs, 'scale', 3)
    for f in fr:
        s = ev(f)
        t['S'].append((f, s[0], s[2], s[1]))
    return t


def gather_md00(scene, scale):
    """{slot: dict(name, root, blob bytes or None)} from the Stage Models collection, or None without one."""
    coll = find_collection(scene, 'Stage Models')
    if coll is None:
        return None
    out = {}
    for e in coll.objects:
        if 'pd_md00_slot' not in e:
            continue
        joints = sorted((c for c in e.children_recursive if 'pd_joint' in c), key=lambda c: int(c['pd_joint']))
        tracks = []
        for je in joints:
            ad = je.animation_data
            if ad and ad.action:
                tracks.append(_curves_to_track(je, int(je['pd_joint']), scale, _length(ad.action)))
        name = e.name.split(' ', 1)[1] if ' ' in e.name else e.name
        out[int(e['pd_md00_slot'])] = dict(name=name, root=int(e.get('pd_game_model_root', -1)),
                                           blob=motion.write_run(tracks) if tracks else None)
    return out


def build_md00(slots, town=False):
    """(MD00 section bytes, blob list bytes) from gather_md00's slots."""
    n = max([TOWN_SLOTS if town else STAGE_SLOTS] + [s + 1 for s in slots])
    names, anims, pairs, blobs = [], [], [], []
    for s in range(n):
        m = slots.get(s)
        if m is None or (m['root'] < 0 and m['blob'] is None):
            names.append('NOUSE')
            anims.append('NOUSE')
            pairs.append((-1, -1))
            continue
        names.append(m['name'] + '.alm')
        if m['blob'] is not None:
            anims.append(m['name'] + '.ala')
            pairs.append((m['root'], len(blobs)))
            blobs.append(m['blob'])
        else:
            anims.append('NOUSE')
            pairs.append((m['root'], -1))
    a = b''.join(x.encode('latin-1') + b'\0' for x in names)
    c = b''.join(x.encode('latin-1') + b'\0' for x in anims)
    md = b'MD00' + struct.pack('<III', len(a), len(c), n) + a + c
    md += b''.join(struct.pack('<2i', *p) for p in pairs) + bytes(8)
    bl = struct.pack('<I', len(blobs)) + b''.join(struct.pack('<I', len(x)) + x for x in blobs)
    return md, bl


def put_md00(b, md, bl):
    buf = bytearray(b)
    off = len(buf)
    buf += md
    struct.pack_into('<I', buf, 0xA0, off)
    buf += b'\0' * (-len(buf) % 4)
    off = len(buf)
    buf += bl
    struct.pack_into('<I', buf, 0xF4, off)
    struct.pack_into('<I', buf, 0x138, len(buf))
    return bytes(buf)


# ---------------------------------------------------------------- object animations (OA) on broken pieces

def import_piece_animation(b_dat, off, nodes, piece_of, top_of, scale, label):
    """Actions on the pieces for the OA run at `off` of a broken model with `nodes` (alr node dicts with
    t, rot, scale, parent). piece_of: {top node: piece object}; top_of(node) -> its piece's top node.
    Returns (pieces animated, tracks not represented)."""
    tracks = motion.read_run(b_dat, off)
    by_joint = {t['joint']: t for t in tracks}
    root_track = by_joint.get(0)
    length = max([t['length'] for t in tracks] + [0.0])
    rest = [motion.joint_local(n) for n in nodes]

    def world(j, time, use_tracks):
        m, i, seen = motion.joint_local(nodes[j]), nodes[j]['parent'], 0
        if use_tracks and j in by_joint:
            m = motion.joint_local(nodes[j], by_joint[j], time)
        while i is not None and seen < 64:
            pm = motion.joint_local(nodes[i], by_joint[i], time) if use_tracks and i in by_joint else rest[i]
            m = motion.mul(pm, m)
            i, seen = nodes[i]['parent'], seen + 1
        return m

    lost = [t['joint'] for t in tracks if t['joint'] != 0 and (t['joint'] >= len(nodes) or
                                                               top_of(t['joint']) != t['joint'] or
                                                               t['joint'] not in piece_of)]
    shared = None
    done = 0
    for top, piece in sorted(piece_of.items()):
        own = by_joint.get(top) if top != 0 else None      # top 0: the root's own meshes, moved by the root
        if own is None and root_track is None:
            continue
        if own is None and shared is not None:            # the root moves every piece the same way
            ad = piece.animation_data or piece.animation_data_create()
            ad.action, ad.action_slot = shared
            done += 1
            continue
        frames = sorted(set((motion.frames_of(own) if own else []) + (motion.frames_of(root_track) if root_track
                                                                      else [])))
        rw_inv = motion.inverse_rigid(world(top, 0.0, False))
        locs, quats, prev = [], [], None
        for f in frames:
            d = game_to_blender(motion.mul(world(top, f, True), rw_inv), scale)
            loc, q, _s = d.decompose()
            if prev is not None and prev.dot(q) < 0:
                q.negate()
            prev = q
            locs.append(loc)
            quats.append(q)
        piece.rotation_mode = 'QUATERNION'
        name = 'PD Anim: %s %s' % (label, 'root' if own is None else piece.name)
        act, cb = new_action(name, [piece], 'pieces' if own is None else piece.name)
        for i in range(3):
            set_curve(cb, 'delta_location', i, frames, [v[i] for v in locs])
        for i in range(4):
            set_curve(cb, 'delta_rotation_quaternion', i, frames, [q[i] for q in quats])
        _set_frame_range(act, length)
        if own is None:
            shared = (act, piece.animation_data.action_slot)
        done += 1
    return done, lost


def rest_local(ob):
    """The object's local matrix without its delta transforms (the rest pose an object animation moves away from)."""
    if ob.rotation_mode == 'QUATERNION':
        rot = ob.rotation_quaternion
    elif ob.rotation_mode == 'AXIS_ANGLE':
        a = ob.rotation_axis_angle
        rot = Quaternion((a[1], a[2], a[3]), a[0])
    else:
        rot = ob.rotation_euler.to_quaternion()
    return ob.matrix_parent_inverse @ Matrix.LocRotScale(ob.location, rot, ob.scale)


def _delta_matrix(curves, f):
    _fr, ev = _keys(curves, 'delta_location', 3)
    loc = Vector(ev(f)) if ev else Vector()
    _fr, evq = _keys(curves, 'delta_rotation_quaternion', 4)
    q = Quaternion(evq(f)).normalized() if evq else Quaternion()
    return loc, q


def export_piece_animation(pieces, scale):
    """OA tracks from the pieces' actions. pieces: [(piece object, node index in the written model, rest matrix in
    the model's Blender space (the matrix its mesh was written with))]. Returns a run's bytes or None."""
    animated = [(p, k, m) for p, k, m in pieces if p.animation_data and p.animation_data.action]
    if not animated:
        return None
    acts = {(p.animation_data.action, p.animation_data.action_slot) for p, _k, _m in animated}
    tracks = []
    if len(acts) == 1 and len(animated) == len(pieces) and len(pieces) > 1:
        # one action on every piece: the broken model's root moves (joint 0)
        p = animated[0][0]
        cs = curves_of(p)
        frames = sorted(set(_keys(cs, 'delta_location', 3)[0]) | set(_keys(cs, 'delta_rotation_quaternion', 4)[0]))
        t = dict(joint=0, length=_length(p.animation_data.action), T=[], R=[], S=[])
        prev = None
        for f in frames:
            loc, q = _delta_matrix(cs, f)
            g = blender_to_game(Matrix.LocRotScale(loc, q, None), scale)
            t['T'].append((f, g[0][3], g[1][3], g[2][3]))
            prev = motion.matrix_euler_near(g, prev)
            t['R'].append((f,) + prev)
        tracks.append(t)
    else:
        for p, k, m in animated:
            cs = curves_of(p)
            frames = sorted(set(_keys(cs, 'delta_location', 3)[0]) |
                            set(_keys(cs, 'delta_rotation_quaternion', 4)[0]))
            t = dict(joint=k, length=_length(p.animation_data.action), T=[], R=[], S=[])
            l0, r0, _s0 = m.decompose()
            prev = None
            for f in frames:
                dl, dq = _delta_matrix(cs, f)
                # the piece at frame f: T(l0 + dl) R(q0 dq) in its owner's space; its mesh was written at
                # T(l0) R(q0): the motion of the written vertices is rotation q0 dq q0^-1 about l0, then dl
                rq = r0 @ dq @ r0.inverted()
                tr = l0 + dl - (rq @ l0)
                g = blender_to_game(Matrix.LocRotScale(tr, rq, None), scale)
                t['T'].append((f, g[0][3], g[1][3], g[2][3]))
                prev = motion.matrix_euler_near(g, prev)
                t['R'].append((f,) + prev)
            tracks.append(t)
    return motion.write_run(tracks)
