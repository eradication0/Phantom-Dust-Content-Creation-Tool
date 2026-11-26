"""Import a map's visible model (Map/stNN.alr) as a reference: stage, background and sky.

Each mesh record becomes an object with its UVs. Meshes using the stage shaders (sd, sbts, sdrefs, sbtsrefs) get a
PD Stage Shader material with the game's maps, highlight colour and shininess (shine mask = PD_Light alpha);
other shaders (sky, effects) get a plain PD material with their colour texture. Shadow meshes
(shaders starting with "sshadow") are not drawn: the stage's shadow volumes (sshadowch) go to a ShadowCasters
collection instead. Vertex positions get their node transforms applied, then the
same game -> Blender conversion as collision, so the model lines up with the imported collision.
"""
import math
import os
import struct
import tempfile

import bpy
import numpy as np

from ._lib import alr, alr_build
from . import convert as cv
from . import pd_material

ROOT_NAMES = {0: 'Stage', 1: 'Background', 2: 'Sky'}


def _load_pixels(path):
    dds = bpy.data.images.load(path)
    w, h = dds.size
    px = np.empty(w * h * 4, dtype=np.float32)
    dds.pixels.foreach_get(px)
    bpy.data.images.remove(dds)
    return w, h, px


def _cube_image(b, t):
    """A cube map as one Blender image: the six faces side by side, left to right +X -X +Y -Y +Z -Z (Direct3D
    order), each face's mip levels stacked under it (pdstage/cubemap.py: the game's lower levels are their own
    pictures, not a reduction of the top one); pd_cube_map marks the layout."""
    from ._lib import cubemap
    faces = cubemap.decode(b, t, alr.header(b)['resource_offset'])
    w, h, px = cubemap.atlas(faces)
    img = bpy.data.images.new(t['name'] or 'cube', w, h, alpha=True)
    img.pixels.foreach_set(px.ravel())
    img.file_format = 'PNG'
    img.pack()
    img['pd_cube_map'] = True
    try:
        img.id_properties_ui('pd_cube_map').update(
            description='A cube map: six square faces left to right, +X -X +Y -Y +Z -Z (game axes), each face\'s '
                        'mip levels stacked under it')
    except (TypeError, AttributeError):
        pass
    return img


# One Blender image per texture of a file within one import (importer.import_stage clears it): the stage, object,
# sky and texture-table imports each had their own cache, so a texture used by the stage and by an object (st08's
# ta105s_0: the tower ring and the break pieces) became two images ("ta105s_0", "ta105s_0.001") for one texture
# number, and the export wrote whichever came last: a picture painted on the other one was lost.
_SHARED = {}


def _image(b, t, cache, tmpdir):
    if t['index'] in cache:
        return cache[t['index']]
    key = (t['name'], t['offset'], t['raw_format'], t['width'], t['height'], t['mips'], len(b))
    img = _SHARED.get(key)
    if img is not None:
        try:
            img.name                                     # still in the file
            cache[t['index']] = img
            return img
        except ReferenceError:
            pass
    img = _image_new(b, t, tmpdir)
    cache[t['index']] = img
    if img is not None:
        _SHARED[key] = img
    return img


def _image_new(b, t, tmpdir):
    img = None
    # 16-bit textures (B5G6R5, B4G4R4A4, B5G5R5A1) come through alr.texture_dds too (each level expanded to BGRA8)
    if t.get('cubemap'):
        try:
            return _cube_image(b, t)
        except (RuntimeError, ValueError):
            return None
    data = alr.texture_dds(b, t)
    if data:
        path = os.path.join(tmpdir, '%03d_%s.dds' % (t['index'], t['name'] or 'tex'))
        with open(path, 'wb') as f:
            f.write(data)
        try:
            dds = bpy.data.images.load(path)
            w, h = dds.size
            px = np.empty(w * h * 4, dtype=np.float32)
            dds.pixels.foreach_get(px)
            bpy.data.images.remove(dds)
            # Keep a plain image packed as PNG: packed DDS images don't survive saving and reopening well.
            img = bpy.data.images.new(t['name'] or 'tex', w, h, alpha=True)
            img.pixels.foreach_set(px)
            img.file_format = 'PNG'
            img.pack()
            # how the game stores it: its mip level count (many of the game's textures have one level only) and
            # plain colour (format 0x06 / 0x12: effect glows, sea, sky pictures) or block-compressed; the export
            # writes the texture the same way (visuals_export.Textures.ref)
            img['pd_mip_levels'] = int(t.get('mips') or 1)
            # the game's storage format (pdstage/texlevels.py: dxt1, dxt3, dxt5, b8g8r8a8, b5g6r5, b4g4r4a4,
            # b5g5r5a1) and, for uncompressed ones, whether its rows are swizzled (the original Xbox release)
            from ._lib import texlevels
            storage, swizzled = texlevels.storage_of(t['raw_format'])
            img['pd_texture_storage'] = storage or 'other'
            if swizzled:
                img['pd_texture_swizzled'] = True
            if t.get('mips', 1) > 1:
                _mip_image(b, t, img, tmpdir)
        except (RuntimeError, ValueError):
            img = None
    return img


