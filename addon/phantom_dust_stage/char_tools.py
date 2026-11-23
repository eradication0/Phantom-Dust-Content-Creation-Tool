"""Character tools: readable bone names, texture export / extract / import, the shine paint layer and the
export check (Characters panel).

What a character's materials hold (every battle character, shader swbos, read from all Player\\*.alr and the shader):
  slot 0  colour texture (DXT1): RGB colour; alpha cuts out (the shader discards where it is below about 0.75).
  slot 1  normal map (model space; A1R5G5B5 or DXT3): RGB the normal; ALPHA = shine mask (specular strength),
          times the vertex's shine (vertex colour byte 3, the "PD Shine" paint layer here).
  slot 3  e3a_glare01, a lighting lookup shared by all characters (looked up by the normal: the sun's light and
          the rim glow). Slot 2 holds it too but swbos does not sample it.
Bone names: the game names its main joints with romanised Japanese (kata = shoulder, ninou = upper arm, tekubi =
wrist, momo = thigh...) and leaves about 60 % of the joints unnamed (shadow / aura hull anchors, mesh anchors,
twist helpers). Blender gets readable names; the game names stay in the armature's joint list (pd_joints) and in
each bone's pd_name, and the export writes those, whatever the bones are called in Blender.
"""
import json
import os

import bpy

# readable names for the joints the game names (side suffix .L / .R lets Blender mirror)
FRIENDLY = {
    'body1': 'Spine', 'body2': 'Chest', 'neck': 'Neck', 'head': 'Head', 'hip': 'Hips',
    'kata': 'Shoulder', 'ninou': 'UpperArm', 'nino2': 'UpperArmTwist', 'tekub': 'Forearm', 'teku2': 'ForearmTwist',
    'hand': 'Hand', 'fin01': 'Finger1', 'fin02': 'Finger2', 'fin03': 'Finger3', 'addha': 'HandAttach',
    'sword': 'Weapon', 'momo': 'Thigh', 'knee': 'Shin', 'foot': 'Foot', 'shoes': 'Toe', 'kick': 'KickPoint',
    'alpha': 'Alpha_Effects', 'camera': 'Camera', 'hikari': 'Glow', 'rotate': 'Rotate',
}
PREFIX = (('colf', 'ColliderF_'), ('colp', 'ColliderPin_'), ('col', 'Collider_'), ('clc', 'ClothChain_'),
          ('clp', 'ClothPin_'), ('cl', 'Cloth_'))
GAME_NAME = 'pd_name'


def _side_split(game):
    """'lkata' -> ('.L', 'kata'); names without a side -> ('', name)."""
    if len(game) > 1 and game[0] in 'lr' and game[1:] in FRIENDLY:
        return ('.L' if game[0] == 'l' else '.R'), game[1:]
    return '', game


def friendly(game):
    side, stem = _side_split(game)
    if stem in FRIENDLY:
        return FRIENDLY[stem] + side
    for p, nice in PREFIX:
        if game.startswith(p) and game[len(p):].isdigit():
            return nice + game[len(p):]
    return game


def bone_names(joints, draws=None, materials=None):
    """Blender names for a skeleton's joints. draws/materials (the model's) tell what the unnamed joints carry:
    shadow-volume and aura-hull anchors, the skinned meshes' anchors; the rest are named after their nearest
    named ancestor (twist helpers) or as roots."""
    kind = {}
    for d in draws or ():
        sh = materials[d['material']]['shader'] if materials and d['material'] < len(materials) else ''
        k = 'Shadow' if sh.startswith('sshadow') else 'Aura' if sh == 'saura' else 'Mesh'
        kind.setdefault(d['joint'], k)
        if k == 'Mesh':
            for j in d.get('palette') or ():
                kind.setdefault(('skin', j), True)
    kids = {}
    for i, j in enumerate(joints):
        kids.setdefault(j['parent'], []).append(i)

    def named_ancestor(i):
        p = joints[i]['parent']
        seen = 0
        while p is not None and seen < 512:
            if joints[p]['name']:
                return p
            p = joints[p]['parent']
            seen += 1
        return None

    raw = []
    for i, j in enumerate(joints):
        if j['name']:
            raw.append(friendly(j['name']))
            continue
        a = named_ancestor(i)
        base = friendly(joints[a]['name']) if a is not None else ''
        stem, side = (base[:-2], base[-2:]) if base[-2:] in ('.L', '.R') else (base, '')
        k = kind.get(i)
        child_names = {joints[c]['name'] for c in kids.get(i, ())}
        if k == 'Mesh':
            raw.append('Mesh_%02d' % i)
        elif kids.get(i) and all(kind.get(c) == 'Mesh' for c in kids[i]):
            raw.append('MeshRoot')
        elif child_names & {'hip', 'body1'}:
            raw.append('Center')
        elif a is None:
            raw.append('Root')
        elif k in ('Shadow', 'Aura'):
            raw.append('%s_%s%s' % (stem, k, side))
        else:
            raw.append('%s_Helper%s' % (stem, side))
    used, out = {}, []
    for i, n in enumerate(raw):
        if n in used:                                 # Hand_Shadow.L, Hand_Shadow2.L ...
            used[n] += 1
            stem, side = (n[:-2], n[-2:]) if n[-2:] in ('.L', '.R') else (n, '')
            m = '%s%d%s' % (stem, used[n], side)
            while m in used:
                used[n] += 1
                m = '%s%d%s' % (stem, used[n], side)
            n = m
        used.setdefault(n, 1)
        out.append(n)
    return out


