"""Blender meshes -> model meshes for the .alr writer (stage model and object models).

Meshes under a Visuals collection replace the game original's main stage model. A child collection named
"Background..." or "Sky..." replaces that model instead (the import creates those names).

Materials: a material using the PD Stage Shader (pd_material.py) gives the texture, normal map, reflection map,
highlight colour/shininess, shine mask and baked light; the game shader follows from the maps it uses (sd, sbts,
sdrefs, sbtsrefs). Any other material exports as before: its image, baked light from "PD_Light" (or the active
colour attribute), and no highlight.

Per triangle: position, the corner normal, the active UV map (game V = 1 - Blender V), the vertex colour
(RGB = baked light, A = shine mask) and, for normal-mapped materials, Blender's tangent and bitangent for that
UV map (the game reads them as stored: tangent = +U, binormal = +V in Blender's UV space, so OpenGL-style
normal maps work unchanged).

Textures: an image whose name matches a texture in the game original (as the import names them) reuses that
texture. Others are added resized to a power of two (largest side at most 512), DXT1/DXT5 compressed with a full
mip chain like the game's own. (Plain BGRA with mip levels showed rainbow streaks at a distance in game: the game
never uses that format above 128 px, so "Uncompressed" now writes the top level only, as its own plain textures.)
A reflection map's alpha is multiplied by the material's Reflection Strength.
"""
import math

import bpy
import re

import numpy as np
from mathutils import Matrix

from ._lib import alr, alr_build
from . import convert as cv
from . import pd_material

SLOTS = (('background', 1), ('sky', 2))
LIGHT_LAYER = 'PD_Light'
MAX_TEX = 512          # the game's own textures are at most ~0.7 MB each (512 px); a 1024 light map
                       # (1.4 MB) drew rainbow streaks at a distance, as did plain 512 px textures (1.4 MB)
UV_LIMIT = 7.99                      # UVs are stored as int16 / 4096
LM_UV_LIMIT = 15.99                  # light-mapped meshes (lbts): uint16 / 4096


class VisualsError(Exception):
    pass


def _slot_for(name, inherited):
    low = name.lower()
    for prefix, slot in SLOTS:
        if low.startswith(prefix):
            return slot
    return inherited


def _image_of(mat):
    if mat is None or not mat.use_nodes or mat.node_tree is None:
        return None
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is not None and bsdf.inputs['Base Color'].is_linked:
        todo, seen = [bsdf.inputs['Base Color'].links[0].from_node], set()
        while todo:
            n = todo.pop()
            if n.name in seen:
                continue
            seen.add(n.name)
            if n.type == 'TEX_IMAGE' and n.image is not None:
                return n.image
            for inp in n.inputs:
                for link in inp.links:
                    todo.append(link.from_node)
    return next((n.image for n in nt.nodes if n.type == 'TEX_IMAGE' and n.image is not None), None)


def game_texture_name(name):
    name = re.sub(r'\.\d{3}$', '', name).lower()
    name = re.sub(r'[^0-9a-z_]', '_', name)
    return name[:12] or 'tex'