def _mip_image(b, t, img, tmpdir):
    """The texture's lower mip levels (1, 2, ...) as one Blender image, `<name> mips`, linked from the texture's
    image as pd_mip_image: level 1 at the top, each next level under it, left-aligned (pdstage/texlevels.py). The
    game's lower levels are pictures of their own (41% of the 2017 stage textures differ from a box reduction of
    the level above), which the game shows at a distance; the export writes them from this image."""
    from ._lib import texlevels
    levels = []
    for k, data in enumerate(alr.texture_level_dds(b, t)[1:], 1):
        path = os.path.join(tmpdir, '%03d_%s_mip%d.dds' % (t['index'], t['name'] or 'tex', k))
        with open(path, 'wb') as f:
            f.write(data)
        dds = bpy.data.images.load(path)
        w, h = dds.size
        px = np.empty(w * h * 4, dtype=np.float32)
        dds.pixels.foreach_get(px)
        bpy.data.images.remove(dds)
        levels.append(np.clip(np.round(px.reshape(h, w, 4)[::-1] * 255), 0, 255).astype(np.uint8))
    if not levels:
        return None
    w, h, px = texlevels.mip_atlas(levels)
    mi = bpy.data.images.new('%s mips' % (t['name'] or 'tex'), w, h, alpha=True)
    mi.pixels.foreach_set(px.ravel())
    mi.file_format = 'PNG'
    mi.pack()
    mi.use_fake_user = True
    img['pd_mip_image'] = mi
    try:
        img.id_properties_ui('pd_mip_image').update(
            description='The lower mip levels (1, 2, ...) the game shows at a distance, stacked top to bottom. '
                        'Written as they are while this image is the imported one; painting this image in '
                        'Blender, replacing it or changing its size makes them again from it (or press '
                        'Regenerate Mip Levels)')
    except (TypeError, AttributeError):
        pass
    return mi


def import_texture_table(alr_path):
    """Every texture of the model file that no imported material uses (the effect textures e3..., envmap, the
    sprite sheets the .dat's effects and SP00 use by number) as a Blender image with its name and its texture
    number (pd_texture_number: the effects use numbers), so the export writes them from the scene. Images already
    made for materials get their number too. Returns (images made, numbers not representable)."""
    b = open(alr_path, 'rb').read()
    texs = alr.textures(b)
    by_name = {}
    for img in bpy.data.images:
        by_name.setdefault(img.name, img)
    made, skipped = 0, []
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = {}
        for t in texs:
            img = by_name.get(t['name']) if t['name'] else None
            if img is None:
                img = _image(b, t, cache, tmpdir)
                if img is None:
                    skipped.append(t['index'])
                    continue
                img.use_fake_user = True                 # no material uses it: keep it when the file is saved
                made += 1
            if 'pd_texture_number' not in img:
                img['pd_texture_number'] = t['index']
    return made, skipped


LIGHT_LAYER = 'PD_Light'     # colour attribute holding the baked lighting (exported as vertex colour)


def _material(name, img):
    """A PD Stage Shader material showing `img` (used for new scenes: no highlight)."""
    return pd_material.make_material(name, diffuse=img)


def _settings_key(entry):
    """A short name part that tells game materials with different settings apart (flags, filter, blend, texture
    slots, colour words, shader parameters)."""
    import hashlib
    raw = bytes(entry['raw'])
    return hashlib.sha1(raw[0x0C:0x12] + raw[0x14:0x20] + raw[0x30:0x4C]).hexdigest()[:6]


