"""Characters in Blender: load a player, enemy or NPC model with its armature, weights, textures and animations;
load other animation sets onto it; export it over a battle character (Player\\<id>\\<id>0..3.alr + exmot*.ala).

Game files: Player\\<id>\\<id>0..3.alr (battle models, colour variants, 130 animations each) and exmot0..5.ala
(win / lose motions 130..135); NPCs only exist in the event bundles Event\\*.mk (models) and Event\\*.ak (event
animation clips named <id>_<clip>.ala). Readers and writer: pdstage/character.py and pdstage/char_build.py.

Blender side:
- one armature per model run (the body; cloth and props are extra armatures parented to it), a bone per game joint,
  tails placed at the child joint (or between symmetric children) so the skeleton reads like a skeleton;
- bone custom properties keep the game's joint number and record; the armature keeps the joint list as JSON so
  animations can be moved between skeletons without the game files;
- one action per motion, named "<set> 033" (motion id), with custom properties pd_set and pd_motion.
"""
import json
import math
import os
import struct

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import char_tools as ct
from . import convert as cv
from .pdstage import alr, character as ch, char_build as cb, charaset as cs

BACKUP_DIR = 'pd_addon_backup'
PLAYER = 'Player'
EVENT = 'Event'
# joints the game looks up by name (PDUWP.exe name tables at 0x2DB7D8 and 0x2F2120) and two it uses for the camera
# required joints that carry no mesh; the export copies them from the replaced character when missing
ADDABLE_JOINTS = ('alpha', 'camera')
REQUIRED_JOINTS = ['body1', 'body2', 'lkata', 'lninou', 'ltekub', 'lhand', 'rkata', 'rninou', 'rtekub', 'rhand',
                   'neck', 'head', 'hip', 'lmomo', 'lknee', 'lfoot', 'rmomo', 'rknee', 'rfoot', 'alpha', 'camera']
EXMOT = 6
NO_UV_FORMATS = (0x07, 0x08, 0x0B, 0x10, 0x18)      # shadow volumes, aura hulls, position-only meshes
SWAP = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))     # game <-> Blender (a mirror)


# ---------------------------------------------------------------- game files

def _child(parent, name):
    p = os.path.join(parent, name)
    if os.path.exists(p):
        return p
    try:
        low = name.lower()
        return next((os.path.join(parent, n) for n in os.listdir(parent) if n.lower() == low), None)
    except OSError:
        return None


def game_path(data, *parts, original=True):
    """Path of a game file (folders matched in any letter case). original: the add-on's backup copy if this
    file was replaced by an export."""
    cur = data
    for k, part in enumerate(parts):
        nxt = _child(cur, part) if cur else None
        if nxt is None:
            return None
        if original and k == len(parts) - 1:
            bdir = _child(cur, BACKUP_DIR)
            backup = _child(bdir, part) if bdir else None
            if backup and os.path.isfile(backup):
                return backup
        cur = nxt
    return cur


def read(path):
    with open(path, 'rb') as f:
        return f.read()


def _bundle_names(path):
    """Member names and sizes of a .mk / .ak without reading the whole file."""
    with open(path, 'rb') as f:
        head = f.read(8)
        if len(head) < 8:
            return []
        hs, n = struct.unpack('<2I', head)
        if n > 100000 or hs > 1 << 22:
            return []
        rest = f.read(max(hs, 8 + 8 * n) - 8 + 4096)
        f.seek(0, 2)
        total = f.tell()
    b = head + rest
    offs = struct.unpack_from('<%dI' % n, b, 8)
    names = b[8 + 4 * n:].split(b'\0')[:n]
    ends = sorted(set(offs) | {total})
    out = []
    for o, nm in zip(offs, names):
        end = next((e for e in ends if e > o), total)
        out.append((nm.decode('ascii', 'replace'), end - o))
    return out


_scan = {}


def scan(data):
    """What the game folder has: {'battle': [ids], 'npc': {id: [(bundle, size)]}, 'events': {id: [bundles]}}."""
    data = bpy.path.abspath(data or '')
    if data in _scan:
        return _scan[data]
    res = dict(battle=[], npc={}, events={})
    pdir = game_path(data, PLAYER, original=False)
    if pdir:
        for cid, _cat, _n in ch.CHARACTERS:
            if _child(pdir, cid) and (game_path(data, PLAYER, cid, cid + '0.alr') or game_path(data, PLAYER, cid, cid + '.alr')):
                res['battle'].append(cid)
    res['boss'] = [cid for cid, cat, _n in ch.CHARACTERS if cat == 'Boss' and game_path(data, 'boss', cid, cid + '.alr')]
    edir = game_path(data, EVENT, original=False)
    if edir:
        for fn in sorted(os.listdir(edir)):
            low = fn.lower()
            p = os.path.join(edir, fn)
            if low.endswith('.mk'):
                for name, size in _bundle_names(p):
                    cid = name.lower().rsplit('.', 1)[0]
                    if cid.startswith('npc') and name.lower().endswith('.alr'):
                        vers = res['npc'].setdefault(cid, [])
                        if size not in [s for _b, s in vers]:
                            vers.append((fn, size))
            elif low.endswith('.ak'):
                for name, _size in _bundle_names(p):
                    if name.lower().endswith('.ala') and '_' in name:
                        cid = name.lower().split('_', 1)[0]
                        lst = res['events'].setdefault(cid, [])
                        if fn not in lst:
                            lst.append(fn)
    res['missing'] = _missing_scan(data, res)
    _scan[data] = res
    return res


def missing_joints(joints):
    """Joints every battle character has (the game looks them up by name) that this skeleton lacks: such characters
    look broken when played, even when the export adds the missing ones."""
    names = {j['name'] for j in joints}
    return [n for n in REQUIRED_JOINTS if n not in names]


def _missing_scan(data, res):
    """{key: [missing joint names]} for every dropdown entry (read once per game folder)."""
    out = {}
    for cid in res['battle']:
        p = game_path(data, PLAYER, cid, cid + '0.alr') or game_path(data, PLAYER, cid, cid + '.alr')
        try:
            out['B:' + cid] = missing_joints(_skeleton_of(read(p)))
        except Exception:
            pass
    for cid in res.get('boss', []):
        try:
            out['S:' + cid] = missing_joints(_skeleton_of(read(game_path(data, 'boss', cid, cid + '.alr'))))
        except Exception:
            pass
    cache = {}
    for cid, vers in res['npc'].items():
        for bundle, _size in vers:
            try:
                if bundle not in cache:
                    cache[bundle] = ch.bundle_members(read(game_path(data, EVENT, bundle)))
                mb = next(b for n, b in cache[bundle] if n.lower() == cid + '.alr')
                out['N:%s:%s' % (cid, bundle)] = missing_joints(_skeleton_of(mb))
            except Exception:
                pass
    return out


def broken_note(missing):
    return ' - Possibly Broken (Missing joints/body)' if missing else ''


