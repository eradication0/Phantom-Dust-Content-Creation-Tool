"""Every mip level of a stage texture: decode, encode in the game's own format, and the Blender layout of the lower
levels.

The game's lower mip levels are pictures of their own, not a box reduction of the top level (survey of the 2017 PC
files and the Xbox files: see ROUNDTRIP_FIXES.md, "Mip levels"); at a distance the game samples them, so an export
that makes them again from level 0 changes how a surface looks from afar (st08's tower ring platform). The import
keeps them as a Blender image of their own (`mip_atlas`): level 1 at the top, level 2 under it, ..., each level
left-aligned; the export writes them from it.

Storage formats (descriptor byte +0x0D; 0x80 = linear rows, the 2017 release's uncompressed textures; without it the
Xbox's swizzled rows):

    name        code   bytes per texel / block
    dxt1        0x0C   8 per 4 x 4 block (1-bit alpha possible)
    dxt3        0x0E   16 per block (4-bit explicit alpha)
    dxt5        0x0F   16 per block (interpolated alpha)
    b8g8r8a8    0x06   4 (also 0x12 / 0x28: other names of the same layout)
    b5g6r5      0x05   2
    b4g4r4a4    0x04   2
    b5g5r5a1    0x02   2
"""
import numpy as np

from . import dxt
from .alr import _morton

STORAGE = {0x0C: 'dxt1', 0x0E: 'dxt3', 0x0F: 'dxt5', 0x06: 'b8g8r8a8', 0x12: 'b8g8r8a8', 0x28: 'b8g8r8a8',
           0x05: 'b5g6r5', 0x04: 'b4g4r4a4', 0x02: 'b5g5r5a1'}
CODE = {'dxt1': 0x0C, 'dxt3': 0x0E, 'dxt5': 0x0F, 'b8g8r8a8': 0x06, 'b5g6r5': 0x05, 'b4g4r4a4': 0x04,
        'b5g5r5a1': 0x02}
BLOCK = {'dxt1': 8, 'dxt3': 16, 'dxt5': 16}
BPP = {'b8g8r8a8': 4, 'b5g6r5': 2, 'b4g4r4a4': 2, 'b5g5r5a1': 2}


def storage_of(raw_format):
    """(storage name or None, swizzled) of a descriptor's format byte."""
    f = raw_format & 0x7F if raw_format & 0x80 else raw_format
    name = STORAGE.get(f)
    return name, bool(name in BPP and not raw_format & 0x80)


