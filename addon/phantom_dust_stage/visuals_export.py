"""Blender meshes -> model meshes for the .alr writer (stage model and object models).

Meshes under a Visuals collection replace the game original's main stage model. A child collection named
"Background..." or "Sky..." replaces that model instead (the import creates those names).

Materials: a material using the PD Stage Shader (pd_material.py) gives the texture, normal map, reflection map,
highlight colour/shininess, shine mask and baked light; the game shader follows from the maps it uses (sd, sbts,
sdrefs, sbtsrefs). Any other material exports as before: its image, baked light from "PD_Light" (or the active
colour attribute), and no highlight.

Per triangle: position, the corner normal, the active UV map (game V = 1 - Blender V), the vertex colour
(RGB = baked light, A = shine mask) and, for normal-mapped materials, the game's tangent frame for that UV map:
binormal = Blender's bitangent (+V in Blender's UV space), tangent = normal x binormal in game space (the game's
own rule on every map; it stores no handedness, so on mirrored UVs the tangent is -U, as in the game's files).

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


def cube_texture(img):
    """A cube map image (pd_cube_map: six square faces side by side, each face's mip levels stacked under it; an
    image of one row of faces gets its levels made by halving) as a texture dict: each face's levels encoded like any
    texture (DXT1 opaque, DXT5 with alpha; never 1-bit-alpha DXT1, which would lose colours under alpha 0), padded to
    128 bytes, faces one after the other (pdstage/cubemap.py); cube=True sets the descriptor's cube bit."""
    from ._lib import cubemap
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    size = w // 6
    if w % 6 or size < 1 or h < size:
        raise VisualsError('cube map %s is %d x %d: six square faces side by side are needed' % (img.name, w, h))
    if h > size:                                             # the levels are in the image
        faces = cubemap.levels_from_atlas(px, w, h)
    else:
        faces = []
        for f in range(6):
            face = bpy.data.images.new('_pd_face', size, size, alpha=True)
            try:
                face.pixels.foreach_set(px.reshape(h, w, 4)[:, f * size:(f + 1) * size].ravel())
                _fw, _fh, levels = image_levels(face)
            finally:
                bpy.data.images.remove(face)
            faces.append([np.frombuffer(l, np.uint8).reshape(max(1, size >> k), max(1, size >> k), 4)[..., [2, 1, 0, 3]]
                          for k, l in enumerate(levels)])
    data, fmt, mips = bytearray(), None, len(faces[0])
    # one format for the six faces (the descriptor has one): with alpha when any face has it (st07's s7_envmap_h:
    # alpha 0 on part of +Z only; mixed DXT1 / DXT5 faces were read with the wrong block size)
    alpha = any(bool((levels[0][..., 3] < 255).any()) for levels in faces)
    for levels in faces:
        bgra = [l[..., [2, 1, 0, 3]].tobytes() for l in levels]
        c = compress(bgra, size, size, punch_ok=False, alpha=alpha)
        fmt = c.get('format', fmt)
        blob = b''.join(c['levels'])
        data += blob + b'\0' * (-len(blob) % 128)
    return dict(name=game_texture_name(img.name), width=size, height=size, levels=[bytes(data)], mips=mips,
                format=fmt, cube=True)


def _game_storage(img):
    """The game storage format an imported image keeps (pdstage/texlevels.py), or None (a new image, or one
    imported before this was recorded with an unknown format)."""
    from ._lib import texlevels
    s = img.get('pd_texture_storage')
    s = 'b8g8r8a8' if s == 'plain' else s                    # scenes imported before the format names
    return s if s in texlevels.CODE else None