def tag_game_material(mat, entry, texs, image_of):
    """The game material's shader and settings on the Blender material, so the export writes the same material
    (alr_build.game_record): pd_game_shader, pd_material_flags, pd_material_filter, pd_material_blend,
    pd_texture_roles, pd_material_colour, pd_material_word_38, pd_shader_params (eight numbers, their meaning per
    shader class), and pd_texture_<k> for a slot whose role is not one of the material's maps (diffuse 1, normal 2,
    reflection 4)."""
    if mat is None or entry is None or 'pd_game_shader' in mat:
        return mat
    raw = bytes(entry['raw'])
    mat['pd_game_shader'] = entry['shader']
    mat['pd_material_flags'] = struct.unpack_from('<i', raw, 0x0C)[0]
    mat['pd_material_filter'] = raw[0x11]
    mat['pd_material_blend'], roles = struct.unpack_from('<HH', raw, 0x14)
    mat['pd_texture_roles'] = roles
    # +0x30 an ARGB colour (no reader found in the shader classes), +0x38 0 or 0xFF808080 (the same): as A, R, G, B
    mat['pd_material_colour'] = [raw[0x33], raw[0x32], raw[0x31], raw[0x30]]
    mat['pd_material_word_38'] = [raw[0x3B], raw[0x3A], raw[0x39], raw[0x38]]
    mat['pd_shader_params'] = list(struct.unpack_from('<8h', raw, 0x3C))
    for k, t in enumerate(entry['textures'][:4]):
        if t is None or t >= len(texs):
            continue
        role = (roles >> (4 * k)) & 0xF
        if role in (1, 2, 4) and not texs[t].get('cubemap'):
            continue
        # (a cube map, the reflection of the ..ref.. shaders, is its own slot image: the six faces side by side)
        img = image_of(t)
        if img is not None:
            mat['pd_texture_%d' % k] = img
    return mat


def _linear(byte):
    c = byte / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _game_material(name, entry, texs, image_of):
    """A PD Stage Shader material with a game material's maps and highlight (shine mask from PD_Light alpha)."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    raw = entry['raw']
    roles = struct.unpack_from('<H', raw, 0x16)[0]
    maps = {}
    for slot, t in enumerate(entry['textures']):
        role = (roles >> (4 * slot)) & 0xF
        if t is not None and t < len(texs) and role in (1, 2, 4) and role not in maps:
            maps[role] = image_of(t)
    if 1 not in maps and entry['textures'] and entry['textures'][0] is not None and entry['textures'][0] < len(texs):
        maps[1] = image_of(entry['textures'][0])
    b, g, r, power = raw[0x34:0x38]
    mat = bpy.data.materials.new(name)
    if entry['shader'] == 'sbtscloud3':                # scrolling (the add-on's Scrolling Textures, the sky's
        # cloud shader): slot 0 colour, 1 and 2 the normal maps, three (x, y) speeds at +0x3C, the blend from +0x15
        tx = entry['textures']
        maps = {1: image_of(tx[0])} if tx[0] is not None and tx[0] < len(texs) else {}
        if tx[1] is not None and tx[1] < len(texs):
            maps[2] = image_of(tx[1])
        sp = struct.unpack_from('<6h', raw, 0x3C)
        mat.pd_scroll = True
        mat.pd_scroll_colour, mat.pd_scroll_normal_a, mat.pd_scroll_normal_b = sp[0:2], sp[2:4], sp[4:6]
        if tx[2] is not None and tx[2] != tx[1] and tx[2] < len(texs):
            mat.pd_scroll_normal_b_image = image_of(tx[2])
        mat.pd_scroll_blend = 'OPAQUE' if not raw[0x0C] & 0x10 else ('ALPHA' if raw[0x15] == 0x54 else 'ADD')
        # the vertex colour's alpha is kept (the game's sky clouds fade out toward the horizon with it), and the
        # material's highlight colour and power
        return pd_material.setup(mat, diffuse=maps.get(1), normal=maps.get(2), shine_from_light_alpha=True,
                                 specular=(_linear(r), _linear(g), _linear(b)), shininess=min(127, power))
    if entry['shader'].endswith('al'):                 # the blended variant (st07 glass sdal): see-through
        mat.pd_transparent = True
    return pd_material.setup(mat, diffuse=maps.get(1), normal=maps.get(2),
                             reflection=maps.get(4), specular=(_linear(r), _linear(g), _linear(b)),
                             shininess=min(127, power),   # the game's own power, also 0 (st08's svcal)
                             shine_from_light_alpha=True)


def _turned(mtx, origin, n):
    """A game normal turned by a node matrix, in Blender space, unit length."""
    p = alr.apply(mtx, n)
    v = cv.to_blender((p[0] - origin[0], p[1] - origin[1], p[2] - origin[2]), 1.0)
    length = math.sqrt(sum(x * x for x in v)) or 1.0
    return tuple(x / length for x in v)


def _set_normals(me, normals, used, mtx):
    """The game's vertex normals (turned by the mesh's node) as the mesh's custom normals: the export writes the
    corner normals, so the shading stays the game's."""
    if not normals:
        return
    o = alr.apply(mtx, (0.0, 0.0, 0.0))
    out = []
    for i in used:
        p = alr.apply(mtx, normals[i])
        n = cv.to_blender((p[0] - o[0], p[1] - o[1], p[2] - o[2]), 1.0)
        length = math.sqrt(sum(x * x for x in n)) or 1.0
        out.append(tuple(x / length for x in n))
    me.validate()
    try:
        me.normals_split_custom_set_from_vertices(out)
    except (RuntimeError, ValueError):
        pass