def image_levels(img, alpha_scale=1.0, normal_strength=1.0, lightmap_ambient=None, max_size=MAX_TEX,
                 lightmap_glow=None, tint=(1.0, 1.0, 1.0), alpha_value=None):
    """(width, height, [BGRA bytes per mip, top row first]) for a Blender image (alpha times alpha_scale; a normal
    map's bumps scaled by normal_strength: x and y times the strength, then made unit length again)."""
    w, h = img.size
    if w == 0 or h == 0:
        raise VisualsError('image %s has no pixels (is the file missing?)' % img.name)
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)[::-1].copy()                      # Blender stores bottom row first
    if lightmap_ambient is not None:
        # a baked light map for the lbts shader, which draws texture x (ambient + light map): the baked light
        # (sun, lamps, bounces; the game adds the stage ambient itself) is stored as is. Alpha 0 (the shader adds the light map once more by its alpha)
        # Light brighter than white (lamps up close: the bake is a float image) goes into the alpha: the shader
        # adds light map x alpha once more on top, untextured, like the campaign's lamp hot spots. Alpha = the
        # part above white as a share of the stored light (at most 1: up to twice the light, then white).
        raw = px[..., :3].copy()
        px[..., :3] = np.clip(raw, 0.0, 1.0)
        over = (raw - px[..., :3]).max(axis=-1)
        px[..., 3] = np.clip(over / np.maximum(px[..., :3].max(axis=-1), 1e-4), 0.0, 1.0)
        if lightmap_glow is not None and tuple(lightmap_glow.size) == (w, h):
            # glow (Emission Map): the shader adds light map x alpha on top, so where something glows the light
            # map gets at least the glow colour and its alpha the share that makes light map x alpha = glow
            g = np.empty(w * h * 4, dtype=np.float32)
            lightmap_glow.pixels.foreach_get(g)
            g = np.clip(g.reshape(h, w, 4)[::-1][..., :3], 0.0, 1.0)
            peak = g.max(axis=-1)
            on = peak > 1.0 / 255
            lit = np.where(on[..., None], np.maximum(px[..., :3], g), px[..., :3])
            px[..., :3] = lit
            px[..., 3] = np.maximum(px[..., 3], np.where(on, np.clip(peak / np.maximum(lit.max(axis=-1), 1e-4),
                                                                      0.0, 1.0), 0.0))
    if alpha_scale != 1.0:
        px[..., 3] *= alpha_scale
    if alpha_value is not None:                                # a fixed alpha (scrolling normal maps)
        px[..., 3] = alpha_value
    if tuple(tint) != (1.0, 1.0, 1.0):                         # the material's Diffuse Color
        px[..., :3] *= np.array(tint, dtype=np.float32)
    if normal_strength != 1.0:
        n = px[..., :3] * 2.0 - 1.0
        n[..., :2] *= normal_strength
        n[..., 2] = np.maximum(n[..., 2], 1e-4)
        n /= np.linalg.norm(n, axis=-1, keepdims=True)
        px[..., :3] = n * 0.5 + 0.5
    W = 1 << int(math.floor(math.log2(min(w, max_size))))
    H = 1 << int(math.floor(math.log2(min(h, max_size))))
    W, H = max(W, 4), max(H, 4)
    if (W, H) != (w, h):                                       # box-average into the power-of-two size
        ys = (np.arange(H + 1) * h / H).astype(int)
        xs = (np.arange(W + 1) * w / W).astype(int)
        csum = np.zeros((h + 1, w + 1, 4), dtype=np.float64)
        csum[1:, 1:] = px.cumsum(0).cumsum(1)
        area = np.maximum(1, (ys[1:] - ys[:-1])[:, None] * (xs[1:] - xs[:-1])[None, :])[..., None]
        px = (csum[ys[1:]][:, xs[1:]] - csum[ys[:-1]][:, xs[1:]] - csum[ys[1:]][:, xs[:-1]]
              + csum[ys[:-1]][:, xs[:-1]]) / area
    levels = []
    cur = px.astype(np.float32)
    while True:
        b8 = np.clip(np.round(cur * 255), 0, 255).astype(np.uint8)[..., [2, 1, 0, 3]]
        levels.append(b8.tobytes())
        hh, ww = cur.shape[:2]
        if hh == 1 and ww == 1:
            break
        cur = cur.reshape(max(1, hh // 2), 2 if hh > 1 else 1, max(1, ww // 2), 2 if ww > 1 else 1, 4).mean(axis=(1, 3))
    return W, H, levels


def compress(levels, w, h):
    """BGRA mip levels -> dict(levels, format) compressed like the game's own textures (DXT1 when opaque,
    DXT5 with alpha): a quarter to an eighth of the size. Falls back to plain BGRA if numpy can't do it."""
    from ._lib import dxt
    try:
        arrs, lw, lh = [], w, h
        for lvl in levels:
            a = np.frombuffer(lvl, dtype=np.uint8).reshape(lh, lw, 4)[..., [2, 1, 0, 3]]
            arrs.append(a)
            lw, lh = max(1, lw // 2), max(1, lh // 2)
        alpha = dxt.needs_alpha(arrs[0])
        out = [dxt.encode(a, alpha) for a in arrs]
        return dict(levels=[d for _f, d in out], format=out[0][0])
    except (ValueError, MemoryError):
        return dict(levels=levels)


class Textures:
    """Texture references shared by every model in one export: map textures reused by name, others added."""

    def __init__(self, base_textures, compress=False):
        # 'NONE': plain BGRA, top level only (finish() drops the mip levels); anything else: DXT1/DXT5 with mip
        # levels like the game's own. Plain BGRA *with* mip levels drew rainbow streaks in game (the game's own
        # plain textures are at most 128 px), so it is never written; the old 'AUTO' now means compressed.
        self.mode = 'NONE' if compress == 'NONE' else 'ALL'
        self.compress = self.mode == 'ALL'
        self.base_by_name = {t['name']: t['index'] for t in base_textures}
        self.new = []
        self.lightmaps = []                            # (texture dict, image, ambient), filled by finish_lightmaps
        self.by_content = {}                           # identical images (copies like wall.001) share one texture
        self.key = {}
        self.reused = 0

    def ref(self, img, alpha_scale=1.0, normal_strength=1.0, tint=(1.0, 1.0, 1.0), alpha_value=None):
        """Texture ref for an image (times `tint`, sRGB 0-1); no image: a 4 x 4 texture of the colour `tint`.
        alpha_value: every pixel's alpha set to it (0-1)."""
        tint = tuple(round(max(0.0, min(1.0, x)), 3) for x in tint)
        key = (img.name if img is not None else None, round(alpha_scale, 3), round(normal_strength, 3), tint,
               alpha_value)
        if key in self.key:
            return self.key[key]
        if img is None:
            ref = ('new', len(self.new))
            a = int(round(max(0.0, min(1.0, alpha_scale)) * 255))
            px = bytes(int(round(c * 255)) for c in (tint[2], tint[1], tint[0])) + bytes((a,))   # BGRA
            name = 'pd_white' if tint == (1.0, 1.0, 1.0) else 'pd_c%02x%02x%02x' % tuple(int(round(c * 255))
                                                                                    for c in tint)
            if a != 255:
                name += '_a%02x' % a
            self.new.append(dict(name=name, width=4, height=4, levels=[px * 16, px * 4, px]))
        elif alpha_scale == 1.0 and normal_strength == 1.0 and tint == (1.0, 1.0, 1.0) and alpha_value is None \
                and game_texture_name(img.name) in self.base_by_name:
            ref = ('base', self.base_by_name[game_texture_name(img.name)])
            self.reused += 1
        else:
            w, h, levels = image_levels(img, alpha_scale, normal_strength, tint=tint, alpha_value=alpha_value)
            import hashlib
            digest = (w, h, hashlib.md5(b''.join(levels)).digest())   # copies of one image (wall.001...) once
            ref = self.by_content.get(digest)
            if ref is None:
                ref = ('new', len(self.new))
                self.by_content[digest] = ref
                self.new.append(dict(name=game_texture_name(img.name), width=w, height=h,
                                     **(compress(levels, w, h) if self.compress else dict(levels=levels))))
            else:
                self.shared = getattr(self, 'shared', 0) + 1
        self.key[key] = ref
        return ref

    def finish(self, budget_bytes, skip=()):
        """Fit all new textures (light maps have their own budget: `skip`) into `budget_bytes`: compressed (or, in
        NONE mode, cut to their top level, see __init__), the biggest halved (top mip level dropped) until they
        fit. Returns (0, halved): nothing is compressed just to fit any more."""
        size = lambda t: sum(len(l) for l in t['levels'])
        mine = [t for t in self.new if id(t) not in skip]
        total = sum(size(t) for t in mine)
        n = 0
        if self.mode == 'ALL':          # the small plain helpers (pd_white, pd_flatnrm...) compressed too
            for t in mine:
                if 'format' not in t:
                    t.update(compress(t['levels'], t['width'], t['height']))
            total = sum(size(t) for t in mine)
        halved = 0
        while total > budget_bytes:
            t = max(mine, key=size)
            if len(t['levels']) < 2 or min(t['width'], t['height']) <= 64:
                break
            before = size(t)
            t['levels'] = t['levels'][1:]
            t['width'], t['height'] = max(1, t['width'] // 2), max(1, t['height'] // 2)
            if 'mips' in t:
                t['mips'] = len(t['levels'])
            total += size(t) - before
            halved += 1
        if self.mode == 'NONE':         # plain textures: top level only (see __init__)
            for t in mine:
                if 'format' not in t and len(t['levels']) > 1:
                    t['levels'] = t['levels'][:1]
                    t['mips'] = 1
            total = sum(size(t) for t in mine)
        self.auto_total = total
        return n, halved

    def lightmap(self, img, ambient, glow=None):
        """A baked light map (lightbake PDLight_ image) as a new texture, see image_levels. Its pixels are made in
        finish_lightmaps(), which fits all light maps into the light map budget."""
        key = ('lightmap', img.name, tuple(round(x, 3) for x in ambient), glow.name if glow else None)
        if key not in self.key:
            self.key[key] = ('new', len(self.new))
            t = dict(name='pdlm%04d' % len(self.new), width=0, height=0, levels=[])
            self.new.append(t)
            self.lightmaps.append((t, img, ambient, glow))
        return self.key[key]

    def finish_lightmaps(self, budget_bytes):
        """Make the light maps' pixels, halving the biggest ones first until they all fit `budget_bytes` (as
        written: compressed light maps take a byte per pixel, plain ones four). Returns how many were shrunk."""
        if not self.lightmaps:
            return 0
        per_px = 1                                                   # always DXT5 (see __init__)
        sizes = [min(MAX_TEX, 1 << int(math.floor(math.log2(max(1, min(img.size[0], img.size[1]))))))
                 for _t, img, _a, _g in self.lightmaps]
        cost = lambda z: z * z * per_px * 4 // 3                     # with the mip levels
        shrunk = set()
        while sum(cost(z) for z in sizes) > budget_bytes:
            k = max(range(len(sizes)), key=lambda i: sizes[i])
            if sizes[k] <= 32:
                break
            sizes[k] //= 2
            shrunk.add(k)
        for (t, img, ambient, glow), z in zip(self.lightmaps, sizes):
            w, h, levels = image_levels(img, lightmap_ambient=ambient, max_size=z, lightmap_glow=glow)
            t.update(width=w, height=h, levels=levels)
            t.update(compress(levels, w, h))                         # DXT5: keeps the alpha at 0
        self.lightmap_bytes = sum(sum(len(l) for l in t['levels']) for t, _i, _a, _g in self.lightmaps)
        return len(shrunk)

    def flat_normal(self):
        """A 4 x 4 flat normal map, for light-mapped surfaces without one (as the hub does)."""
        key = ('flat_normal',)
        if key not in self.key:
            self.key[key] = ('new', len(self.new))
            self.new.append(dict(name='pd_flatnrm', width=4, height=4,
                                 levels=[b'\xff\x80\x80\xff' * 16, b'\xff\x80\x80\xff' * 4, b'\xff\x80\x80\xff']))
        return self.key[key]

    # Scrolling (sbtscloud3) works its alpha out from the colour texture's and both normal maps' alphas ("overlay"):
    # normal maps with alpha 127/255 leave the colour texture's alpha as it is (alr_build.SCROLL_TEMPLATE)
    SCROLL_NORMAL_ALPHA = 127 / 255

    def scroll_flat_normal(self):
        key = ('scroll_flat_normal',)
        if key not in self.key:
            self.key[key] = ('new', len(self.new))
            px = b'\xff\x80\x80\x7f'                                # BGRA: flat, alpha 127
            self.new.append(dict(name='pd_flatscr', width=4, height=4, levels=[px * 16, px * 4, px]))
        return self.key[key]

    def material(self, settings):
        """Writer material dict (texture refs, highlight) for pd_material.read() settings."""
        tint = settings.get('diffuse_tint', (1.0, 1.0, 1.0))
        if settings['diffuse'] is None and settings.get('pd'):    # no texture: the Diffuse colour
            tint = tuple(a * b for a, b in zip(settings.get('diffuse_colour', (1.0, 1.0, 1.0)), tint))
        if settings.get('scroll'):
            blend = settings.get('scroll_blend', 'OPAQUE')
            fade = 1.0 - settings.get('transparency', 0.0) if blend == 'ALPHA' else 1.0
            strength = settings.get('normal_strength', 1.0)
            na = self.ref(settings['normal'], normal_strength=strength, alpha_value=self.SCROLL_NORMAL_ALPHA) \
                if settings['normal'] is not None else self.scroll_flat_normal()
            nb_img = settings.get('normal_b') or settings['normal']
            nb = self.ref(nb_img, normal_strength=strength, alpha_value=self.SCROLL_NORMAL_ALPHA) \
                if nb_img is not None else self.scroll_flat_normal()
            return dict(diffuse=self.ref(settings['diffuse'], fade, tint=tint), transparent=False, normal=na,
                        reflection=None, specular=(0, 0, 0, 0),
                        scroll=dict(normal_a=na, normal_b=nb, speeds=tuple(settings['scroll_speeds']), blend=blend))
        see = bool(settings.get('transparent'))      # blended shader (..al): the slider fades the texture's alpha
        return dict(diffuse=self.ref(settings['diffuse'], 1.0 - settings.get('transparency', 0.0) if see else 1.0,
                                     tint=tint),
                    transparent=see,
                    normal=self.ref(settings['normal'], normal_strength=settings.get('normal_strength', 1.0))
                    if settings['normal'] is not None else None,
                    reflection=self.ref(settings['reflection'], settings['reflection_strength'])
                    if settings['reflection'] is not None else None,
                    specular=tuple(settings['specular']))


def _corner_reader(me, source, srgb=True):
    """Function (loop index, vertex index, polygon index) -> (r, g, b, a) floats for an attribute, or None."""
    if source is None:
        return None
    name = source[1]
    attr = me.attributes.get(name) if name else me.color_attributes.active_color
    if attr is None:
        return None
    data = attr.data
    domain = attr.domain
    if attr.data_type in ('FLOAT_COLOR', 'BYTE_COLOR'):
        get = (lambda d: tuple(d.color_srgb)) if srgb else (lambda d: tuple(d.color))
    elif attr.data_type in ('FLOAT', 'INT', 'INT8', 'BOOLEAN'):
        get = lambda d: (float(d.value),) * 3 + (float(d.value),)
    else:
        return None

    def read(li, vi, pi):
        i = li if domain == 'CORNER' else vi if domain == 'POINT' else pi if domain == 'FACE' else None
        return get(data[i]) if i is not None else (1.0, 1.0, 1.0, 1.0)
    return read


def _shine_value(source, reader, li, vi, pi):
    if source[0] == 'const':
        return source[1]
    if reader is None:
        return 1.0
    c = reader(li, vi, pi)
    if source[2] == 'A':
        return c[3]
    return (c[0] + c[1] + c[2]) / 3 if source[2] in ('RGB', 'F') else c[0]


def mesh_parts(depsgraph, ob, matrix, scale, textures, stats, parts=None):
    """Add one Blender mesh object's triangles to `parts` ({material key: part}), transformed by `matrix`
    (Blender space) then converted to game space. Returns `parts`."""
    parts = {} if parts is None else parts
    ev = ob.evaluated_get(depsgraph)
    me = ev.to_mesh()
    try:
        if any(p.loop_total > 4 for p in me.polygons):  # tangents (normal and light maps) need tris and quads
            import bmesh
            bm = bmesh.new()
            bm.from_mesh(me)
            bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
            bm.to_mesh(me)
            bm.free()
        me.calc_loop_triangles()
        m3 = matrix.to_3x3()
        nmat = m3.inverted_safe().transposed()
        flip = matrix.determinant() < 0
        uvl = next((l for l in me.uv_layers if l.active_render and l.name != 'PD_LightUV'), None) or \
            next((l for l in me.uv_layers if l.name != 'PD_LightUV'), None)      # the textures' UV map
        lm_ref = lm_uv = None
        if getattr(bpy.context.scene, 'pd_bake_use', False):  # Bake Lighting: a light map on a second UV map
            from . import lightbake
            light = lightbake.baked_light(ob)
            if light is not None and me.uv_layers.get(lightbake.UV_NAME) is not None and uvl is not None:
                lm_uv = me.uv_layers[lightbake.UV_NAME]
                lm_ref = textures.lightmap(light, lightbake.game_ambient(bpy.context.scene), lightbake.baked_glow(ob))
        cnormals = me.corner_normals
        co = [matrix @ v.co for v in me.vertices]
        slots_mat = [s.material for s in ob.material_slots]
        for i, m in enumerate(slots_mat):                # the bake's viewport preview: export the mesh's own
            if m is not None and m.name.startswith('PDBakeView_'):
                slots_mat[i] = ob.data.materials[i] if i < len(ob.data.materials) else None
        legacy_col = me.color_attributes.get(LIGHT_LAYER) or me.color_attributes.active_color
        legacy_read = _corner_reader(me, ('attr', legacy_col.name, 'RGB')) if legacy_col is not None else None
        settings, readers = {}, {}
        tangents = None
        for lt in me.loop_triangles:
            mi = lt.material_index
            mat = slots_mat[mi] if mi < len(slots_mat) else None
            if mi not in settings:
                st = pd_material.read(mat)
                gmat = textures.material(st)
                if gmat.get('scroll'):                  # scrolling: tangents always, white light, alpha 255
                    st = dict(st, normal=st['normal'] or 'flat', light=('const', (255, 255, 255)),
                              shine=('const', 1.0))
                elif lm_ref is not None and not gmat['transparent']:   # light-mapped: lbts (no reflection map;
                    # lbts has no blended variant, so transparent materials keep vertex light)
                    gmat = dict(diffuse=gmat['diffuse'], lightmap=lm_ref,
                                normal=gmat['normal'] or textures.flat_normal(), reflection=None,
                                specular=gmat['specular'])
                    st = dict(st, normal=st['normal'] or 'flat', light=('const', (255, 255, 255)))
                settings[mi] = (st, gmat)
                light = st['light']
                light_read = legacy_read if light is None else (
                    _corner_reader(me, light) if light[0] == 'attr' else None)
                shine_read = _corner_reader(me, st['shine'], srgb=False) if st['shine'][0] == 'attr' else None
                readers[mi] = (light_read, shine_read)
                if st['normal'] is not None and tangents is None:
                    if uvl is None:
                        raise VisualsError('%s has a normal map but no UV map' % ob.name)
                    try:
                        me.calc_tangents(uvmap=uvl.name)
                    except RuntimeError as e:
                        raise VisualsError('%s: tangents for its normal map failed (%s); triangulate n-gons'
                                           % (ob.name, e))
                    tangents = True
            st, gmat = settings[mi]
            light_read, shine_read = readers[mi]
            bump = st['normal'] is not None
            key = repr(gmat)
            part = parts.setdefault(key, dict(verts=[], index={}, tris=[], material=gmat))
            corners = []
            for li, vi in zip(lt.loops, lt.vertices):
                uv = (uvl.data[li].uv[0], 1.0 - uvl.data[li].uv[1]) if uvl else (0.0, 0.0)
                n = nmat @ cnormals[li].vector
                pi = lt.polygon_index
                if st['light'] is not None and st['light'][0] == 'const':
                    rgb = st['light'][1]
                elif light_read is not None:
                    rgb = tuple(int(round(max(0.0, min(1.0, x)) * 255)) for x in light_read(li, vi, pi)[:3])
                else:
                    rgb = (255, 255, 255)
                a = _shine_value(st['shine'], shine_read, li, vi, pi)
                c = rgb + (int(round(max(0.0, min(1.0, a)) * 255)),)
                extra = ()
                if bump:
                    loop = me.loops[li]
                    t = cv.to_game(m3 @ loop.tangent, 1.0)
                    b = cv.to_game(m3 @ loop.bitangent, 1.0)
                    extra = (t, b)
                if lm_uv is not None:
                    extra += ((lm_uv.data[li].uv[0], 1.0 - lm_uv.data[li].uv[1]),)
                corners.append((cv.to_game(co[vi], scale), cv.to_game(n, 1.0), uv, c) + extra)
            du = math.floor(min(c[2][0] for c in corners))
            dv = math.floor(min(c[2][1] for c in corners))
            tri = []
            limit = LM_UV_LIMIT if lm_uv is not None else UV_LIMIT
            for corner in corners:
                pos, n, uv, c = corner[:4]
                u, v = uv[0] - du, uv[1] - dv
                if u > limit or v > limit:
                    stats['clamped_uv'] = stats.get('clamped_uv', 0) + 1
                    u, v = min(u, limit), min(v, limit)
                n = _unit(n)
                extra = tuple(_orthonormal(x, n) for x in corner[4:6])
                if lm_uv is not None:
                    extra += (tuple(min(1.0, max(0.0, x)) for x in corner[6]),)
                key = (tuple(round(x, 4) for x in pos), tuple(round(x, 3) for x in n), (round(u, 5), round(v, 5)), c,
                       tuple(tuple(round(x, 5) for x in e) for e in extra))
                if key not in part['index']:
                    part['index'][key] = len(part['verts'])
                    part['verts'].append((pos, n, (u, v), c) + extra)
                tri.append(part['index'][key])
            if len(set(tri)) == 3:
                part['tris'].append(tuple(tri) if flip else (tri[0], tri[2], tri[1]))   # mirror: see convert.py
        if tangents:
            me.free_tangents()
    finally:
        ev.to_mesh_clear()
    return parts


def _unit(v):
    l = math.sqrt(sum(x * x for x in v)) or 1.0
    return tuple(x / l for x in v)


def _orthonormal(v, n):
    """v made perpendicular to the unit normal n, then unit length."""
    d = sum(a * b for a, b in zip(v, n))
    return _unit(tuple(a - d * b for a, b in zip(v, n)))


def to_meshes(parts, node=0):
    """Parts -> mesh dicts for alr_build (with their material: texture refs and highlight)."""
    out = []
    for part in parts.values():
        if part['tris']:
            out.append(dict(verts=part['verts'], tris=part['tris'], material=part['material'], node=node))
    return out


def resolve(meshes):
    """Kept for callers: texture refs now travel inside each mesh's material and are resolved by the writer."""
    return meshes


def gather(context, vis_colls, scale, textures):
    """Visuals -> ({slot: [mesh dicts]}, stats). Each Blender object stays a separate mesh per texture."""
    slot_of = []

    def walk(c, slot):
        s = _slot_for(c.name, slot)
        slot_of.append((c, s))
        for ch in c.children:
            walk(ch, s)

    for c in vis_colls:
        walk(c, 0)

    depsgraph = context.evaluated_depsgraph_get()
    stats = dict(objects=0, clamped_uv=0)
    replace, seen = {}, set()
    for coll, slot in slot_of:
        for ob in coll.objects:
            if ob.type != 'MESH' or ob.name in seen:
                continue
            seen.add(ob.name)
            stats['objects'] += 1
            parts = mesh_parts(depsgraph, ob, ob.matrix_world, scale, textures, stats)
            replace.setdefault(slot, []).extend(resolve(to_meshes(parts)))
    stats['triangles'] = sum(len(m['tris']) for ms in replace.values() for m in ms)
    return replace, stats
