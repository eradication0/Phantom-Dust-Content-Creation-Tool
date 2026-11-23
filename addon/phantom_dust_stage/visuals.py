"""Import a map's visible model (Map/stNN.alr) as a reference: stage, background and sky.

Each mesh record becomes an object with its UVs. Meshes using the stage shaders (sd, sbts, sdrefs, sbtsrefs) get a
PD Stage Shader material with the game's maps, highlight colour and shininess (shine mask = PD_Light alpha);
other shaders (sky, effects) get a plain PD material with their colour texture. Shadow meshes
(shaders starting with "sshadow") are not drawn: the stage's shadow volumes (sshadowch) go to a ShadowCasters
collection instead. Vertex positions get their node transforms applied, then the
same game -> Blender conversion as collision, so the model lines up with the imported collision.
"""
import os
import struct
import tempfile

import bpy
import numpy as np

from ._lib import alr
from . import convert as cv
from . import pd_material

ROOT_NAMES = {0: 'Stage', 1: 'Background', 2: 'Sky'}


def _image(b, t, cache, tmpdir):
    if t['index'] in cache:
        return cache[t['index']]
    img = None
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
        except (RuntimeError, ValueError):
            img = None
    cache[t['index']] = img
    return img


LIGHT_LAYER = 'PD_Light'     # colour attribute holding the baked lighting (exported as vertex colour)


def _material(name, img):
    """A PD Stage Shader material showing `img` (used for new scenes: no highlight)."""
    return pd_material.make_material(name, diffuse=img)


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
        return pd_material.setup(mat, diffuse=maps.get(1), normal=maps.get(2), shine_from_light_alpha=False)
    if entry['shader'].endswith('al'):                 # the blended variant (st07 glass sdal): see-through
        mat.pd_transparent = True
    return pd_material.setup(mat, diffuse=maps.get(1), normal=maps.get(2),
                             reflection=maps.get(4), specular=(_linear(r), _linear(g), _linear(b)),
                             shininess=max(1, min(127, power)) if (r or g or b) else 20,
                             shine_from_light_alpha=True)


def import_visuals(context, alr_path, parent, scale, roots=(0, 1, 2)):
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
                light = me.color_attributes.new(LIGHT_LAYER, 'BYTE_COLOR', 'POINT')
                for new_i, old_i in enumerate(used):
                    c = cols[old_i] if cols else (255, 255, 255, 255)
                    light.data[new_i].color_srgb = (c[0] / 255, c[1] / 255, c[2] / 255, c[3] / 255)
                me.color_attributes.active_color = light
                me.validate()
                me.update()
                if mat_entry is not None and (shader in STAGE_SHADERS or (shader == 'sbtscloud3' and ri != 2)):
                    tex_i = mat_entry['textures'][0]
                    tex_name = texs[tex_i]['name'] if tex_i is not None and tex_i < len(texs) else 'untextured'
                    extra = bytes(mat_entry['raw'][0x3C:0x48]).hex() if shader == 'sbtscloud3' else ''
                    me.materials.append(_game_material(
                        '%s_%s_%s_%s%s' % (stage, shader, tex_name, bytes(mat_entry['raw'][0x34:0x38]).hex(), extra),
                        mat_entry, texs, lambda t: _image(b, texs[t], cache, tmpdir)))
                else:
                    tex_i = mat_entry['textures'][0] if mat_entry else None
                    img = _image(b, texs[tex_i], cache, tmpdir) if tex_i is not None and tex_i < len(texs) else None
                    tex_name = texs[tex_i]['name'] if img is not None else 'untextured'
                    me.materials.append(_material('%s_%s_%s' % (stage, shader or 'mat', tex_name), img))
                ob = bpy.data.objects.new(name, me)
                coll.objects.link(ob)
                n_obj += 1
                n_tri += len(faces)
            report.append('%s: %d meshes, %d triangles' % (coll.name, n_obj, n_tri))
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
    for m in alr.meshes(b, h['roots'][0]):
        entry = m['materials'][m['material']] if m['material'] < len(m['materials']) else None
        if entry is None or entry['shader'] not in groups or m['vbuf'] >= len(m['vbufs']):
            continue
        verts, index, faces, seen = groups[entry['shader']]
        pos = alr.read_vertices(b, h['resource_offset'], m['vbufs'][m['vbuf']])[0]
        mtx = alr.node_matrix(m['nodes'], m['node']) if m['node'] < len(m['nodes']) else alr._identity()
        for t in alr.triangles_from_indices(m['indices'], m['primitive']):
            f = []
            for i in t:
                p = alr.apply(mtx, pos[i])
                k = tuple(round(c, 3) for c in p)
                if k not in index:
                    index[k] = len(verts)
                    verts.append(cv.to_blender(p, scale))
                f.append(index[k])
            if len(set(f)) == 3 and tuple(sorted(f)) not in seen:
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
        if not shadow_dynamic(shader):
            ob['pd_shadow_stretched'] = True       # already stretched along this map's sun: written back as is
        coll.objects.link(ob)
        total += len(faces)
    return total


def shadow_dynamic(shader):
    return shader == 'sshadowch'


STAGE_SHADERS = ('sd', 'sbts', 'sdrefs', 'sbtsrefs', 'sdal', 'sbtsal', 'sdrefsal', 'sbtsrefsal')


def build_mesh(name, b, h, texs, records, scale, image_of, stage, transform=None):
    """One Blender mesh from several .alr mesh records (node transforms applied, then `transform`, a 4x4 nested
    list in game space, if given), with a material per game material. Returns the mesh, or None if empty."""
    verts, faces, uvs, cols, mat_index, mats = [], [], [], [], [], []
    mat_key = {}
    for m in records:
        entry = m['materials'][m['material']] if m['material'] < len(m['materials']) else None
        shader = entry['shader'] if entry else ''
        if shader.startswith('sshadow') or m['vbuf'] >= len(m['vbufs']):
            continue
        tris = alr.triangles_from_indices(m['indices'], m['primitive'])
        if not tris:
            continue
        vb = m['vbufs'][m['vbuf']]
        pos, uv, _uv2 = alr.read_vertices(b, h['resource_offset'], vb)
        col = alr.read_colours(b, h['resource_offset'], vb)
        mtx = alr.node_matrix(m['nodes'], m['node']) if m['node'] < len(m['nodes']) else alr._identity()
        if transform is not None:
            mtx = alr._mul(mtx, transform)
        if entry is not None and shader in STAGE_SHADERS:
            t0 = entry['textures'][0]
            tex_name = texs[t0]['name'] if t0 is not None and t0 < len(texs) else 'untextured'
            key = '%s_%s_%s_%s' % (stage, shader, tex_name, bytes(entry['raw'][0x34:0x38]).hex())
            make = lambda e=entry, k=key: _game_material(k, e, texs, image_of)
        else:
            t0 = entry['textures'][0] if entry else None
            img = image_of(t0) if t0 is not None and t0 < len(texs) else None
            key = '%s_%s_%s' % (stage, shader or 'mat', texs[t0]['name'] if img is not None else 'untextured')
            make = lambda k=key, i=img: _material(k, i)
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
        seen = set()
        for t in tris:
            f = cv.flip_winding(tuple(remap[i] for i in t))
            if frozenset(f) in seen:                       # double-sided: own vertex copies (see import_visuals)
                f2 = []
                for k in f:
                    verts.append(verts[k])
                    uvs.append(uvs[k])
                    cols.append(cols[k])
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
    me.update()
    return me