IMPORTED = []   # (root, draw index, Blender object, draw chunk offset, joint, light list) of the last import_visuals:
                # read by townlights (draw instances, chunk 0x12, are listed with their own joint and lights)

# Joint flag bits (skeleton chunk 0x03, u16 at +36 of a 64-byte joint), clean-room notes (research p3-dropped-data.md):
#   0x0004 the joint has draws, 0x0010 translation, 0x0020 rotation, 0x0040 scale: summaries the export computes;
#   0x0100 a joint the game finds by name (Xbox 0x4C4B0 tests it), 0x0200 turned to face the camera (pose 0x14DE40),
#   0x0800 its draws are not drawn (draw submit 0x151310; set at run time on actors' shotNN / C_00..C_04 markers).
JOINT_PROPS = ((0x0100, 'pd_joint_lookup'), (0x0200, 'pd_faces_camera'), (0x0800, 'pd_hidden'))
JOINT_COMPUTED = 0x0004 | 0x0010 | 0x0020 | 0x0040


def game_to_blender_matrix(m, scale):
    """A game node matrix (row-major 4x4, column vectors, y-up left-handed) as a Blender Matrix: the y/z mirror on
    both sides, translation times scale."""
    from mathutils import Matrix
    o = (0, 2, 1)
    out = Matrix.Identity(4)
    for r in range(3):
        for c in range(3):
            out[r][c] = m[o[r]][o[c]]
        out[r][3] = m[o[r]][3] * scale
    return out


def import_joints(b, root_off, ri, coll, stage, scale):
    """The model's joints as empties (hierarchy, transforms, name, flags) in a '<model> Joints' collection, and
    every imported mesh of the model parented to its draw's joint without moving. Returns the joint count."""
    nodes, _ = alr.skeleton(b, root_off)
    if not nodes:
        return 0
    jc = bpy.data.collections.new('%s Joints' % coll.name)
    coll.children.link(jc)
    empties, worlds = [], []
    sk = [x for x in alr.chain(b, root_off) if x[1] == 3][0]
    for i, n in enumerate(nodes):
        word = struct.unpack_from('<I', b, sk[0] + 16 + i * 64 + 0x2C)[0]
        gname = alr.decode_text(word) if word != 0xFFFFFFFF else ''
        ob = bpy.data.objects.new('%s_%s_J%03d%s' % (stage, coll.name, i, ('_' + gname) if gname else ''), None)
        ob.empty_display_type = 'PLAIN_AXES'
        ob.empty_display_size = 2.0 * scale
        ob['pd_joint'] = True
        if gname:
            ob['pd_joint_name'] = gname
        for bit, prop in JOINT_PROPS:
            if n['flags'] & bit:
                ob[prop] = True
        if n['parent'] is not None and n['parent'] < len(empties):
            ob.parent = empties[n['parent']]
        ob.matrix_basis = game_to_blender_matrix(alr._local(n), scale)
        jc.objects.link(ob)
        empties.append(ob)
        worlds.append(game_to_blender_matrix(alr.node_matrix(nodes, i), scale))
    for r, _mi, mesh_ob, off, j, _lights in IMPORTED:
        if r != ri:
            continue
        if j < len(empties):
            mesh_ob.parent = empties[j]
            mesh_ob.matrix_parent_inverse = worlds[j].inverted()   # the mesh stays where it is (world vertices)
    # draw instances (chunk 0x12, st08 and st09): an earlier draw drawn again under another joint ('target' counts
    # the model's draws and instances together from 0). Each is a linked duplicate of that draw's object on its own
    # joint; the export writes it as a draw of its own (same picture)
    seq = [(o, t) for o, t, _s in alr.chain(b, root_off) if t in (0x02, 0x12)]
    by_off = {e[3]: e for e in IMPORTED if e[0] == ri}

    def source(k, depth=0):
        o, t = seq[k]
        if t == 0x02 or depth > 16:
            return o if t == 0x02 else None
        tgt = struct.unpack_from('<H', b, o + 8 + 24)[0]
        return source(tgt, depth + 1) if tgt < len(seq) else None

    n_inst = 0
    for k, (o, t) in enumerate(seq):
        if t != 0x12:
            continue
        lc = b[o + 8 + 16]
        lights = list(b[o + 8 + 17:o + 8 + 17 + min(lc, 7)])
        tgt, j = struct.unpack_from('<HH', b, o + 8 + 24)
        src = by_off.get(source(tgt)) if tgt < len(seq) else None
        if src is None or j >= len(empties) or src[4] >= len(worlds):
            continue
        src_ob = src[2]
        inst = bpy.data.objects.new('%s_i%03d' % (src_ob.name, k), src_ob.data)
        for c in src_ob.users_collection:
            c.objects.link(inst)
        inst.parent = empties[j]
        inst.matrix_parent_inverse = worlds[src[4]].inverted()
        IMPORTED.append((ri, None, inst, o, j, lights))
        n_inst += 1
    return len(nodes)