def character_items(data):
    """Dropdown entries: 'Playable: Alpha (pc00a)' ... (key 'B:<id>' battle model, 'N:<id>:<bundle>' NPC)."""
    s = scan(data)
    items = []
    cat_of = {cid: (cat, name) for cid, cat, name in ch.CHARACTERS}
    for cid, cat, name in ch.CHARACTERS:
        if cat != 'NPC' and cid in s['battle']:
            miss = s.get('missing', {}).get('B:' + cid, [])
            items.append(('B:' + cid, '%s: %s (%s)%s' % (cat, name, cid, broken_note(miss)),
                          'Battle model %s' % cid + ('. Its skeleton lacks joints the game looks up by name (%s): '
                                                     'played as a fighter it looks broken' % ', '.join(miss) if miss else '')))
    for cid in s.get('boss', []):
        _cat, name = cat_of[cid]
        miss = s.get('missing', {}).get('S:' + cid, [])
        items.append(('S:' + cid, 'Boss: %s (%s)%s' % (name, cid, broken_note(miss)),
                      'Boss model %s' % cid + ('. Not a humanoid fighter skeleton: lacks %s' % ', '.join(miss)
                                               if miss else '')))
    for cid in sorted(s['npc']):
        _cat, name = cat_of.get(cid, ('NPC', cid))
        vers = s['npc'][cid]
        for k, (bundle, _size) in enumerate(vers):
            extra = '' if len(vers) == 1 else ', version %d' % (k + 1)
            key = 'N:%s:%s' % (cid, bundle)
            miss = s.get('missing', {}).get(key, [])
            items.append((key, 'NPC: %s (%s%s)%s' % (name, cid, extra, broken_note(miss)),
                          'Event model %s from Event\\%s' % (cid, bundle) +
                          ('. Its skeleton lacks joints the game looks up by name (%s): played as a fighter it looks '
                           'broken' % ', '.join(miss) if miss else '')))
    return items


def animation_set_items(data):
    """Dropdown entries for animation sets: battle sets (130 motions + 6 exmot) and event clip sets."""
    s = scan(data)
    names = {cid: (cat, name) for cid, cat, name in ch.CHARACTERS}
    items = []
    for cid in s['battle']:
        cat, name = names[cid]
        items.append(('B:' + cid, 'Battle: %s (%s)' % (name, cid),
                      '%s\'s 130 battle motions and 6 win / lose motions' % name))
    for cid in s.get('boss', []):
        items.append(('S:' + cid, 'Boss: %s (%s)' % (names[cid][1], cid), 'The boss\'s own motions'))
    if pc01_motion(data):
        items.append(('M:pc01a', 'Battle extra: Edgar (pc01a_motion)', 'pc01a_motion.alr: 149 motions'))
    for cid in sorted(s['events']):
        cat, name = names.get(cid, ('', cid))
        items.append(('E:' + cid, 'Event clips: %s (%s)' % (name, cid),
                      'Story-event clips of %s (talk, walk, stand...) from Event\\*.ak' % name))
    return items


def pc01_motion(data):
    return game_path(bpy.path.abspath(data), PLAYER, 'pc01a', 'pc01a_motion.alr')


def load_model_bytes(data, key, variant=0):
    """(bytes, label, source path) of the dropdown entry `key`."""
    data = bpy.path.abspath(data)
    kind, _, rest = key.partition(':')
    if kind == 'B':
        cid = rest
        for fn in ([cid + '%d.alr' % variant] if variant >= 0 else []) + [cid + '0.alr', cid + '.alr']:
            p = game_path(data, PLAYER, cid, fn)
            if p:
                return read(p), cid, p
        raise FileNotFoundError('Player\\%s\\%s0.alr not found' % (cid, cid))
    if kind == 'S':
        p = game_path(data, 'boss', rest, rest + '.alr')
        if not p:
            raise FileNotFoundError('boss\\%s\\%s.alr not found' % (rest, rest))
        return read(p), rest, p
    cid, _, bundle = rest.partition(':')
    p = game_path(data, EVENT, bundle)
    if not p:
        raise FileNotFoundError('Event\\%s not found' % bundle)
    for name, b in ch.bundle_members(read(p)):
        if name.lower() == cid + '.alr':
            return b, cid, p + '|' + name
    raise FileNotFoundError('%s is not in Event\\%s' % (cid, bundle))


def _skeleton_of(b):
    h = alr.header(b)
    return ch.read_model(b, h['roots'][ch.model_roots(b)[0]])['joints']


def animation_set(data, key):
    """Clips of an animation set: [(name, motion id or None, source joints, tracks)]."""
    data = bpy.path.abspath(data)
    kind, _, cid = key.partition(':')
    out = []
    if kind == 'S':
        b = read(game_path(data, 'boss', cid, cid + '.alr'))
        joints = _skeleton_of(b)
        for run in ch.animation_roots(b):
            out.append(('%s %03d' % (cid, run), None, joints, ch.run_tracks(b, run)))
        return out
    if kind == 'B':
        p = game_path(data, PLAYER, cid, cid + '0.alr') or game_path(data, PLAYER, cid, cid + '.alr')
        b = read(p)
        joints = _skeleton_of(b)
        for run in ch.animation_roots(b):
            out.append(('%s %03d' % (cid, run), run, joints, ch.run_tracks(b, run)))
        for k in range(EXMOT):
            q = game_path(data, PLAYER, cid, 'exmot%d.ala' % k)
            if q:
                out.append(('%s %03d exmot%d' % (cid, ch.EXMOT_BASE + k, k), ch.EXMOT_BASE + k, joints,
                            ch.read_tracks(read(q), 0)))
    elif kind == 'M':
        p = pc01_motion(data)
        b = read(p)
        src = read(game_path(data, PLAYER, 'pc01a', 'pc01a0.alr'))
        joints = _skeleton_of(src)
        for run in ch.animation_roots(b):
            out.append(('pc01a_motion %03d' % run, None, joints, ch.run_tracks(b, run)))
    else:
        s = scan(data)
        seen = set()
        for bundle in s['events'].get(cid, []):
            ak = game_path(data, EVENT, bundle)
            mk = game_path(data, EVENT, bundle[:-3] + '.mk')
            joints = None
            if mk:
                for name, mb in ch.bundle_members(read(mk)):
                    if name.lower() == cid + '.alr':
                        joints = _skeleton_of(mb)
            if joints is None:
                joints = _any_skeleton(data, cid)
            if joints is None:
                continue
            for name, ab in ch.bundle_members(read(ak)):
                low = name.lower()
                if low.startswith(cid + '_') and low.endswith('.ala') and low not in seen:
                    seen.add(low)
                    out.append(('%s %s' % (cid, low[len(cid) + 1:-4]), None, joints, ch.read_tracks(ab, 0)))
    return out


def _any_skeleton(data, cid):
    p = game_path(data, PLAYER, cid, cid + '0.alr')
    if p:
        return _skeleton_of(read(p))
    for bundle, _size in scan(data)['npc'].get(cid, []):
        for name, mb in ch.bundle_members(read(game_path(data, EVENT, bundle))):
            if name.lower() == cid + '.alr':
                return _skeleton_of(mb)
    return None


# ---------------------------------------------------------------- space conversion

def _m(rows):
    return Matrix([list(r) for r in rows])


def to_blender_matrix(m, scale):
    """Game 4x4 (nested lists, column vectors) -> Blender Matrix (mirror conjugation, translation scaled)."""
    M = SWAP @ _m(m) @ SWAP
    M.translation = M.translation * scale
    return M


def to_game_matrix(M, scale):
    G = SWAP @ M @ SWAP
    G.translation = G.translation / scale
    return [list(r) for r in G]


def _pos(p, s):
    return (p[0] * s, p[2] * s, p[1] * s)


def _gpos(v, s):
    return (v[0] / s, v[2] / s, v[1] / s)


# ---------------------------------------------------------------- import

def _bone_names(joints):
    used, out = set(), []
    for i, j in enumerate(joints):
        n = j['name'] or 'j%03d' % i
        if n in used:
            n = '%s.%03d' % (n, i)
        used.add(n)
        out.append(n)
    return out


MAX_BONE = 6.0         # game units: longer bones are shortened (pointing the same way)
LEAF_BONE = 0.8        # game units: end bones (no child to point at)
MIN_BONE = 0.2