def level_dims(w, h, mips):
    out = []
    for _ in range(max(1, mips)):
        out.append((w, h))
        w, h = max(1, w // 2), max(1, h // 2)
    return out


def level_bytes(storage, w, h):
    if storage in BLOCK:
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * BLOCK[storage]
    return w * h * BPP[storage]


# ---------------------------------------------------------------- decoding (numpy; tools and the survey)

def _dxt_colour(blk, four):
    c0 = blk[:, 0].astype(np.uint32) | (blk[:, 1].astype(np.uint32) << 8)
    c1 = blk[:, 2].astype(np.uint32) | (blk[:, 3].astype(np.uint32) << 8)
    bits = blk[:, 4:8].copy().view('<u4')[:, 0]
    e0, e1 = dxt._from565(c0), dxt._from565(c1)
    four = np.ones(len(blk), bool) if four else c0 > c1
    p2 = np.where(four[:, None], (2 * e0 + e1) / 3, (e0 + e1) / 2)
    p3 = np.where(four[:, None], (e0 + 2 * e1) / 3, 0.0)
    pal = np.stack([e0, e1, p2, p3], 1)                                  # (n, 4, 3)
    idx = (bits[:, None] >> (2 * np.arange(16, dtype=np.uint32))) & 3
    rgb = np.take_along_axis(pal, idx[..., None].astype(np.int64).repeat(3, -1), 1)
    a = np.where((~four)[:, None] & (idx == 3), 0.0, 255.0)
    return np.concatenate([rgb, a[..., None]], -1)                       # (n, 16, 4)


def _decode_blocks(data, storage, w, h):
    nbx, nby = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    blk = np.frombuffer(bytes(data), np.uint8)[:nbx * nby * BLOCK[storage]].reshape(-1, BLOCK[storage])
    if storage == 'dxt1':
        px = _dxt_colour(blk, False)
    else:
        px = _dxt_colour(blk[:, 8:], True)
        if storage == 'dxt3':
            nib = blk[:, :8].copy().view('<u8')[:, 0]
            px[..., 3] = ((nib[:, None] >> (4 * np.arange(16, dtype=np.uint64))) & np.uint64(15)).astype(np.float32) * 17
        else:
            a0, a1 = blk[:, 0].astype(np.float32), blk[:, 1].astype(np.float32)
            bits = np.zeros(len(blk), np.uint64)
            for j in range(6):
                bits |= blk[:, 2 + j].astype(np.uint64) << np.uint64(8 * j)
            k = np.arange(2, 8, dtype=np.float32)[None, :]
            eight = (a0 > a1)[:, None]
            pal8 = ((8 - k) * a0[:, None] + (k - 1) * a1[:, None]) / 7
            k6 = np.arange(2, 6, dtype=np.float32)[None, :]
            pal6 = np.concatenate([((6 - k6) * a0[:, None] + (k6 - 1) * a1[:, None]) / 5,
                                   np.zeros((len(blk), 1), np.float32), np.full((len(blk), 1), 255, np.float32)], 1)
            pal = np.concatenate([a0[:, None], a1[:, None], np.where(eight, pal8, pal6)], 1)
            idx = ((bits[:, None] >> (3 * np.arange(16, dtype=np.uint64))) & np.uint64(7)).astype(np.int64)
            px[..., 3] = np.take_along_axis(pal, idx, 1)
    img = px.reshape(nby, nbx, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(nby * 4, nbx * 4, 4)[:h, :w]
    return np.clip(np.round(img), 0, 255).astype(np.uint8)


def decode_level(data, storage, w, h, swizzled=False):
    """One level as (h, w, 4) uint8 RGBA, top row first."""
    if storage in BLOCK:
        return _decode_blocks(data, storage, w, h)
    n = w * h
    if storage == 'b8g8r8a8':
        px = np.frombuffer(bytes(data[:4 * n]), np.uint8).reshape(n, 4)[:, [2, 1, 0, 3]]
    else:
        v = np.frombuffer(bytes(data[:2 * n]), '<u2').astype(np.uint32)
        if storage == 'b5g6r5':
            r, g, b, a = (v >> 11) & 31, (v >> 5) & 63, v & 31, np.full(n, 255, np.uint32)
            r, g, b = (r * 255 + 15) // 31, (g * 255 + 31) // 63, (b * 255 + 15) // 31
        elif storage == 'b5g5r5a1':
            r, g, b, a = (v >> 10) & 31, (v >> 5) & 31, v & 31, ((v >> 15) & 1) * 255
            r, g, b = (r * 255 + 15) // 31, (g * 255 + 15) // 31, (b * 255 + 15) // 31
        else:
            a, r, g, b = ((v >> 12) & 15) * 17, ((v >> 8) & 15) * 17, ((v >> 4) & 15) * 17, (v & 15) * 17
        px = np.stack([r, g, b, a], 1).astype(np.uint8)
    if swizzled:
        px = px[_morton(w, h).ravel()]
    return px.reshape(h, w, 4).copy()


def decode_texture(b, t, resource_offset):
    """[level arrays] of a plain (not cube) texture dict (alr.textures), or None for formats not handled."""
    storage, swz = storage_of(t['raw_format'])
    if storage is None or t.get('cubemap'):
        return None
    p, out = resource_offset + t['offset'], []
    for w, h in level_dims(t['width'], t['height'], t['mips']):
        n = level_bytes(storage, w, h)
        out.append(decode_level(b[p:p + n], storage, w, h, swz and not t.get('npot')))
        p += n
    return out


# ---------------------------------------------------------------- encoding

def encode_level(rgba, storage, swizzled=False, punch=None):
    """(h, w, 4) uint8 RGBA, top row first -> bytes in `storage`. punch (dxt1): 1-bit alpha (None: when the level
    has a transparent texel)."""
    h, w = rgba.shape[:2]
    if storage == 'dxt1':
        if punch is None:
            punch = bool((rgba[..., 3] < 128).any())
        return dxt.encode(rgba, alpha=False, punch=punch)[1]
    if storage == 'dxt5':
        return dxt.encode(rgba, alpha=True)[1]
    if storage == 'dxt3':
        b = dxt._blocks(rgba)
        colour = dxt._colour_blocks(b[:, :, :3])
        nib = np.clip(np.round(b[:, :, 3] / 17), 0, 15).astype(np.uint64)
        bits = (nib << (4 * np.arange(16, dtype=np.uint64))).sum(1).astype(np.uint64)
        alpha = bits.astype('<u8').view(np.uint8).reshape(-1, 8)
        return np.concatenate([alpha, colour], 1).tobytes()
    px = rgba.reshape(-1, 4).astype(np.uint32)
    r, g, b, a = px[:, 0], px[:, 1], px[:, 2], px[:, 3]
    if storage == 'b8g8r8a8':
        out = rgba.reshape(-1, 4)[:, [2, 1, 0, 3]]
    elif storage == 'b5g6r5':
        out = (((r * 31 + 127) // 255) << 11) | (((g * 63 + 127) // 255) << 5) | ((b * 31 + 127) // 255)
    elif storage == 'b5g5r5a1':
        out = ((a >= 128).astype(np.uint32) << 15) | (((r * 31 + 127) // 255) << 10) \
            | (((g * 31 + 127) // 255) << 5) | ((b * 31 + 127) // 255)
    else:
        q = lambda c: (c * 15 + 127) // 255
        out = (q(a) << 12) | (q(r) << 8) | (q(g) << 4) | q(b)
    if storage != 'b8g8r8a8':
        out = out.astype('<u2')
    if swizzled:
        sw = np.empty_like(out)
        sw[_morton(w, h).ravel()] = out
        out = sw
    return out.tobytes()


def raw_format_byte(storage, swizzled=False):
    """The descriptor's format byte: uncompressed formats get 0x80 (linear) unless written swizzled (Xbox)."""
    c = CODE[storage]
    return c if storage in BLOCK or swizzled else c | 0x80


# ---------------------------------------------------------------- the Blender image of the lower levels

def atlas_size(w, h, mips):
    """(width, height) of the image holding levels 1 .. mips-1 of a w x h texture (None with one level)."""
    dims = level_dims(w, h, mips)[1:]
    if not dims:
        return None
    return dims[0][0], sum(d[1] for d in dims)


def mip_atlas(levels):
    """Levels 1 .. n-1 (uint8 RGBA, top row first) -> (width, height, float RGBA pixels, rows bottom first):
    level 1 at the top, each next level under it, left-aligned (the rest of a row is transparent black)."""
    w, h = levels[0].shape[1], sum(l.shape[0] for l in levels)
    img = np.zeros((h, w, 4), np.float32)
    y = 0
    for l in levels:
        img[y:y + l.shape[0], :l.shape[1]] = l / 255.0
        y += l.shape[0]
    return w, h, img[::-1].copy()


def levels_from_atlas(px, width, height, w0, h0, mips):
    """Levels 1 .. mips-1 (uint8 RGBA, top row first) from the lower-levels image's pixels (float, rows bottom
    first) for a w0 x h0 texture; None when the image does not have that layout's size."""
    if atlas_size(w0, h0, mips) != (width, height):
        return None
    img = np.clip(np.round(np.asarray(px, np.float32).reshape(height, width, 4)[::-1] * 255), 0, 255).astype(np.uint8)
    out, y = [], 0
    for w, h in level_dims(w0, h0, mips)[1:]:
        out.append(img[y:y + h, :w].copy())
        y += h
    return out