def joint_bone_names(arm):
    """Name of the bone of every joint, by the bones' pd_index (survives renaming bones in Blender); older files:
    the names stored at import."""
    joints = json.loads(arm['pd_joints'])
    out = [None] * len(joints)
    for b in arm.data.bones:
        i = b.get('pd_index')
        if isinstance(i, int) and 0 <= i < len(out):
            out[i] = b.name
    if any(n is None for n in out):
        old = json.loads(arm.get('pd_bones', '[]'))
        out = [n if n is not None else (old[k] if k < len(old) else 'j%03d' % k) for k, n in enumerate(out)]
    return out


def rename_bones(arm):
    """Give an armature imported before readable names its readable names (pd_joints game names kept)."""
    joints = json.loads(arm['pd_joints'])
    by_index = {b.get('pd_index'): b for b in arm.data.bones}
    wanted = bone_names(joints)
    n = 0
    for i, nm in enumerate(wanted):
        b = by_index.get(i)
        if b is None or b.name == nm:
            continue
        b[GAME_NAME] = joints[i]['name'] or ''
        b.name = nm                                    # Blender renames vertex groups and action paths with it
        n += 1
    arm['pd_bones'] = json.dumps(joint_bone_names(arm))
    return n


# ---------------------------------------------------------------- textures

SHINE = 'PD Shine'
TEX_NODES = (('PD Diffuse', 'color'), ('PD Normal', 'normal'), ('PD Lighting', 'ramp'))
IMAGE_EXT = ('.png', '.tga', '.tif', '.tiff', '.bmp', '.jpg', '.jpeg', '.exr', '.webp', '.psd')
MAX_SIZE = 1024


def character_meshes(arm):
    """Every mesh under a character armature (its cloth / prop armatures too)."""
    out, todo, seen = [], [arm], set()
    while todo:
        ob = todo.pop()
        if ob.name in seen:
            continue
        seen.add(ob.name)
        for c in ob.children:
            if c.type == 'MESH':
                out.append(c)
            elif c.type == 'ARMATURE':
                todo.append(c)
    return out


def material_images(mats):
    """[(image, kind)] of PD character materials, each image once."""
    out, seen = [], set()
    for mat in mats:
        if mat is None or mat.node_tree is None:
            continue
        for node_name, kind in TEX_NODES:
            n = mat.node_tree.nodes.get(node_name)
            if n is not None and n.image is not None and n.image.name not in seen:
                seen.add(n.image.name)
                out.append((n.image, kind))
    return out


def object_images(objects):
    mats = []
    for ob in objects:
        obs = character_meshes(ob) if ob.type == 'ARMATURE' else [ob] if ob.type == 'MESH' else []
        for o in obs:
            mats += [s.material for s in o.material_slots]
    return material_images(mats)


def file_stem(img):
    return bpy.path.clean_name(img.name)


def save_images(images, folder):
    """Write each image as PNG (RGBA, alpha as stored: cut-out / shine mask) into folder. Returns paths."""
    os.makedirs(folder, exist_ok=True)
    out = []
    for img, _kind in images:
        path = os.path.join(folder, file_stem(img) + '.png')
        tmp = bpy.data.images.new('.pd_save', img.size[0], img.size[1], alpha=True, float_buffer=False)
        try:
            tmp.colorspace_settings.name = img.colorspace_settings.name
            tmp.alpha_mode = 'CHANNEL_PACKED'
            import numpy as np
            px = np.empty(img.size[0] * img.size[1] * 4, np.float32)
            img.pixels.foreach_get(px)
            tmp.pixels.foreach_set(px)
            tmp.filepath_raw = path
            tmp.file_format = 'PNG'
            tmp.save()
        finally:
            bpy.data.images.remove(tmp)
        out.append(path)
    return out