def bone_tails(joints, world, scale):
    """Tail of every bone: at its child joint (named children first; the middle of children about as far, e.g.
    both legs), else (end bones) a short stub continuing the parent bone's direction."""
    kids = {}
    for i, j in enumerate(joints):
        kids.setdefault(j['parent'], []).append(i)
    heads = [Vector(m.translation) for m in world]
    tails = [None] * len(joints)

    def tail(i, depth=0):
        if tails[i] is not None:
            return tails[i]
        head = heads[i]
        cands = [(c, (heads[c] - head).length) for c in kids.get(i, [])]
        cands = [(c, d) for c, d in cands if d > 1e-4 * scale]
        named = [(c, d) for c, d in cands if joints[c]['name']]
        cands = named or cands
        if cands:
            best = max(d for _c, d in cands)
            pts = [heads[c] for c, d in cands if d >= 0.9 * best]
            v = sum(pts, Vector((0, 0, 0))) / len(pts) - head
            if v.length > MAX_BONE * scale:
                v = v.normalized() * (MAX_BONE * scale)
        else:
            p = joints[i]['parent']
            if p is not None and depth < 256:
                pv = tail(p, depth + 1) - heads[p]
            else:
                pv = Vector((0, 0, 1))
            n = pv.normalized() if pv.length > 1e-9 else Vector((0, 0, 1))
            v = n * max(MIN_BONE * scale, min(LEAF_BONE * scale, pv.length * 0.5))
        if v.length < MIN_BONE * scale:
            v = (v.normalized() if v.length > 1e-9 else Vector((0, 0, 1))) * (MIN_BONE * scale)
        tails[i] = head + v
        return tails[i]
    for i in range(len(joints)):
        tail(i)
    return tails


def build_armature(context, name, joints, scale, coll, model=None):
    world_g = ch.world_matrices(joints)
    world = [to_blender_matrix(m, scale) for m in world_g]
    kids = {}
    for i, j in enumerate(joints):
        kids.setdefault(j['parent'], []).append(i)
    arm = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, arm)
    coll.objects.link(ob)
    ob['pd_joints'] = json.dumps([dict(t=j['t'], rot=j['rot'], scale=j['scale'], flags=j['flags'], name=j['name'],
                                       parent=j['parent'], extra=j['extra'], raw=j['raw'].hex()) for j in joints])
    ob['pd_scale'] = scale
    names = ct.bone_names(joints, model['draws'], model['materials']) if model else _bone_names(joints)
    context.view_layer.objects.active = ob
    for o in context.selected_objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    helpers = arm.collections.new('Helpers (unnamed joints)')
    named = arm.collections.new('Joints')
    ebs = []
    tails = bone_tails(joints, world, scale)
    for i, j in enumerate(joints):
        eb = arm.edit_bones.new(names[i])
        eb.head, eb.tail = Vector(world[i].translation), tails[i]
        eb.roll = 0.0
        eb['pd_index'] = i
        eb[ct.GAME_NAME] = j['name'] or ''              # the game's name (the export writes pd_joints' names)
        (named if j['name'] else helpers).assign(eb)
        ebs.append(eb)
    for i, j in enumerate(joints):
        if j['parent'] is not None:
            ebs[i].parent = ebs[j['parent']]
            ebs[i].use_connect = False
    bpy.ops.object.mode_set(mode='OBJECT')
    helpers.is_visible = False
    # orientation of each bone relative to its joint: O = W^-1 * bone matrix (rotation only)
    orient = []
    for i, nm in enumerate(names):
        b = arm.bones[nm]
        o = world[i].to_3x3().normalized().inverted() @ b.matrix_local.to_3x3()
        orient.append([list(r) for r in o])
    ob['pd_orient'] = json.dumps(orient)
    ob['pd_bones'] = json.dumps(names)
    arm.display_type = 'STICK'
    ob.show_in_front = True
    return ob


def _image(b, t, cache, label, kind, src):
    key = t['index']
    if key in cache:
        return cache[key]
    img = None
    dec = ch.decode_texture(b, t)
    if dec:
        import numpy as np
        w, h, rgba = dec
        px = np.frombuffer(rgba, np.uint8).reshape(h, w, 4)[::-1].astype(np.float32) / 255.0
        img = bpy.data.images.new('%s_%s' % (label, t['name'] or 'tex%d' % key), w, h, alpha=True)
        img.pixels.foreach_set(px.ravel())
        if kind in ('normal', 'ramp'):
            img.colorspace_settings.name = 'Non-Color'
        # the alpha is a mask of its own (colour: cut-out; normal map: shine), not transparency of the colour:
        # stored straight, the viewport and saving would darken or drop the colour under alpha 0
        img.alpha_mode = 'CHANNEL_PACKED'
        img['pd_kind'] = kind
        img.file_format = 'PNG'
        img.pack()
        img['pd_src'] = src
        img['pd_tex'] = key
        img['pd_hash'] = image_hash(img)
    cache[key] = img
    return img


def image_hash(img):
    import hashlib
    import numpy as np
    px = np.empty(len(img.pixels), np.float32)
    img.pixels.foreach_get(px)
    return hashlib.md5(np.round(px * 255).astype(np.uint8).tobytes()).hexdigest()


def character_material(name, raw, diffuse, normal, ramp=None):
    """Principled material showing the game's colour texture and its object-space normal map (game normals are
    y-up: green and blue swap for Blender; vertices with the mirror flag flip the red channel). The colour
    texture's alpha cuts out (as swbos: below about 0.75); the normal map's alpha x the PD Shine paint layer is
    the shine (Specular). ramp: the shared lighting lookup (e3a_glare01), kept in an unlinked node for the export."""
    mat = bpy.data.materials.new(name)
    try:
        mat.use_nodes = True
    except AttributeError:
        pass
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    out.location = (600, 0)
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (300, 0)
    bsdf.inputs['Roughness'].default_value = 0.7
    nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    if diffuse:
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image, tex.label, tex.name = diffuse, 'PD Diffuse', 'PD Diffuse'
        tex.location = (-400, 200)
        nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
        cut = nt.nodes.new('ShaderNodeMath')            # the game's cut-out: alpha above about 0.75 is drawn
        cut.operation = 'GREATER_THAN'
        cut.inputs[1].default_value = 0.75
        cut.label = cut.name = 'PD Cut-out'
        cut.location = (-100, 120)
        nt.links.new(tex.outputs['Alpha'], cut.inputs[0])
        nt.links.new(cut.outputs[0], bsdf.inputs['Alpha'])
        for attr_name, value in (('surface_render_method', 'DITHERED'), ('blend_method', 'CLIP')):
            try:
                setattr(mat, attr_name, value)
            except (AttributeError, TypeError):
                pass
    if ramp:
        rn = nt.nodes.new('ShaderNodeTexImage')
        rn.image, rn.label, rn.name = ramp, 'PD Lighting', 'PD Lighting'
        rn.location = (-400, 500)
    if normal:
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image, tex.label, tex.name = normal, 'PD Normal', 'PD Normal'
        tex.location = (-900, -250)
        sep = nt.nodes.new('ShaderNodeSeparateColor')
        sep.location = (-600, -250)
        nt.links.new(tex.outputs['Color'], sep.inputs['Color'])
        attr = nt.nodes.new('ShaderNodeAttribute')
        attr.attribute_name = 'pd_mirror'
        attr.location = (-900, -500)
        flip = nt.nodes.new('ShaderNodeMath')          # r' = r + m * (1 - 2r)
        flip.operation = 'MULTIPLY_ADD'
        flip.location = (-400, -400)
        two = nt.nodes.new('ShaderNodeMath')
        two.operation = 'MULTIPLY_ADD'                  # 1 - 2r = r * -2 + 1
        two.inputs[1].default_value, two.inputs[2].default_value = -2.0, 1.0
        two.location = (-600, -450)
        nt.links.new(sep.outputs['Red'], two.inputs[0])
        nt.links.new(two.outputs[0], flip.inputs[0])
        nt.links.new(attr.outputs['Fac'], flip.inputs[1])
        nt.links.new(sep.outputs['Red'], flip.inputs[2])
        comb = nt.nodes.new('ShaderNodeCombineColor')
        comb.location = (-200, -250)
        nt.links.new(flip.outputs[0], comb.inputs['Red'])
        nt.links.new(sep.outputs['Blue'], comb.inputs['Green'])
        nt.links.new(sep.outputs['Green'], comb.inputs['Blue'])
        nm = nt.nodes.new('ShaderNodeNormalMap')
        nm.space = 'OBJECT'
        nm.location = (50, -250)
        nt.links.new(comb.outputs['Color'], nm.inputs['Color'])
        nt.links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])
        shine = nt.nodes.new('ShaderNodeAttribute')     # shine = normal map alpha x the PD Shine paint layer
        shine.attribute_name = ct.SHINE
        shine.location = (-400, -650)
        mul = nt.nodes.new('ShaderNodeMath')
        mul.operation = 'MULTIPLY'
        mul.label = mul.name = 'PD Shine'
        mul.location = (-100, -600)
        nt.links.new(tex.outputs['Alpha'], mul.inputs[0])
        nt.links.new(shine.outputs['Fac'], mul.inputs[1])
        spec = bsdf.inputs.get('Specular IOR Level') or bsdf.inputs.get('Specular')
        if spec is not None:
            nt.links.new(mul.outputs[0], spec)
    mat['pd_raw'] = raw.hex()
    return mat


