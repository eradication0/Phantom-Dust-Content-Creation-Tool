"""Cube map textures: the six faces and every mip level, decoded (numpy), and the layout of their Blender image.

Layout in the file (every cube map of the game: 64 x 64 DXT1 7 mips, st07's B8G8R8A8 ones): the faces +X -X +Y -Y
+Z -Z one after the other, each its whole mip chain, padded to 128 bytes.

The game's own mip levels are not a plain reduction of the top level (envmap: mip 2 is on average 8 to 55 levels
away from a box reduction of mip 0 on st02; st07's B8G8R8A8 ones are close to it), so the Blender image holds every
level: the six faces side by side, each face's levels stacked under it (level 0 at the top, then 1, 2, ...; the
rest of the face's column is unused).
"""
import numpy as np

from . import texlevels


def decode(b, t, resource_offset):
    """[[level arrays] per face] of a cube texture dict (alr.textures)."""
    storage, swizzled = texlevels.storage_of(t['raw_format'])
    dims = texlevels.level_dims(t['width'], t['height'], t['mips'])
    stride = (sum(texlevels.level_bytes(storage, w, h) for w, h in dims) + 127) & ~127
    faces = []
    for f in range(6):
        p, levels = resource_offset + t['offset'] + f * stride, []
        for w, h in dims:
            sz = texlevels.level_bytes(storage, w, h)
            levels.append(texlevels.decode_level(b[p:p + sz], storage, w, h, swizzled))
            p += sz
        faces.append(levels)
    return faces


def atlas(faces):
    """The Blender image's pixels (float RGBA, rows bottom first) for faces' levels; (width, height, pixels): each
    face a column laid out as texlevels.mip_atlas, level 0 included."""
    cols = [texlevels.mip_atlas(levels) for levels in faces]
    return 6 * cols[0][0], cols[0][1], np.concatenate([px for _w, _h, px in cols], axis=1)


def levels_from_atlas(px, width, height):
    """[[level arrays (uint8 RGBA, top row first)] per face] from an atlas image's pixels (rows bottom first)."""
    img = np.clip(np.round(px.reshape(height, width, 4)[::-1] * 255), 0, 255).astype(np.uint8)
    w = width // 6
    faces = []
    for f in range(6):
        y, lw, levels = 0, w, []
        while y < height and lw >= 1:
            levels.append(img[y:y + lw, f * w:f * w + lw].copy())
            y += lw
            if lw == 1:
                break
            lw //= 2
        faces.append(levels)
    return faces