def _pow2(n):
    p = 1
    while p * 2 <= n:
        p *= 2
    return p


def _find_file(folder, stem):
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    low = stem.lower()
    for n in names:
        s, e = os.path.splitext(n)
        if s.lower() == low and e.lower() in IMAGE_EXT:
            return os.path.join(folder, n)
    return None


def load_into(img, kind, path):
    """Replace an image's pixels with a file's, converted to what the game takes: RGBA, a power of two at most
    MAX_SIZE (resized to the nearest power of two below its size), normal maps Non-Color. A normal map without an
    alpha channel keeps the old shine mask (alpha); a colour texture without one becomes fully opaque.
    Returns a short note of what was converted."""
    import numpy as np
    src = bpy.data.images.load(path, check_existing=False)
    notes = []
    try:
        if kind == 'normal':
            src.colorspace_settings.name = 'Non-Color'
        src.alpha_mode = 'CHANNEL_PACKED'
        w, h = src.size
        if w == 0 or h == 0:
            raise ValueError('%s: no pixels' % os.path.basename(path))
        W, H = min(_pow2(w), MAX_SIZE), min(_pow2(h), MAX_SIZE)
        if (W, H) != (w, h):
            src.scale(W, H)
            notes.append('%dx%d -> %dx%d' % (w, h, W, H))
        px = np.empty(W * H * 4, np.float32)
        src.pixels.foreach_get(px)
        px = px.reshape(H, W, 4)
        has_alpha = src.channels == 4 and src.depth in (32, 64, 128)    # RGBA bytes, halves or floats
        if not has_alpha:
            if kind == 'normal' and img.size[0] > 0:
                old = np.empty(img.size[0] * img.size[1] * 4, np.float32)
                img.pixels.foreach_get(old)
                old = old.reshape(img.size[1], img.size[0], 4)
                ys = (np.arange(H) * img.size[1] // H)
                xs = (np.arange(W) * img.size[0] // W)
                px[..., 3] = old[ys][:, xs][..., 3]
                notes.append('shine mask kept')
            else:
                px[..., 3] = 1.0
        if tuple(img.size) != (W, H):
            img.scale(W, H)
        img.pixels.foreach_set(px.ravel())
        img.alpha_mode = 'CHANNEL_PACKED'
        if kind == 'normal':
            img.colorspace_settings.name = 'Non-Color'
        img.update()
        img.pack()
    finally:
        bpy.data.images.remove(src)
    return ', '.join(notes)


def import_images(images, folder):
    """Load every image that has a file of the same name in folder. Returns (updated [(name, note)], missing)."""
    done, missing = [], []
    for img, kind in images:
        path = _find_file(folder, file_stem(img))
        if path is None:
            missing.append(img.name)
            continue
        done.append((img.name, load_into(img, kind, path)))
    return done, missing


# ---------------------------------------------------------------- shine paint layer

def ensure_shine(me):
    """The PD Shine colour layer (vertex paint: white = full shine, black = none), from the older pd_alpha."""
    attr = me.color_attributes.get(SHINE)
    if attr is None:
        attr = me.color_attributes.new(SHINE, 'BYTE_COLOR', 'POINT')
        old = me.attributes.get('pd_alpha')
        for k, d in enumerate(attr.data):
            v = old.data[k].value if old is not None and k < len(old.data) else 1.0
            d.color_srgb = (v, v, v, 1.0)
    me.color_attributes.active_color = attr
    return attr


def shine_reader(me):
    """Function vertex index -> shine 0..1 (the PD Shine layer, else the older pd_alpha, else 1)."""
    attr = me.color_attributes.get(SHINE)
    if attr is not None:
        if attr.domain == 'POINT':
            return lambda v: sum(attr.data[v].color_srgb[:3]) / 3.0
        per_v = {}
        for poly in me.polygons:
            for li in poly.loop_indices:
                per_v.setdefault(me.loops[li].vertex_index, sum(attr.data[li].color_srgb[:3]) / 3.0)
        return lambda v: per_v.get(v, 1.0)
    old = me.attributes.get('pd_alpha')
    if old is not None:
        return lambda v: old.data[v].value
    return lambda v: 1.0


# ---------------------------------------------------------------- the export check

def check_model(arm):
    """(errors, warnings) for everything the export writes from Blender: textures, bones, weights, UVs, shine."""
    from .pdstage import char_build as cb
    errors, warnings = [], []
    names = joint_bone_names(arm)
    joints = json.loads(arm['pd_joints'])
    by_bone = {n: i for i, n in enumerate(names)}
    game = [j['name'] for j in joints if j['name']]
    dup = sorted({n for n in game if game.count(n) > 1})
    if dup:
        errors.append('game joint names used twice: %s' % ', '.join(dup))
    long = [n for n in game if len(n) > 6]
    if long:
        errors.append('game joint names longer than 6 characters (the file holds 6): %s' % ', '.join(long))
    for b in arm.data.bones:
        if not isinstance(b.get('pd_index'), int):
            errors.append('bone "%s" is not one of the game\'s joints (new bones are not exported; parent its '
                          'vertices to an existing bone)' % b.name)
    meshes = [o for o in arm.children if o.type == 'MESH' and not o.get('pd_rigid')]
    if not meshes:
        errors.append('%s has no mesh' % arm.name)
    for ob in meshes:
        me = ob.data
        if not me.uv_layers:
            errors.append('%s: no UV map' % ob.name)
        if not any(m.type == 'ARMATURE' and m.object for m in ob.modifiers):
            warnings.append('%s: no Armature modifier (it will not move in Blender; the export still uses its '
                            'vertex groups)' % ob.name)
        groups = {g.index: g.name for g in ob.vertex_groups}
        unknown = sorted({g.name for g in ob.vertex_groups if g.name not in by_bone})
        if unknown:
            warnings.append('%s: vertex groups that are no bone are ignored: %s' % (ob.name, ', '.join(unknown[:8])))
        none, many = 0, 0
        for v in me.vertices:
            ws = [g for g in v.groups if g.weight > 0 and groups.get(g.group) in by_bone]
            if not ws:
                none += 1
            elif len(ws) > 2:
                many += 1
        if none:
            errors.append('%s: %d vertices have no weight on a bone' % (ob.name, none))
        if many:
            warnings.append('%s: %d vertices use more than 2 bones (the game takes 2: the strongest are kept)'
                            % (ob.name, many))
        # joints per triangle (a draw holds at most PALETTE)
        worst = 0
        for poly in me.polygons:
            js = set()
            for vi in poly.vertices:
                for g in me.vertices[vi].groups:
                    if g.weight > 0 and groups.get(g.group) in by_bone:
                        js.add(groups[g.group])
            worst = max(worst, len(js))
        if worst > cb.PALETTE:
            errors.append('%s: a face uses %d bones (at most %d)' % (ob.name, worst, cb.PALETTE))
        if me.color_attributes.get(SHINE) is None and me.attributes.get('pd_alpha') is None:
            warnings.append('%s: no PD Shine paint layer (full shine everywhere)' % ob.name)
        if len(me.vertices) > 200000:
            warnings.append('%s: %d vertices; the game\'s characters have about 3,000' % (ob.name, len(me.vertices)))
        for k, slot in enumerate(ob.material_slots):
            if slot.material is None:
                errors.append('%s: material slot %d is empty' % (ob.name, k + 1))
            elif slot.material.node_tree is None or slot.material.node_tree.nodes.get('PD Diffuse') is None:
                warnings.append('%s: material "%s" is not a character material: its first image is used, no normal '
                                'map' % (ob.name, slot.material.name))
    for img, kind in object_images([arm]):
        w, h = img.size
        if w == 0 or h == 0:
            errors.append('texture %s has no pixels (file missing?)' % img.name)
            continue
        if w & (w - 1) or h & (h - 1):
            errors.append('texture %s is %d x %d: not a power of two (Import Textures converts it)' % (img.name, w, h))
        elif max(w, h) > MAX_SIZE:
            errors.append('texture %s is %d x %d: at most %d' % (img.name, w, h, MAX_SIZE))
        elif max(w, h) > 512:
            warnings.append('texture %s is %d x %d: the game\'s own are at most 512' % (img.name, w, h))
        if kind == 'normal' and img.colorspace_settings.name != 'Non-Color':
            warnings.append('normal map %s is not Non-Color: its colours are read as they are stored'
                            % img.name)
    return errors, warnings