def _mesh_object(name, verts_b, faces, coll, parent):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts_b, [], faces)
    me.update()
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    ob.parent = parent
    return ob


def build_model(context, b, model, root_name, scale, coll, label, src, texcache, parent=None):
    """Armature + body mesh (+ hidden shadow / aura meshes) of one model run."""
    arm = build_armature(context, root_name, model['joints'], scale, coll, model)
    if parent is not None:
        arm.parent = parent
    names = ct.joint_bone_names(arm)
    texs = alr.textures(b)
    mats = {}

    def material(i):
        if i not in mats:
            m = model['materials'][i]
            slots = m['textures']
            diff = _image(b, texs[slots[0]], texcache, label, 'color', src) if slots and slots[0] is not None and slots[0] < len(texs) else None
            nrm = None
            if m['shader'].startswith('swbos') and (m['roles'] >> 4) & 0xF and len(slots) > 1 and \
                    slots[1] is not None and slots[1] < len(texs):
                nrm = _image(b, texs[slots[1]], texcache, label, 'normal', src)
            ramp = None
            if m['shader'].startswith('swbos') and len(slots) > 3 and slots[3] is not None and slots[3] < len(texs):
                ramp = _image(b, texs[slots[3]], texcache, label, 'ramp', src)
            mats[i] = character_material('%s %s' % (label, m['shader']), m['raw'], diff, nrm, ramp)
        return mats[i]

    skin_v, skin_f, skin_uv, skin_w, skin_x, skin_mat, mat_list = [], [], [], [], [], [], []
    rigid = {}
    for d in model['draws']:
        mrec = model['materials'][d['material']]
        vb = model['vbufs'][d['vbuf']]
        pos, uvs, ws, tris, nums = ch.draw_vertices(b, model, d)
        hidden = (mrec['shader'].startswith('sshadow') or mrec['shader'] == 'saura' or vb['format'] in NO_UV_FORMATS
                  or (d['joint'] < len(model['joints']) and model['joints'][d['joint']]['flags'] & 0x800))
        if vb['format'] in ch.SKINNED_FORMATS or not hidden:
            # skinned body, or a visible rigid part (bosses): rigid parts are bound fully to their joint
            base = len(skin_v)
            skin_v += [_pos(p, scale) for p in pos]
            skin_uv += [(u, 1.0 - v) for u, v in uvs]
            skin_w += ws
            skin_x += ch.vertex_extras(b, model, d, nums)
            mt = material(d['material'])
            if mt not in mat_list:
                mat_list.append(mt)
            for t in tris:
                skin_f.append(tuple(base + k for k in cv.flip_winding(t)))
                skin_mat.append(mat_list.index(mt))
        else:
            kind = 'shadow' if mrec['shader'].startswith('sshadow') else 'aura' if mrec['shader'] == 'saura' else \
                'hidden %s' % mrec['shader']
            r = rigid.setdefault(kind, dict(v=[], f=[], j=[], extra=[], material=d['material'], format=vb['format']))
            base = len(r['v'])
            r['v'] += [_pos(p, scale) for p in pos]
            r['j'] += [d['joint']] * len(pos)
            rb = alr.header(b)['resource_offset'] + vb['offset']
            for n in nums:
                r['extra'].append(tuple(b[rb + n * vb['vertex_size'] + 12:rb + n * vb['vertex_size'] + 16]))
            r['f'] += [tuple(base + k for k in cv.flip_winding(t)) for t in tris]
    out = []
    if skin_v:
        body = _mesh_object(root_name + ' mesh', skin_v, skin_f, coll, arm)
        me = body.data
        uv = me.uv_layers.new(name='UVMap')
        for poly in me.polygons:
            for li in poly.loop_indices:
                uv.data[li].uv = skin_uv[me.loops[li].vertex_index]
        for mt in mat_list:
            me.materials.append(mt)
        me.polygons.foreach_set('material_index', skin_mat)
        a = me.attributes.new('pd_mirror', 'FLOAT', 'POINT')
        a.data.foreach_set('value', [x[0] / 255.0 for x in skin_x])
        shine = me.color_attributes.new(ct.SHINE, 'BYTE_COLOR', 'POINT')   # vertex paint: the shine
        for k, x in enumerate(skin_x):
            v = x[1] / 255.0
            shine.data[k].color_srgb = (v, v, v, 1.0)
        me.color_attributes.active_color = shine
        _weights(body, skin_w, names)
        mod = body.modifiers.new('Armature', 'ARMATURE')
        mod.object = arm
        out.append(body)
    for kind, r in rigid.items():
        o = _mesh_object('%s %s' % (root_name, kind), r['v'], r['f'], coll, arm)
        o['pd_rigid'] = kind
        o['pd_format'] = r['format']
        o['pd_raw'] = model['materials'][r['material']]['raw'].hex()
        a = o.data.attributes.new('pd_extra', 'INT', 'POINT')
        a.data.foreach_set('value', [struct.unpack('<i', bytes(e))[0] for e in r['extra']])
        _weights(o, [[(j, 1.0)] for j in r['j']], names)
        mod = o.modifiers.new('Armature', 'ARMATURE')
        mod.object = arm
        o.hide_set(True)
        o.hide_render = True
        out.append(o)
    arm['pd_draw_joint'] = next((d['joint'] for d in model['draws']
                                 if model['vbufs'][d['vbuf']]['format'] in ch.SKINNED_FORMATS), 0)
    arm['pd_extra_chunks'] = json.dumps([raw.hex() for _t, raw in model['extra']])
    arm['pd_mat_header'] = model.get('mat_header', b'\0\0\0\0').hex()
    arm['pd_vbuf_masks'] = json.dumps({str(vb['format']): struct.unpack_from('<I', vb['raw'], 4)[0]
                                       for vb in model['vbufs']})
    return arm, out


def _weights(ob, weights, names):
    groups = {}
    for v, ws in enumerate(weights):
        for j, w in ws:
            if j < len(names):
                groups.setdefault(j, []).append((v, w))
    for j in sorted(groups):
        vg = ob.vertex_groups.new(name=names[j])
        by_w = {}
        for v, w in groups[j]:
            by_w.setdefault(round(w, 4), []).append(v)
        for w, vs in by_w.items():
            vg.add(vs, w, 'REPLACE')