def _level_arrays(levels, w, h):
    out = []
    for lvl in levels:
        out.append(np.frombuffer(lvl, np.uint8).reshape(h, w, 4)[..., [2, 1, 0, 3]])
        w, h = max(1, w // 2), max(1, h // 2)
    return out


def stored_mip_levels(img, w, h, n):
    """Levels 1 .. n-1 (uint8 RGBA, top row first) from the image's lower-levels image (pd_mip_image, made by the
    import from the game's own levels), or None when they are to be made again from level 0. The rule: they are
    the texture's levels while the image is the imported picture: not painted in this session (is_dirty), not
    replaced by a file (no longer packed), the same size; and the lower-levels image has the layout's size. A
    painted or replaced level 0 gets levels made from it (box reduction), as does Regenerate Mip Levels."""
    from ._lib import texlevels
    mi = img.get('pd_mip_image')
    if n < 2 or mi is None or not isinstance(mi, bpy.types.Image) or mi.size[0] == 0:
        return None
    if img.is_dirty or img.packed_file is None or tuple(img.size) != (w, h):
        return None
    px = np.empty(mi.size[0] * mi.size[1] * 4, dtype=np.float32)
    mi.pixels.foreach_get(px)
    return texlevels.levels_from_atlas(px, mi.size[0], mi.size[1], w, h, n)


def regenerate_mip_image(img):
    """Make the image's lower-levels image (pd_mip_image) again from its level 0 (box reduction). Returns True when
    there was one to make."""
    from ._lib import texlevels
    mi = img.get('pd_mip_image')
    n = int(img.get('pd_mip_levels', 0) or 0)
    if mi is None or not isinstance(mi, bpy.types.Image) or n < 2 or img.size[0] == 0:
        return False
    w, h, levels = image_levels(img)
    arrs = _level_arrays(levels[:n], w, h)
    if len(arrs) < 2:
        return False
    aw, ah, px = texlevels.mip_atlas(arrs[1:])
    if tuple(mi.size) != (aw, ah):
        mi.scale(aw, ah)
    mi.pixels.foreach_set(px.ravel())
    mi.update()
    if mi.packed_file is not None:
        mi.pack()
    return True


def game_texture(img):
    """An imported game texture (pd_texture_storage) written in the game's own format: B8G8R8A8 and the 16-bit
    formats stay uncompressed (linear rows, or swizzled when imported from the original Xbox release), DXT1 / DXT3 /
    DXT5 stay so; every mip level the game has, the lower ones from the lower-levels image (stored_mip_levels)."""
    from ._lib import texlevels
    storage = _game_storage(img)
    w, h, levels = image_levels(img)
    keep = int(img.get('pd_mip_levels', 0) or 0)
    arrs = _level_arrays(levels[:max(1, keep)] if keep else levels, w, h)
    stored = stored_mip_levels(img, w, h, len(arrs))
    if stored is not None:
        arrs = arrs[:1] + stored
    swz = bool(img.get('pd_texture_swizzled')) and storage in texlevels.BPP
    # DXT1 with 1-bit alpha (the game's cut-outs) when level 0 has a transparent texel; every level the same way
    punch = storage == 'dxt1' and bool((arrs[0][..., 3] < 128).any())
    data = [texlevels.encode_level(a, storage, swz, punch) for a in arrs]
    return dict(name=game_texture_name(img.name), width=w, height=h, levels=data, mips=len(data),
                format=texlevels.raw_format_byte(storage, swz), mips_kept=stored is not None)


def compress(levels, w, h, keep_alpha=False, punch_ok=True, alpha=None):
    """BGRA mip levels -> dict(levels, format) compressed like the game's own textures (DXT1 when opaque,
    DXT5 with alpha): a quarter to an eighth of the size. Falls back to plain BGRA if numpy can't do it.
    keep_alpha: DXT5 whatever the alpha (a game texture stored DXT3/DXT5)."""
    from ._lib import dxt
    try:
        arrs, lw, lh = [], w, h
        for lvl in levels:
            a = np.frombuffer(lvl, dtype=np.uint8).reshape(lh, lw, 4)[..., [2, 1, 0, 3]]
            arrs.append(a)
            lw, lh = max(1, lw // 2), max(1, lh // 2)
        alpha = (dxt.needs_alpha(arrs[0]) if alpha is None else alpha) or keep_alpha
        # 1-bit alpha (the game's DXT1 cut-outs): DXT1 again. Not when nothing is opaque: DXT1 stores a transparent
        # texel as black, so a texture whose alpha is 0 everywhere (st16's normal maps, DXT5 with alpha 0: a
        # mask) came out black and darkened the whole map; not for a game DXT3/DXT5 texture (keep_alpha) and not
        # for a cube map (punch_ok False: its colours under alpha 0 are kept, as DXT5)
        punch = punch_ok and not keep_alpha and dxt.binary_alpha(arrs[0]) and bool((arrs[0][..., 3] > 127).any())
        alpha = alpha and not punch
        out = [dxt.encode(a, alpha, punch) for a in arrs]
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
        self.replaced = {}                             # built from the scene: {texture number: texture} (rebuild)

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
                and game_texture_name(img.name) in self.base_by_name and _reuse_by_name():
            # fallback only ("Preserve unedited parts"): an image named like one of the replaced map's textures
            # uses that texture's bytes. Built from the scene, every texture is encoded from its Blender image
            ref = ('base', self.base_by_name[game_texture_name(img.name)])
            self.reused += 1
        elif alpha_scale == 1.0 and normal_strength == 1.0 and tint == (1.0, 1.0, 1.0) and alpha_value is None \
                and game_texture_name(img.name) in self.base_by_name:
            # built from the scene: an image named like one of the replaced map's textures is encoded from its pixels
            # into that texture's own number (the map's effects use texture numbers), so each texture is in the file
            # once
            i = self.base_by_name[game_texture_name(img.name)]
            if img.get('pd_cube_map'):
                self.replaced[i] = cube_texture(img)
            elif _game_storage(img):
                self.replaced[i] = game_texture(img)
            else:
                w, h, levels = image_levels(img, alpha_scale, normal_strength, tint=tint, alpha_value=alpha_value)
                keep = int(img.get('pd_mip_levels', 0) or 0)      # the game's own level count (imported images)
                if keep:
                    levels = levels[:max(1, keep)]
                if img.get('pd_texture_storage') == 'plain' and len(levels) == 1:
                    # a plain-colour texture with one level stays plain (the game's own: glows, sea, sky pictures);
                    # block compression would change its gradients, extra levels its look at a distance
                    entry = dict(levels=levels, mips=1)
                else:
                    entry = compress(levels, w, h, keep_alpha=img.get('pd_texture_storage') == 'dxt5')                         if self.compress else dict(levels=levels)
                    entry['mips'] = len(entry['levels'])
                self.replaced[i] = dict(name=game_texture_name(img.name), width=w, height=h, **entry)
            ref = ('base', i)
        elif img.get('pd_cube_map'):
            ref = ('new', len(self.new))
            self.new.append(cube_texture(img))
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
            nalpha = None if settings.get('scroll_keep_normal_alpha') else self.SCROLL_NORMAL_ALPHA
            na = self.ref(settings['normal'], normal_strength=strength, alpha_value=nalpha) \
                if settings['normal'] is not None else self.scroll_flat_normal()
            nb_img = settings.get('normal_b') or settings['normal']
            nb = self.ref(nb_img, normal_strength=strength, alpha_value=nalpha) \
                if nb_img is not None else self.scroll_flat_normal()
            return dict(diffuse=self.ref(settings['diffuse'], fade, tint=tint), transparent=False, normal=na,
                        reflection=None, specular=(0, 0, 0, 0),
                        scroll=dict(normal_a=na, normal_b=nb, speeds=tuple(settings['scroll_speeds']), blend=blend,
                                    specular=tuple(settings['specular']) if nalpha is None else None))
        see = bool(settings.get('transparent'))      # blended shader (..al): the slider fades the texture's alpha
        return dict(diffuse=self.ref(settings['diffuse'], 1.0 - settings.get('transparency', 0.0) if see else 1.0,
                                     tint=tint),
                    transparent=see,
                    normal=self.ref(settings['normal'], normal_strength=settings.get('normal_strength', 1.0))
                    if settings['normal'] is not None else None,
                    reflection=self.ref(settings['reflection'], settings['reflection_strength'])
                    if settings['reflection'] is not None else None,
                    specular=tuple(settings['specular']))


def game_settings(mat, any_shader=False):
    """A material's game shader and settings (set by the import from the game's material), or None.
    any_shader: also shaders the generic writer has no vertex format for (lbts: written by the light-map path)."""
    if mat is None or 'pd_game_shader' not in mat or (
            not any_shader and mat.get('pd_game_shader') not in alr_build.SHADER_FORMAT):
        return None
    params = [int(x) for x in mat.get('pd_shader_params', ())][:8]
    return dict(shader=str(mat['pd_game_shader']), flags=int(mat.get('pd_material_flags', 0)),
                filter=int(mat.get('pd_material_filter', 0x10)), blend=int(mat.get('pd_material_blend', 0)),
                roles=int(mat.get('pd_texture_roles', 1)), colour=_argb(mat.get('pd_material_colour'), 0xFF000000),
                word_38=_argb(mat.get('pd_material_word_38'), 0), params=tuple(params + [0] * (8 - len(params))))


def _argb(v, default):
    try:
        a, r, g, b = (int(x) & 0xFF for x in v)
    except (TypeError, ValueError):
        return default
    return a << 24 | r << 16 | g << 8 | b


def _reuse_by_name():
    from . import roundtrip
    return roundtrip.ENABLED


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
        game_lm = False
        if lm_ref is None and uvl is not None and me.uv_layers.get('PD_LightUV') is not None and any(
                s.material is not None and str(s.material.get('pd_game_shader', '')).startswith('lbts')
                for s in ob.material_slots):
            # the game's own light-mapped surfaces (lbts: the town's floors): their light map image and second UV
            # map, as imported, written back as lbts (they were written as sbts without the light map: darker)
            lm_uv = me.uv_layers['PD_LightUV']
            game_lm = True
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
                game = game_settings(mat) if lm_ref is None and not game_lm and not gmat.get('scroll') else None
                if game_lm and mat is not None and str(mat.get('pd_game_shader', '')).startswith('lbts'):
                    # the game's settings (roles 0x0261 or 0x0255, flags, blend ...) and every slot by its role:
                    # diffuse (1), normal (2), reflection (4: lbtsrefs, the map's cube map), the light map (5/6) and
                    # any other slot from its own image
                    g = game_settings(mat, any_shader=True)
                    imgs = {1: st['diffuse'], 2: st['normal'], 4: st['reflection']}
                    refs, lm = [], None
                    for k in range(4):
                        role = (g['roles'] >> (4 * k)) & 0xF
                        if ('pd_texture_%d_cube' % k) in mat:
                            refs.append(('base', int(mat['pd_texture_%d_cube' % k])))
                            continue
                        img = imgs.get(role) if imgs.get(role) is not None else mat.get('pd_texture_%d' % k)
                        refs.append(textures.ref(img) if img is not None and hasattr(img, 'pixels') else
                                    (textures.flat_normal() if role == 2 else None))
                        if role in (5, 6) and k > 0 and lm is None:
                            lm = refs[-1]
                    gmat = dict(diffuse=refs[0], lightmap=lm or refs[1], normal=st['normal'] and refs[2] or
                                textures.flat_normal(), reflection=None, specular=gmat['specular'], game=g,
                                textures=tuple(refs))
                    st = dict(st, normal=st['normal'] or 'flat', light=('const', (255, 255, 255)))
                elif game is not None:
                    # the material keeps the game's shader and settings (pd_game_shader ...): every texture slot
                    # from the material's maps (by the slot's role) or its own slot image
                    imgs = {1: st['diffuse'], 2: st['normal'], 4: st['reflection']}
                    refs = []
                    for k in range(4):
                        role = (game['roles'] >> (4 * k)) & 0xF
                        img = imgs.get(role) if role in imgs and imgs.get(role) is not None else \
                            (mat.get('pd_texture_%d' % k) if mat is not None else None)
                        if mat is not None and ('pd_texture_%d_cube' % k) in mat:
                            refs.append(('base', int(mat['pd_texture_%d_cube' % k])))     # the map's cube map
                            continue
                        refs.append(textures.ref(img) if img is not None and hasattr(img, 'pixels') else None)
                    gmat = dict(game=game, textures=tuple(refs), specular=gmat['specular'])
                    needs_tangents = alr_build.VERTEX_MASK[alr_build.SHADER_FORMAT[game['shader']]] & 0x1000
                    st = dict(st, normal=(st['normal'] or 'flat') if needs_tangents else None)
                elif gmat.get('scroll'):                  # scrolling: tangents always; white light, alpha 255
                    # unless the material reads the mesh's colours (the game's sky clouds: the vertex colour's alpha
                    # fades the clouds out toward the horizon, its RGB tints them)
                    attr = lambda s: s is not None and s[0] == 'attr'
                    st = dict(st, normal=st['normal'] or 'flat',
                              light=st['light'] if attr(st['light']) else ('const', (255, 255, 255)),
                              shine=st['shine'] if attr(st['shine']) else ('const', 1.0))
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
            if lm_uv is None and all(-8.0 <= c[2][k] <= UV_LIMIT for c in corners for k in (0, 1)):
                du = dv = 0                   # within what the vertex holds (s16 / 4096): as they are, so a vertex
                # shared by several triangles stays one vertex
            tri = []
            limit = LM_UV_LIMIT if lm_uv is not None else UV_LIMIT
            for corner in corners:
                pos, n, uv, c = corner[:4]
                u, v = uv[0] - du, uv[1] - dv
                if u > limit or v > limit:
                    stats['clamped_uv'] = stats.get('clamped_uv', 0) + 1
                    u, v = min(u, limit), min(v, limit)
                n = _unit(n)
                extra = ()
                if len(corner) > 4:
                    # the game's tangent frame: the binormal along the UV map's V (Blender's bitangent), the
                    # tangent always normal x binormal in game space. The game stores no handedness: its sbts-family
                    # vertex shaders take the light and half vectors into the frame as (-L.T, -L.B, L.N), and every
                    # tangent-framed vertex of the game's maps (Xbox and 2017 PC, st01-st09) has T = N x B, also
                    # where the UVs are mirrored (there T = -dP/du). Blender's own tangent (+U) points the other way
                    # on mirrored faces: the bump and highlight flipped there, hard seams on the pillars.
                    b = _orthonormal(corner[5], n)
                    extra = (_cross(n, b), b)
                if lm_uv is not None:
                    extra += (tuple(min(1.0, max(0.0, x)) for x in corner[6]),)
                # the values as the vertex stores them (packed normals and tangents, UVs in 1/4096): corners that
                # write the same bytes are one vertex
                # write the same bytes are one vertex. The tangent frame is one per vertex, as in the game's files:
                # the corners' binormals are summed and the frame made from the sum below (Blender's per-corner
                # tangents differ slightly and split every vertex: st04's pillar 233 vertices -> 1014)
                key = (tuple(round(x, 4) for x in pos), alr_build.pack_normal(n),
                       (round(u * 4096), round(v * 4096)), c, len(extra) >= 2,
                       tuple(tuple(round(x, 5) for x in e) for e in extra[2:]))
                if key not in part['index']:
                    part['index'][key] = len(part['verts'])
                    part['verts'].append((pos, n, (u, v), c) + extra)
                    part.setdefault('bsum', []).append([0.0, 0.0, 0.0])
                k = part['index'][key]
                if len(extra) >= 2:
                    bs = part['bsum'][k]
                    for j in range(3):
                        bs[j] += extra[1][j]
                tri.append(k)
            if len(set(tri)) == 3:
                part['tris'].append(tuple(tri) if flip else (tri[0], tri[2], tri[1]))   # mirror: see convert.py
        if tangents:
            me.free_tangents()
        for part in parts.values():                       # one tangent frame per vertex, from the summed binormals
            for k, vert in enumerate(part['verts']):
                if len(vert) >= 6 and any(part['bsum'][k]):
                    bn = _orthonormal(part['bsum'][k], vert[1])
                    part['verts'][k] = vert[:4] + (_cross(vert[1], bn), bn) + vert[6:]
    finally:
        ev.to_mesh_clear()
    return parts


def _unit(v):
    l = math.sqrt(sum(x * x for x in v)) or 1.0
    return tuple(x / l for x in v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


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
    from . import townlights
    town = townlights.town_lights(context.scene)   # the town: each draw names the lights linked to its object
    joints = {}                                     # slot -> joint empties in skeleton order
    for coll, slot in slot_of:
        for ob in coll.objects:
            if ob.type == 'EMPTY' and ob.get('pd_joint'):
                joints.setdefault(slot, []).append(ob)
    skel = {s: skeleton(js, scale) for s, js in joints.items()}
    for coll, slot in slot_of:
        for ob in coll.objects:
            if ob.type != 'MESH' or ob.name in seen:
                continue
            seen.add(ob.name)
            stats['objects'] += 1
            sk = skel.get(slot)
            node = 0
            matrix = ob.matrix_world
            if sk is not None:
                # on its joint: the vertices in the joint's space (the game poses them with the joint's matrix)
                node = sk['index'].get(ob.parent.name, sk['world']) if ob.parent is not None else sk['world']
                if node != sk['world']:
                    matrix = ob.parent.matrix_world.inverted() @ ob.matrix_world
                sk['used'].add(node)
            parts = mesh_parts(depsgraph, ob, matrix, scale, textures, stats)
            meshes = resolve(to_meshes(parts, node))
            lights = townlights.draw_lights(ob, town) if town else None
            for m in meshes:
                m['object'] = ob.name                    # which object made it (export keeps unedited game meshes)
                if lights is not None:
                    m['lights'] = lights
            replace.setdefault(slot, []).extend(meshes)
    stats['triangles'] = sum(len(m['tris']) for ms in replace.values() for m in ms)
    for slot, sk in skel.items():
        if slot in replace:
            for k in sk['used']:                     # computed flag: the joint has draws
                sk['nodes'][k]['flags'] |= 0x0004
            replace[slot] = dict(meshes=replace[slot], nodes=sk['nodes'])
            stats['joints'] = stats.get('joints', 0) + len(sk['nodes'])
    return replace, stats


def skeleton(empties, scale):
    """Joint empties -> dict(nodes=[node_record kwargs], index={empty name: joint index}, world=joint index of an
    identity root for meshes not on a joint, used=set()). Order: parents before children, roots and siblings by
    name. Flags: the empty's game settings (pd_joint_lookup, pd_faces_camera, pd_hidden) and the computed bits
    (translation / rotation / scale not identity; 'has draws' is added by gather)."""
    from . import visuals
    names = {o.name for o in empties}
    kids = {}
    for o in empties:
        p = o.parent.name if o.parent is not None and o.parent.name in names else None
        kids.setdefault(p, []).append(o)
    order = []

    def walk(p):
        for o in sorted(kids.get(p, []), key=lambda o: cv.natural_key(o.name)):
            order.append(o)
            walk(o.name)
    walk(None)
    index = {o.name: k for k, o in enumerate(order)}
    nodes = []
    for o in order:
        par = index.get(o.parent.name) if o.parent is not None and o.parent.name in names else None
        local = o.matrix_basis if par is not None else o.matrix_world
        loc, rot, scl = local.decompose()
        t = cv.to_game(loc, scale)
        r = cv.rot_to_game([list(row) for row in rot.to_matrix()])
        s = (scl[0], scl[2], scl[1])
        flags = 0
        if any(abs(x) > 1e-6 for x in t):
            flags |= 0x0010
        if any(abs(x) > 1e-7 for x in r):
            flags |= 0x0020
        if any(abs(x - 1.0) > 1e-6 for x in s):
            flags |= 0x0040
        for bit, prop in visuals.JOINT_PROPS:
            if o.get(prop):
                flags |= bit
        name = o.get('pd_joint_name') or ''
        nodes.append(dict(t=t, rot=r, scale=s, flags=flags, parent=par,
                          marker=alr_build.encode_word(name) if name else 0xFFFFFFFF))
    world = 0
    if not nodes or nodes[0]['parent'] is not None or nodes[0]['t'] != (0.0, 0.0, 0.0) or nodes[0]['flags'] & 0x70 \
            or index.get(order[0].name) != 0:
        world = 0
        # an identity root first, for meshes on no joint (and the shadow volumes the writer adds on joint 0)
        nodes = [dict(t=(0.0, 0.0, 0.0), rot=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0), flags=0, parent=None,
                      marker=0xFFFFFFFF)] + [dict(n, parent=None if n['parent'] is None else n['parent'] + 1)
                                             for n in nodes]
        index = {k: v + 1 for k, v in index.items()}
    return dict(nodes=nodes, index=index, world=world, used=set())