def import_visuals(context, alr_path, parent, scale, roots=(0, 1, 2)):
    IMPORTED.clear()
    b = open(alr_path, 'rb').read()
    h = alr.header(b)
    texs = alr.textures(b)
    cache, report = {}, []
    vis = bpy.data.collections.new('Visuals')
    parent.children.link(vis)
    vis.pd_role = 'VISUALS'
    stage = os.path.splitext(os.path.basename(alr_path))[0]
    with tempfile.TemporaryDirectory() as tmpdir:
        for ri in roots:
            if ri >= len(h['roots']):
                continue
            meshes = alr.meshes(b, h['roots'][ri])
            if not meshes:
                continue
            coll = bpy.data.collections.new(ROOT_NAMES.get(ri, 'Model_%d' % ri))
            vis.children.link(coll)
            n_obj = n_tri = 0
            for mi, m in enumerate(meshes):
                mat_entry = m['materials'][m['material']] if m['material'] < len(m['materials']) else None
                shader = mat_entry['shader'] if mat_entry else ''
                if shader.startswith('sshadow') or m['vbuf'] >= len(m['vbufs']):
                    continue
                tris = alr.triangles_from_indices(m['indices'], m['primitive'])
                if not tris:
                    continue
                vb = m['vbufs'][m['vbuf']]
                pos, uv, _uv2 = alr.read_vertices(b, h['resource_offset'], vb)
                cols = alr.read_colours(b, h['resource_offset'], vb)
                mtx = alr.node_matrix(m['nodes'], m['node']) if m['node'] < len(m['nodes']) else alr._identity()
                used = sorted({i for t in tris for i in t})
                remap = {old: new for new, old in enumerate(used)}
                verts = [cv.to_blender(alr.apply(mtx, pos[i]), scale) for i in used]
                faces, seen_faces = [], set()
                for t in tris:
                    f = cv.flip_winding(tuple(remap[i] for i in t))        # the mirror reverses winding
                    if frozenset(f) in seen_faces:
                        # Same corners as an earlier face (a double-sided wall): Blender would merge the two,
                        # so give this one its own copies of the vertices.
                        f2 = []
                        for k in f:
                            used.append(used[k])
                            verts.append(verts[k])
                            f2.append(len(verts) - 1)
                        f = tuple(f2)
                    seen_faces.add(frozenset(f))
                    faces.append(f)
                name = '%s_%s_%02d_%s' % (stage, ROOT_NAMES.get(ri, 'm%d' % ri), mi, shader or 'mesh')
                me = bpy.data.meshes.new(name)
                me.from_pydata(verts, [], faces)
                if uv:
                    layer = me.uv_layers.new(name='UVMap')
                    for poly in me.polygons:
                        for li in poly.loop_indices:
                            u, v = uv[used[me.loops[li].vertex_index]]
                            layer.data[li].uv = (u, 1.0 - v)
                if _uv2:                                  # light-mapped (lbts): the light map's own UV map
                    layer2 = me.uv_layers.new(name='PD_LightUV')
                    for poly in me.polygons:
                        for li in poly.loop_indices:
                            u, v = _uv2[used[me.loops[li].vertex_index]]
                            layer2.data[li].uv = (u, 1.0 - v)
                    me.uv_layers.active = layer
                _set_normals(me, alr.read_normals(b, h['resource_offset'], vb), used, mtx)
                light = me.color_attributes.new(LIGHT_LAYER, 'BYTE_COLOR', 'POINT')
                for new_i, old_i in enumerate(used):
                    c = cols[old_i] if cols else (255, 255, 255, 255)
                    light.data[new_i].color_srgb = (c[0] / 255, c[1] / 255, c[2] / 255, c[3] / 255)
                me.color_attributes.active_color = light
                me.validate()
                me.update()
                if mat_entry is not None and (keeps_game_maps(shader, mat_entry) or shader in SKY_SHADERS):
                    tex_i = mat_entry['textures'][0]
                    tex_name = texs[tex_i]['name'] if tex_i is not None and tex_i < len(texs) else 'untextured'
                    extra = bytes(mat_entry['raw'][0x3C:0x48]).hex() if shader == 'sbtscloud3' else ''
                    image_of = lambda t: _image(b, texs[t], cache, tmpdir)
                    me.materials.append(tag_game_material(_game_material(
                        '%s_%s_%s_%s%s_%s' % (stage, shader, tex_name, bytes(mat_entry['raw'][0x34:0x38]).hex(), extra,
                                              _settings_key(mat_entry)),
                        mat_entry, texs, image_of), mat_entry, texs, image_of))
                else:
                    tex_i = mat_entry['textures'][0] if mat_entry else None
                    img = _image(b, texs[tex_i], cache, tmpdir) if tex_i is not None and tex_i < len(texs) else None
                    tex_name = texs[tex_i]['name'] if img is not None else 'untextured'
                    key = '%s_%s_%s' % (stage, shader or 'mat', tex_name) + \
                        ('_' + _settings_key(mat_entry) if mat_entry else '')
                    me.materials.append(tag_game_material(_material(key, img), mat_entry, texs,
                                                          lambda t: _image(b, texs[t], cache, tmpdir)))
                ob = bpy.data.objects.new(name, me)
                from . import roundtrip
                if roundtrip.ENABLED:                     # fallback only: the game's mesh it came from
                    ob['pd_mesh'] = [ri, mi]
                coll.objects.link(ob)
                IMPORTED.append((ri, mi, ob, m['offset'], m['node'],
                                 list(b[m['offset'] + 0x34:m['offset'] + 0x34 + min(12, b[m['offset'] + 0x30])])))
                n_obj += 1
                n_tri += len(faces)
            n_joints = import_joints(b, h['roots'][ri], ri, coll, stage, scale)
            report.append('%s: %d meshes, %d triangles%s' % (coll.name, n_obj, n_tri,
                                                              ', %d joints' % n_joints if n_joints else ''))
    n_img = sum(1 for v in cache.values() if v is not None)
    report.append('%d textures' % n_img)
    if 0 in roots and 0 < len(h['roots']):
        n = import_shadow_casters(b, h, parent, scale, stage)
        if n:
            report.append('shadow casters: %d triangles' % n)
    return '; '.join(report)