def import_character(context, data, key, variant=0, scale=cv.DEFAULT_SCALE, animations=True):
    b, cid, src = load_model_bytes(data, key, variant)
    name = ch.NAMES.get(cid, cid)
    coll = bpy.data.collections.new('%s (%s)' % (name, cid))
    context.scene.collection.children.link(coll)
    coll['pd_character'] = cid
    h = alr.header(b)
    roots = ch.model_roots(b)
    texcache = {}
    main = None
    for k, r in enumerate(roots):
        model = ch.read_model(b, h['roots'][r])
        label = cid if k == 0 else '%s part%d' % (cid, k)
        arm, _objs = build_model(context, b, model, label, scale, coll, cid, src, texcache, parent=main)
        arm['pd_root'] = k
        if main is None:
            main = arm
            main['pd_character'] = cid
            main['pd_source'] = src
            main['pd_key'] = key
            main['pd_missing'] = missing_joints(model['joints'])
            try:
                main['pd_hitbox'] = list(_hitbox_for(data, cid, b))
            except Exception:
                main['pd_hitbox'] = [180, 100, 50, 90]
        else:
            pin_cloth(arm, main)
    context.scene.render.fps = ch.FPS
    context.scene.render.fps_base = 1.0
    n = 0
    if animations and key.startswith('B:'):
        n = load_animation_set(context, main, data, key)
    return main, n


def pin_cloth(sub, main):
    """Make a cloth / prop armature follow its pin bone on the body (clcNN hangs from clpNN; the game swings the
    cloth with physics, Blender only carries it along)."""
    game = [j['name'] for j in json.loads(sub['pd_joints'])]
    root = next((n for n in game if n and n.startswith('clc')), None)
    if root is None:
        return
    pin = 'clp' + root[3:5]
    main_game = [j['name'] for j in json.loads(main['pd_joints'])]
    if pin not in main_game:
        return
    bone = main.data.bones.get(ct.joint_bone_names(main)[main_game.index(pin)])
    if bone is None:
        return
    con = sub.constraints.new('CHILD_OF')
    con.target = main
    con.subtarget = bone.name
    con.inverse_matrix = (main.matrix_world @ bone.matrix_local).inverted()
    con.name = 'PD pin %s' % bone.name


# ---------------------------------------------------------------- animations

def armature_joints(arm):
    return [dict(t=tuple(j['t']), rot=tuple(j['rot']), scale=tuple(j['scale']), flags=j['flags'], name=j['name'],
                 parent=j['parent'], extra=tuple(j['extra']), raw=bytes.fromhex(j['raw']))
            for j in json.loads(arm['pd_joints'])]


def _new_action(arm, name):
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    slot = act.slots.new(id_type='OBJECT', name=arm.name)
    layer = act.layers.new('Layer')
    strip = layer.strips.new(type='KEYFRAME')
    bag = strip.channelbag(slot, ensure=True)
    return act, slot, bag


def _fcurve(bag, path, index, group):
    fc = bag.fcurves.new(path, index=index)
    try:
        g = bag.groups.get(group) or bag.groups.new(group)
        fc.group = g
    except (AttributeError, TypeError, RuntimeError):
        pass
    return fc


def _set_keys(fc, frames, values):
    fc.keyframe_points.add(len(frames))
    co = [0.0] * (2 * len(frames))
    co[0::2] = frames
    co[1::2] = values
    fc.keyframe_points.foreach_set('co', co)
    fc.keyframe_points.foreach_set('interpolation', [1] * len(frames))      # LINEAR
    fc.update()


def key_to_basis(jt, rest_inv, O, Oi, scale, t, q, s):
    """A game key (local translation, quaternion, scale; None = the rest value) -> pose-bone basis
    (location, rotation quaternion, scale)."""
    lt = t if t is not None else jt['t']
    lq = q if q is not None else ch._q_from_euler(*jt['rot'])
    ls = s if s is not None else jt['scale']
    La = to_blender_matrix(ch.quat_matrix(lq, lt, ls), scale)
    return (Oi @ rest_inv @ La @ O).decompose()


def basis_to_key(rest, O, Oi, scale, loc, rot, sc):
    """Pose-bone basis -> game local (translation, quaternion (w, x, y, z), scale)."""
    rot = rot.normalized()
    basis = Matrix.LocRotScale(loc, rot, sc)
    G = to_game_matrix(rest @ O @ basis @ Oi, scale)
    gm = Matrix([r[:3] for r in G[:3]])
    q = gm.normalized().to_quaternion()
    return (G[0][3], G[1][3], G[2][3]), (q.w, q.x, q.y, q.z), tuple(gm.to_scale())


def keys_to_action(arm, name, keys, length, joints):
    """Game keys {joint: [(frame, t, q, s)]} -> an action on the armature's pose bones."""
    scale = arm['pd_scale']
    names = ct.joint_bone_names(arm)
    orient = [Matrix(o).to_4x4() for o in json.loads(arm['pd_orient'])]
    act, slot, bag = _new_action(arm, name)
    for j, ks in keys.items():
        if j >= len(names):
            continue
        jt = joints[j]
        rest = to_blender_matrix(ch.local_matrix(jt['t'], jt['rot'], jt['scale']), scale)
        rest_inv = rest.inverted_safe()
        O, Oi = orient[j], orient[j].inverted()
        frames, locs, rots, scs = [], [], [], []
        prev = None
        for f, t, q, s in ks:
            loc, rot, sc = key_to_basis(jt, rest_inv, O, Oi, scale, t, q, s)
            if prev is not None and rot.dot(prev) < 0:
                rot = -rot
            prev = rot
            frames.append(float(f))
            locs.append(loc)
            rots.append(rot)
            scs.append(sc)
        path = 'pose.bones["%s"]' % names[j].replace('"', '\\"')
        for k in range(3):
            _set_keys(_fcurve(bag, path + '.location', k, names[j]), frames, [v[k] for v in locs])
        for k in range(4):
            _set_keys(_fcurve(bag, path + '.rotation_quaternion', k, names[j]), frames, [v[k] for v in rots])
        if any(s is not None for _f, _t, _q, s in ks):
            for k in range(3):
                _set_keys(_fcurve(bag, path + '.scale', k, names[j]), frames, [v[k] for v in scs])
    act.frame_range = (0.0, max(1.0, float(length)))
    act.use_frame_range = True
    return act, slot


def load_animation_set(context, arm, data, set_key, prefix=None):
    """Load every clip of a set onto the armature (moved onto its skeleton when it is another character's).
    Returns the number of actions made."""
    dst = armature_joints(arm)
    clips = animation_set(data, set_key)
    label = prefix or set_key.partition(':')[2]
    n = 0
    first = None
    for name, motion, src_joints, tracks in clips:
        same = len(src_joints) == len(dst) and all(a['name'] == b_['name'] and a['parent'] == b_['parent']
                                                   for a, b_ in zip(src_joints, dst))
        mapping = {i: i for i in range(len(dst))} if same else ch.match_joints(src_joints, dst)
        keys, length = ch.bake_clip(src_joints, tracks, None if same else dst, None if same else mapping)
        if same:
            keys = {j: k for j, k in keys.items() if j < len(dst)}
        act, slot = keys_to_action(arm, '%s: %s' % (arm.name, name), keys, length, dst)
        act['pd_set'] = set_key
        act['pd_motion'] = -1 if motion is None else motion
        act['pd_armature'] = arm.name
        act['pd_clip'] = name
        if first is None:
            first = (act, slot)
        n += 1
    arm['pd_anim_set'] = set_key
    if first:
        play(arm, first[0])
    return n


def play(arm, act):
    ad = arm.animation_data or arm.animation_data_create()
    ad.action = act
    try:
        ad.action_slot = act.slots[0]
    except (AttributeError, IndexError, TypeError):
        pass
    for pb in arm.pose.bones:
        pb.rotation_mode = 'QUATERNION'
    s = bpy.context.scene
    s.frame_start, s.frame_end = 0, int(round(act.frame_range[1]))
    s.frame_set(0)


def character_actions(arm, set_key=None):
    out = [a for a in bpy.data.actions if a.get('pd_armature') == arm.name and
           (set_key is None or a.get('pd_set') == set_key)]
    return sorted(out, key=lambda a: (a.get('pd_set', ''), a.get('pd_motion', -1), a.name))


def action_keys(arm, act, joints):
    """An action back to game keys {joint: [(frame, t, q, s)]} (every frame of its range)."""
    scale = arm['pd_scale']
    names = ct.joint_bone_names(arm)
    orient = [Matrix(o).to_4x4() for o in json.loads(arm['pd_orient'])]
    curves = {}
    for bag in _channelbags(act):
        for fc in bag.fcurves:
            curves[(fc.data_path, fc.array_index)] = fc
    f0, f1 = act.frame_range
    frames = list(range(int(math.floor(f0)), int(math.ceil(f1)) + 1))
    out = {}
    for j, nm in enumerate(names):
        path = 'pose.bones["%s"]' % nm.replace('"', '\\"')
        loc_c = [curves.get((path + '.location', k)) for k in range(3)]
        rot_c = [curves.get((path + '.rotation_quaternion', k)) for k in range(4)]
        sc_c = [curves.get((path + '.scale', k)) for k in range(3)]
        if not any(loc_c + rot_c + sc_c):
            continue
        jt = joints[j]
        rest = to_blender_matrix(ch.local_matrix(jt['t'], jt['rot'], jt['scale']), scale)
        O, Oi = orient[j], orient[j].inverted()
        keys = []
        moves = any(loc_c)
        scales = any(sc_c)
        for f in frames:
            loc = Vector([c.evaluate(f) if c else 0.0 for c in loc_c])
            rot = Quaternion([c.evaluate(f) if c else (1.0 if k == 0 else 0.0) for k, c in enumerate(rot_c)])
            sc = Vector([c.evaluate(f) if c else 1.0 for c in sc_c])
            t, q, gs = basis_to_key(rest, O, Oi, scale, loc, rot, sc)
            keys.append((f - frames[0], t if moves and _moved(t, jt["t"]) else None, q,
                         tuple(gs) if scales else None))
        if all(k[1] is None for k in keys):
            keys = [(f, None, q, s) for f, _t, q, s in keys]
        elif any(k[1] is None for k in keys):
            keys = [(f, t if t is not None else tuple(jt['t']), q, s) for f, t, q, s in keys]
        out[j] = keys
    return out, frames[-1] - frames[0]


def _moved(t, rest, tol=1e-3):
    return any(abs(a - b) > tol for a, b in zip(t, rest))


def _channelbags(act):
    try:
        for layer in act.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    yield bag
    except AttributeError:
        return


# ---------------------------------------------------------------- export

class CharacterExportError(Exception):
    pass


def _image_rgba(img):
    import numpy as np
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    return w, h, (np.clip(np.round(px.reshape(h, w, 4)[::-1] * 255), 0, 255)).astype(np.uint8).tobytes()


def _original_texture(img):
    """The game's own encoded bytes of an imported image that was not changed."""
    try:
        if img.get('pd_hash') != image_hash(img):
            return None
        src, index = img['pd_src'], int(img['pd_tex'])
    except (KeyError, TypeError, ValueError):
        return None
    path, _sep, member = src.partition('|')
    if not os.path.isfile(path):
        return None
    b = read(path)
    if member:
        b = next((mb for n, mb in ch.bundle_members(b) if n == member), None)
        if b is None:
            return None
    t = alr.textures(b)[index]
    return dict(name=t['name'], raw_format=t['raw_format'], width=t['width'], height=t['height'],
                mips=max(1, t['mips']), data=ch.texture_bytes(b, t))


def _material_textures(mat):
    """(colour, normal map, lighting lookup) images of a material."""
    if not mat or not mat.node_tree:
        return None, None, None
    nodes = mat.node_tree.nodes
    d = nodes.get('PD Diffuse')
    n = nodes.get('PD Normal')
    r = nodes.get('PD Lighting')
    if d is None:
        d = next((x for x in nodes if x.type == 'TEX_IMAGE' and x.image and x.name not in ('PD Normal', 'PD Lighting')),
                 None)
    return (d.image if d else None), (n.image if n else None), (r.image if r and r.image else None)


RAMP = 'e3a_glare01'


def _source_texture(arm, name):
    """The game's encoded bytes of a texture named `name` in the character's own source file (for characters
    loaded before the lighting lookup was kept in their materials)."""
    src = arm.get('pd_source') or ''
    path, _sep, member = src.partition('|')
    if not path or not os.path.isfile(path):
        return None
    b = read(path)
    if member:
        b = next((mb for n, mb in ch.bundle_members(b) if n == member), None)
        if b is None:
            return None
    t = next((t for t in alr.textures(b) if t['name'] == name), None)
    if t is None:
        return None
    return dict(name=t['name'], raw_format=t['raw_format'], width=t['width'], height=t['height'],
                mips=max(1, t['mips']), data=ch.texture_bytes(b, t))