def import_shadow_casters(b, h, parent, scale, stage):
    """The stage's shadow volumes into a ShadowCasters collection, corners welded, zero-area strips left out:
    sshadowch (stretched by the game along the sun: the export makes the strips again) as one mesh, sshadowc
    (already stretched along the map's sun when it was made) as another, marked pd_prestretched so the export
    writes it back unchanged. Returns the triangle count."""
    groups = {'sshadowch': ([], {}, [], set()), 'sshadowc': ([], {}, [], set())}
    sources = {'sshadowch': [], 'sshadowc': []}
    for mi, m in enumerate(alr.meshes(b, h['roots'][0])):
        entry = m['materials'][m['material']] if m['material'] < len(m['materials']) else None
        if entry is None or entry['shader'] not in groups or m['vbuf'] >= len(m['vbufs']):
            continue
        verts, index, faces, seen = groups[entry['shader']]
        sources[entry['shader']].append(mi)
        pos = alr.read_vertices(b, h['resource_offset'], m['vbufs'][m['vbuf']])[0]
        mtx = alr.node_matrix(m['nodes'], m['node']) if m['node'] < len(m['nodes']) else alr._identity()
        for t in alr.triangles_from_indices(m['indices'], m['primitive']):
            f = []
            for i in t:
                p = alr.apply(mtx, pos[i])
                k = tuple(round(c, 6) for c in p)      # welded where the game's own vertices meet, nothing more
                if k not in index:
                    index[k] = len(verts)
                    verts.append(cv.to_blender(p, scale))
                f.append(index[k])
            if len(set(f)) != 3:
                continue
            k = min((f[i], f[(i + 1) % 3], f[(i + 2) % 3]) for i in range(3))     # same face, same winding
            if tuple(sorted(f)) in seen:
                # the same corners again (a volume's back-to-back pair, or a repeated face): the stencil counts every
                # face, so dropping one opened Spiral Highway's volumes (a dark wedge over the road). Blender keeps one face
                # per set of vertices, so this one gets its own copies
                f2 = []
                for i in f:
                    verts.append(verts[i])
                    f2.append(len(verts) - 1)
                seen.add(k)
                faces.append(cv.flip_winding(tuple(f2)))
                continue
            seen.add(k)
            seen.add(tuple(sorted(f)))
            faces.append(cv.flip_winding(tuple(f)))
    total, coll = 0, None
    for shader, (verts, _index, faces, _seen) in groups.items():
        if not faces:
            continue
        if coll is None:
            coll = bpy.data.collections.new('ShadowCasters')
            parent.children.link(coll)
            coll.pd_role = 'SHADOWS'
        name = '%s_shadow_casters%s' % (stage, '' if shadow_dynamic(shader) else '_stretched')
        me = bpy.data.meshes.new(name)
        me.from_pydata(verts, [], faces)
        me.validate()
        me.update()
        ob = bpy.data.objects.new(name, me)
        ob.hide_render = True                      # real-time only: kept out of the lighting bake
        ob.display_type = 'WIRE'
        from . import roundtrip
        if roundtrip.ENABLED:                      # fallback only: the game's meshes
            ob['pd_meshes'] = [[0, mi] for mi in sources[shader]]
        if not shadow_dynamic(shader):
            ob['pd_shadow_stretched'] = True       # already stretched along this map's sun: written back as is
        coll.objects.link(ob)
        total += len(faces)
    return total