def gather_model(arm, textures, tex_index):
    """char_build model dict from an armature and its child meshes; textures appended to `textures`."""
    scale = arm['pd_scale']
    joints = armature_joints(arm)
    names = ct.joint_bone_names(arm)
    by_name = {n: i for i, n in enumerate(names)}
    materials, mat_index = [], {}

    def tex_slot(img, kind):
        if img is None:
            return 0
        if img.name not in tex_index:
            enc = _original_texture(img)
            if enc is None:
                w, h, rgba = _image_rgba(img)
                enc = dict(name=img.name[-12:], rgba=(w, h, rgba), kind=kind)
            tex_index[img.name] = len(textures)
            textures.append(enc)
        return tex_index[img.name]

    def ramp_slot(img):
        """The lighting lookup (slots 2 and 3): the material's, else the source file's e3a_glare01."""
        if img is not None:
            return tex_slot(img, 'color')
        if '__ramp__' not in tex_index:
            enc = _source_texture(arm.parent if arm.parent and arm.parent.get('pd_source') else arm, RAMP)
            if enc is None:
                return 0
            tex_index['__ramp__'] = len(textures)
            textures.append(enc)
        return tex_index['__ramp__']

    def material(mat, raw_hex=None):
        key = mat.name if mat else raw_hex
        if key in mat_index:
            return mat_index[key]
        raw = bytearray(bytes.fromhex(raw_hex or (mat.get('pd_raw') if mat else '') or SWBOS))
        if mat is not None and not alr.decode_text(*struct.unpack_from('<2I', raw, 0)).startswith('swbos'):
            raw = bytearray(bytes.fromhex(SWBOS))         # bosses' rigid shaders: drawn skinned on export
        if mat is not None:
            d, n, r = _material_textures(mat)
            ramp = ramp_slot(r)
            slots = [tex_slot(d, 'color'), tex_slot(n, 'normal') if n else 0, ramp, ramp]
            roles = 0x0001 | (0x0020 if n else 0)
            struct.pack_into('<H4H', raw, 0x16, roles, *slots)
        raw[0x12] = len(materials) & 0xFF
        mat_index[key] = len(materials)
        materials.append(bytes(raw))
        return mat_index[key]

    skin, rigid = [], []
    for ob in arm.children:
        if ob.type != 'MESH':
            continue
        groups = {g.index: by_name.get(g.name) for g in ob.vertex_groups}
        me = ob.data
        if ob.get('pd_rigid'):
            fmt = int(ob['pd_format'])
            if fmt not in cb.RIGID_STRIDE:
                continue                         # position-only boss meshes: not written
            extra = me.attributes.get('pd_extra')
            bind = ch.world_matrices(joints)
            parts = {}
            for poly in me.polygons:
                vs = list(poly.vertices)
                for k in range(1, len(vs) - 1):
                    tri = (vs[0], vs[k], vs[k + 1])
                    js = [_rigid_joint(me.vertices[v], groups) for v in tri]
                    parts.setdefault(js[0], []).append(cv.flip_winding(tri))
            for j, tris in parts.items():
                used = sorted({v for t in tris for v in t})
                remap = {v: k for k, v in enumerate(used)}
                verts = []
                for v in used:
                    p = _gpos(me.vertices[v].co, scale)
                    if fmt == 0x07:
                        if extra and v < len(extra.data):
                            e = _unpack_normal(extra.data[v].value, bind[j])
                        else:
                            n = me.vertices[v].normal
                            e = (n[0], n[2], n[1])
                    else:
                        e = tuple(struct.pack('<i', extra.data[v].value)) if extra and v < len(extra.data) else (255, 255, 255, 255)
                    verts.append((p, e))
                rigid.append(dict(material=material(None, ob['pd_raw']), format=fmt, joint=j,
                                  verts=verts, tris=[tuple(remap[v] for v in t) for t in tris]))
            continue
        tmp = None          # rest pose: the mesh itself (apply other modifiers before exporting)
        mesh = me
        mesh.calc_loop_triangles()
        uv = mesh.uv_layers.active
        mir = mesh.attributes.get('pd_mirror')
        shine_of = ct.shine_reader(mesh)
        per_mat = {}
        for tri in mesh.loop_triangles:
            per_mat.setdefault(tri.material_index, []).append(tri)
        for mi, tris in per_mat.items():
            mat = ob.material_slots[mi].material if mi < len(ob.material_slots) else None
            m_idx = material(mat)
            vmap, verts, out_tris = {}, [], []
            for tri in tris:
                corners = []
                for li, v in zip(tri.loops, tri.vertices):
                    u = tuple(uv.data[li].uv) if uv else (0.0, 0.0)
                    key = (v, round(u[0], 5), round(u[1], 5))
                    if key not in vmap:
                        vert = mesh.vertices[v]
                        ws = [(groups.get(g.group), g.weight) for g in vert.groups if groups.get(g.group) is not None
                              and g.weight > 0]
                        ws = sorted(ws, key=lambda x: -x[1])[:2]
                        if not ws:
                            raise CharacterExportError('%s: vertex %d has no weight on a bone' % (ob.name, v))
                        vmap[key] = len(verts)
                        verts.append((_gpos(vert.co, scale), (u[0], 1.0 - u[1]), ws,
                                      int(round((mir.data[v].value if mir else 0.0) * 255)),
                                      int(round(max(0.0, min(1.0, shine_of(v))) * 255))))
                    corners.append(vmap[key])
                out_tris.append(cv.flip_winding(tuple(corners)))
            skin.append(dict(material=m_idx, verts=verts, tris=out_tris))
        if tmp:
            bpy.data.meshes.remove(tmp)
    return dict(joints=joints, materials=materials, mat_header=bytes.fromhex(arm.get('pd_mat_header', '00000000')),
                vbuf_masks={int(k): v for k, v in json.loads(arm.get('pd_vbuf_masks', '{}')).items()},
                skin=skin, rigid=rigid, draw_joint=int(arm.get('pd_draw_joint', 0)),
                extra=[bytes.fromhex(x) for x in json.loads(arm.get('pd_extra_chunks', '[]'))])


def _unpack_normal(value, bind):
    """A shadow vertex's stored normal (packed 11-11-10, in its joint's space) -> model space."""
    v = value & 0xFFFFFFFF
    nx = ((v & 0x7FF) ^ 0x400) - 0x400
    ny = (((v >> 11) & 0x7FF) ^ 0x400) - 0x400
    nz = (((v >> 22) & 0x3FF) ^ 0x200) - 0x200
    n = (nx / 1023.0, ny / 1023.0, nz / 511.0)
    return tuple(bind[r][0] * n[0] + bind[r][1] * n[1] + bind[r][2] * n[2] for r in range(3))


def _rigid_joint(vert, groups):
    best = max(vert.groups, key=lambda g: g.weight, default=None)
    if best is None or groups.get(best.group) is None:
        raise CharacterExportError('a shadow / aura vertex has no bone')
    return groups[best.group]


# the game's skinned body material (pc00a0's swbos entry) for meshes without one
SWBOS = ('c8e815b600000000000000002d0800001110000000112100000001000000000000000000000000000000000000000000000000'
         'ff7f7f7f140000000000000000000000000000000000000000')


def check_compatible(arm, data, target, experimental=False):
    """Problems that stop an export over `target` (a battle character id): [str]."""
    problems = []
    joints = armature_joints(arm)
    names = {j['name'] for j in joints}
    missing = [n for n in REQUIRED_JOINTS if n not in names and n not in ADDABLE_JOINTS]
    if missing and not experimental:
        problems.append('the skeleton lacks joints the game looks up by name: %s' % ', '.join(missing))
    if len(joints) > 256:
        problems.append('%d joints (a draw palette stores joint numbers as bytes: at most 256)' % len(joints))
    have = {a.get('pd_motion') for a in character_actions(arm, arm.get('pd_anim_set'))}
    need = list(range(ch.BATTLE_MOTIONS)) + [ch.EXMOT_BASE + k for k in range(EXMOT)]
    lack = [m for m in need if m not in have]
    if lack:
        problems.append('the loaded animation set "%s" lacks %d of the %d motions the game plays (load a '
                        'Battle animation set first): %s' % (arm.get('pd_anim_set', 'none'), len(lack), len(need),
                                                            _ranges(lack)))
    if not game_path(bpy.path.abspath(data), PLAYER, target, target + '0.alr'):
        problems.append('Player\\%s\\%s0.alr not found in the game folder' % (target, target))
    return problems


def add_missing_joints(joints, donor, wanted=ADDABLE_JOINTS):
    """Append the `wanted` joints the skeleton lacks, copied from `donor` (the replaced character), under the
    matching parent (a donor parent that is missing too is added first). Existing joint numbers do not change.
    Returns the names added."""
    added = []

    def add(di, depth=0):
        name = donor[di]['name']
        if name and any(j['name'] == name for j in joints):
            return next(i for i, j in enumerate(joints) if j['name'] == name)
        inv = {s_: d for d, s_ in ch.match_joints(donor, joints).items()}
        p = donor[di]['parent']
        parent = inv.get(p) if p is not None else None
        if p is not None and parent is None and donor[p]['name'] and depth < 64:
            parent = add(p, depth + 1)
        j = dict(donor[di])
        j['parent'] = parent
        joints.append(j)
        added.append(name or 'j%03d' % di)
        return len(joints) - 1
    for name in wanted:
        if any(j['name'] == name for j in joints):
            continue
        di = next((i for i, j in enumerate(donor) if j['name'] == name), None)
        if di is not None:
            add(di)
    return added


def _ranges(nums):
    out, start, prev = [], None, None
    for n in sorted(nums):
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append('%d' % start if start == prev else '%d-%d' % (start, prev))
            start = prev = n
    if start is not None:
        out.append('%d' % start if start == prev else '%d-%d' % (start, prev))
    return ', '.join(out)


def export_character(context, arm, data, target, variants=(0, 1, 2, 3), move='AUTO', voice='KEEP', box='AUTO',
                     experimental=False):
    """Write the character over Player\\<target>\\<target>N.alr (the variants given) and exmot0..5.ala, the game's
    own files saved first in Player\\<target>\\pd_addon_backup. Returns a report string."""
    data = bpy.path.abspath(data)
    problems = check_compatible(arm, data, target, experimental)
    if problems:
        raise CharacterExportError('; '.join(problems))
    base = read(game_path(data, PLAYER, target, target + '0.alr'))
    textures, tex_index = [], {}
    models = [gather_model(arm, textures, tex_index)]
    for sub in sorted((o for o in arm.children if o.type == 'ARMATURE'), key=lambda o: o.get('pd_root', 99)):
        models.append(gather_model(sub, textures, tex_index))
    joints = models[0]['joints']
    added = add_missing_joints(joints, _skeleton_of(base), REQUIRED_JOINTS if experimental else ADDABLE_JOINTS)
    acts = {a['pd_motion']: a for a in character_actions(arm, arm.get('pd_anim_set'))}
    anims = {}
    for m in range(ch.BATTLE_MOTIONS):
        keys, length = action_keys(arm, acts[m], joints)
        anims[m] = ch.clip_tracks(keys, length)
    out = cb.build(base[:0x20], textures, models, anims, n_anim_runs=ch.BATTLE_MOTIONS)
    folder = game_path(data, PLAYER, target, original=False)
    bdir = os.path.join(folder, BACKUP_DIR)
    os.makedirs(bdir, exist_ok=True)
    written = []
    files = [(target + '%d.alr' % v, out) for v in variants]
    ex_len = []
    for k in range(EXMOT):
        keys, length = action_keys(arm, acts[ch.EXMOT_BASE + k], joints)
        ex_len.append(length)
        files.append(('exmot%d.ala' % k, cb.encode_run(ch.clip_tracks(keys, length))))
    for fn, payload in files:
        dst = os.path.join(folder, fn)
        if os.path.isfile(dst) and not os.path.isfile(os.path.join(bdir, fn)):
            with open(dst, 'rb') as f, open(os.path.join(bdir, fn), 'wb') as g:
                g.write(f.read())
        with open(dst, 'wb') as f:
            f.write(payload)
        written.append(fn)
    mv = set_movement(arm, data) if move == 'AUTO' else None if move == 'KEEP' else int(move)
    anim_set = str(arm.get('pd_anim_set', ''))
    src = charaset_record(data, anim_set[2:], original=True) if anim_set.startswith('B:') else None
    patched = patch_charaset(data, target, move=mv, voice=None if voice == 'KEEP' else voice, exmot=ex_len,
                             exmot_tail=src['exmot'] if src else None,
                             box=character_hitbox(arm))
    rec = charaset_record(data, target)
    extra = ''
    if added:
        extra += '; added joints %s' % ', '.join(added)
    if arm.get('pd_missing'):
        extra += '; POSSIBLY BROKEN: the original skeleton lacks %s' % ', '.join(arm['pd_missing'])
    if experimental:
        extra += '; EXPERIMENTAL export'
    if patched and rec:
        extra += '; charaset: %s, voice %s, height %.1f' % ('cartwheel' if rec['move'] == cs.CARTWHEEL else 'jump',
                                                            rec['voice'], rec['height'] / 10.0)
    return 'wrote %s (%d KB each model file) into Player\\%s%s' % (', '.join(written), len(out) // 1024, target,
                                                                   extra)


# ---------------------------------------------------------------- charaset (voice, jump or cartwheel)

def charaset_paths(data, original=False):
    data = bpy.path.abspath(data)
    return [p for p in (game_path(data, 'setup', 'charaset', fn, original=original) for fn in cs.FILES) if p]


def charaset_record(data, model, original=False):
    paths = charaset_paths(data, original)
    return cs.record_of(read(paths[0]), model) if paths else None


def voice_items(data):
    paths = charaset_paths(data, original=True)
    if not paths:
        return []
    names = sorted(cs.voices(read(paths[0])), key=str.lower)
    return [(n, n[len('BattleVo_'):-4] if n.startswith('BattleVo_') else n, 'Voice and sound bank Sound\\%s'
             % n.replace('.bin', '_en.bin')) for n in names]


MIN_CAPSULE = 180      # tenths: no fighter smaller than the standard 18 units (no competitive advantage)


def character_hitbox(arm):
    """The loaded character's own body collider and hit volume (charaset record of its model when it has one,
    else from the mesh height), in tenths of a game unit; the capsule never below MIN_CAPSULE."""
    box = arm.get('pd_hitbox')
    if not box:
        return None
    box = [int(x) for x in box]
    box[0] = max(box[0], MIN_CAPSULE)
    return tuple(box)


def _hitbox_for(data, cid, b):
    paths = charaset_paths(data, original=True)
    if paths:
        box = cs.hitbox(read(paths[0]), cid)
        if box:
            return box
    tex, models, _ = ch.read_ir(b)
    ys = [v[0][1] for p in models[0]['skin'] for v in p['verts']] if models else []
    height = int(max(ys) - min(ys)) * 10 if ys else 180
    return (height, 100, 50, 90)


def set_movement(arm, data):
    """Jump (750) or cartwheel (751) of the character whose battle set is loaded, else None."""
    key = arm.get('pd_anim_set', '')
    if not key.startswith('B:'):
        return None
    r = charaset_record(data, key[2:], original=True)
    return r['move'] if r else None


def patch_charaset(data, target, move=None, voice=None, exmot=None, box=None, exmot_tail=None):
    """Change the target's record in both charaset files (the game's own copies saved first)."""
    done = []
    for path in charaset_paths(data):
        folder = os.path.dirname(path)
        bdir = os.path.join(folder, BACKUP_DIR)
        os.makedirs(bdir, exist_ok=True)
        fn = os.path.basename(path)
        if not os.path.isfile(os.path.join(bdir, fn)):
            with open(os.path.join(bdir, fn), 'wb') as g:
                g.write(read(path))
        b = read(path)
        rec = cs.record_of(b, target)
        ex = None
        if exmot is not None and rec is not None:
            # +0x40 is not the clip length: it is the length L of the end range of the extra motion that the
            # fighter keeps playing while the pose is held (the call that reads it plays the range
            # (length - L, length); L = 0: the clip holds its last frame). In every record of the game it is far
            # shorter than the clip (pc05a: 50 and 40 for clips of 176 and 154 frames). Writing the clip length
            # made the held range the whole clip. Keep the value of the record the animations came from
            # (exmot_tail), else the target's own, never longer than the new clip.
            tail = exmot_tail or rec['exmot']
            ex = [min(int(tail[k]), int(round(exmot[k]))) if rec['exmot'][k] and tail[k] > 0 else 0 for k in range(6)]
        with open(path, 'wb') as f:
            f.write(cs.patch(b, target, move=move, voice=voice, exmot=ex, box=box))
        done.append(fn)
    return done


def restore_charaset_record(data, target):
    """Put the target's charaset record back from the backup (other records keep their changes)."""
    done = []
    for path in charaset_paths(data):
        bpath = os.path.join(os.path.dirname(path), BACKUP_DIR, os.path.basename(path))
        if not os.path.isfile(bpath):
            continue
        orig, cur = read(bpath), bytearray(read(path))
        r = cs.record_of(orig, target)
        if r is None:
            continue
        at = 16 + r['index'] * cs.RECORD
        cur[at:at + cs.RECORD] = orig[at:at + cs.RECORD]
        with open(path, 'wb') as f:
            f.write(bytes(cur))
        done.append(os.path.basename(path))
    return done


def restore_character(data, target):
    data = bpy.path.abspath(data)
    folder = game_path(data, PLAYER, target, original=False)
    bdir = os.path.join(folder, BACKUP_DIR) if folder else None
    if not bdir or not os.path.isdir(bdir):
        return []
    done = []
    for fn in os.listdir(bdir):
        with open(os.path.join(bdir, fn), 'rb') as f, open(os.path.join(folder, fn), 'wb') as g:
            g.write(f.read())
        done.append(fn)
    done += ['charaset record (%s)' % fn for fn in restore_charaset_record(data, target)]
    return done