def shadow_dynamic(shader):
    return shader == 'sshadowch'


STAGE_SHADERS = ('sd', 'sbts', 'sdrefs', 'sbtsrefs', 'sdal', 'sbtsal', 'sdrefsal', 'sbtsrefsal')
# the game's sky dome (battle stage root 2): clouds and the vertex-coloured domes, with their highlight settings
SKY_SHADERS = ('sbtscloud3', 'svc', 'sc', 'scal', 'svcal')


def pd_maps(entry):
    """Whether a game material is imported as a PD Stage Shader material (its maps and highlight as the shader's
    inputs): the add-on's stage shaders, and every other game shader with a normal map (role 2) or reflection map
    (role 4) slot or a highlight colour. A plain material holds the diffuse image only: the town's dbts materials
    lost their normal maps (slot written empty: the shader's N.L from an empty texture, the areas far darker) and
    their highlight colour (7f7f7f -> 0)."""
    if entry['shader'] in STAGE_SHADERS:
        return True
    if entry['shader'].startswith(('sshadow', 'sbtscloud')):
        return False
    raw = bytes(entry['raw'])
    roles = struct.unpack_from('<H', raw, 0x16)[0]
    if any(((roles >> (4 * k)) & 0xF) in (2, 4) for k in range(4)):
        return True
    return any(raw[0x34:0x37])


def keeps_game_maps(shader, entry=None):
    """True for a game material the import gives the game's maps by slot role (diffuse 1, normal 2, reflection 4),
    the specular colour of +0x34 and the shine mask from PD_Light alpha, so the export writes the same texture slots,
    specular word and vertex alpha: the add-on's stage shaders, every shader the export writes from its game settings
    (alr_build.SHADER_FORMAT: sbtsrefp, sdrefp, sbpxrefpal, sbpx, sv ...; they lost their normal and reflection
    slots, specular colour and vertex alpha: the dark floors of st03 / st13 / st23) and every other game shader with
    a normal / reflection slot or a highlight colour (pd_maps: the town's dbts, lbts)."""
    if shader.startswith('sshadow'):
        return True                              # the game's settings incl. +0x34 written back; no maps
    return shader in STAGE_SHADERS or shader in alr_build.SHADER_FORMAT or (entry is not None and pd_maps(entry))


def build_mesh(name, b, h, texs, records, scale, image_of, stage, transform=None, shadows=False):
    """One Blender mesh from several .alr mesh records (node transforms applied, then `transform`, a 4x4 nested
    list in game space, if given), with a material per game material. Returns the mesh, or None if empty.
    shadows: only the shadow-volume records (sshadow*: an object's own shadow, every vertex with the game's normal,
    the zero-area edge strips kept as faces), else every record but those."""
    verts, faces, uvs, cols, mat_index, mats = [], [], [], [], [], []
    nrms = []                                   # the game's vertex normals (Blender space), or None
    mat_key = {}
    for m in records:
        entry = m['materials'][m['material']] if m['material'] < len(m['materials']) else None
        shader = entry['shader'] if entry else ''
        if shader.startswith('sshadow') != bool(shadows) or m['vbuf'] >= len(m['vbufs']):
            continue
        tris = alr.triangles_from_indices(m['indices'], m['primitive'])
        if not tris:
            continue
        vb = m['vbufs'][m['vbuf']]
        pos, uv, _uv2 = alr.read_vertices(b, h['resource_offset'], vb)
        col = alr.read_colours(b, h['resource_offset'], vb)
        nrm = alr.read_normals(b, h['resource_offset'], vb)
        mtx = alr.node_matrix(m['nodes'], m['node']) if m['node'] < len(m['nodes']) else alr._identity()
        if transform is not None:
            mtx = alr._mul(mtx, transform)
        if entry is not None and (keeps_game_maps(shader, entry) or shader == 'sbtscloud3'):   # cloud shell: Scrolling
            t0 = entry['textures'][0]
            tex_name = texs[t0]['name'] if t0 is not None and t0 < len(texs) else 'untextured'
            key = '%s_%s_%s_%s_%s' % (stage, shader, tex_name, bytes(entry['raw'][0x34:0x38]).hex(), _settings_key(entry))
            make = lambda e=entry, k=key: tag_game_material(_game_material(k, e, texs, image_of), e, texs, image_of)
        else:
            t0 = entry['textures'][0] if entry else None
            img = image_of(t0) if t0 is not None and t0 < len(texs) else None
            key = '%s_%s_%s' % (stage, shader or 'mat', texs[t0]['name'] if img is not None else 'untextured') + \
                ('_' + _settings_key(entry) if entry else '')
            make = lambda k=key, i=img, e=entry: tag_game_material(_material(k, i), e, texs, image_of)
        if key not in mat_key:
            mat_key[key] = len(mats)
            mats.append(bpy.data.materials.get(key) or make())
        mi = mat_key[key]
        used = sorted({i for t in tris for i in t})
        base = len(verts)
        remap = {old: base + new for new, old in enumerate(used)}
        verts += [cv.to_blender(alr.apply(mtx, pos[i]), scale) for i in used]
        uvs += [uv[i] if uv else (0.0, 0.0) for i in used]
        cols += [col[i] if col else (255, 255, 255, 255) for i in used]
        o = alr.apply(mtx, (0.0, 0.0, 0.0))
        nrms += [_turned(mtx, o, nrm[i]) if nrm else None for i in used]
        seen = set()
        for t in tris:
            if shadows and len({tuple(pos[i]) for i in t}) < 3:
                continue                  # a shadow volume's zero-area edge strip: the export makes them again
            f = cv.flip_winding(tuple(remap[i] for i in t))
            if frozenset(f) in seen:                       # double-sided: own vertex copies (see import_visuals)
                f2 = []
                for k in f:
                    verts.append(verts[k])
                    uvs.append(uvs[k])
                    cols.append(cols[k])
                    nrms.append(nrms[k])
                    f2.append(len(verts) - 1)
                f = tuple(f2)
            seen.add(frozenset(f))
            faces.append(f)
            mat_index.append(mi)
    if not faces:
        return None
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    layer = me.uv_layers.new(name='UVMap')
    for poly in me.polygons:
        for li in poly.loop_indices:
            u, v = uvs[me.loops[li].vertex_index]
            layer.data[li].uv = (u, 1.0 - v)
    light = me.color_attributes.new(LIGHT_LAYER, 'BYTE_COLOR', 'POINT')
    light.data.foreach_set('color_srgb', [c / 255 for col in cols for c in col])
    me.color_attributes.active_color = light
    for mat in mats:
        me.materials.append(mat)
    me.polygons.foreach_set('material_index', mat_index)
    me.validate()
    if any(n is not None for n in nrms) and len(nrms) == len(me.vertices):
        # (shadow volumes too: their normals are each face's, turned by the joint as the game turns them; the
        # edge strips were left out above, so no zero-area face spoils the custom normals)
        # the game's vertex normals as custom normals (as the stage's meshes): the export writes the corner
        # normals, so the objects keep the game's smooth shading (Panorama's pillars: smooth octagons, not facets)
        try:
            me.normals_split_custom_set_from_vertices([n if n is not None else (0.0, 0.0, 0.0) for n in nrms])
        except (RuntimeError, ValueError):
            pass
    me.update()
    return me
