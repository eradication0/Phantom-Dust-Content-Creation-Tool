"""Block compression (DXT1 / DXT5, the formats the game's own textures use) in numpy.

New textures used to be written as plain BGRA: four to eight times the size of the game's own. A map whose
textures all come from another map (a game original imported and exported over a different slot) then made a
67 MB model file, which the game does not load. Compressed, the same textures take the game's usual space.

encode(rgba) takes an (h, w, 4) uint8 array, top row first, and returns (format byte, bytes):
0x0C (DXT1) when the texture is opaque, 0x0F (DXT5) when it uses alpha.
"""
import numpy as np

BC1, BC3 = 0x0C, 0x0F


def _blocks(rgba):
    """(h, w, 4) -> (number of blocks, 16, 4) float, padded to whole 4 x 4 blocks by repeating the edge."""
    h, w = rgba.shape[:2]
    H, W = max(4, (h + 3) // 4 * 4), max(4, (w + 3) // 4 * 4)
    if (H, W) != (h, w):
        rgba = np.pad(rgba, ((0, H - h), (0, W - w), (0, 0)), mode='edge')
    b = rgba.reshape(H // 4, 4, W // 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 4)
    return b.astype(np.float32)


def _to565(c):
    c = np.clip(np.round(c), 0, 255).astype(np.uint32)
    return ((c[..., 0] >> 3) << 11) | ((c[..., 1] >> 2) << 5) | (c[..., 2] >> 3)


def _from565(v):
    r = (v >> 11) & 31
    g = (v >> 5) & 63
    b = v & 31
    return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], -1).astype(np.float32)


def _fit(px, hi, lo, three=False):
    """End colours (float) -> (c0, c1 as 565, palette index per texel, squared error per block).
    three: DXT1's 3-colour mode (c0 <= c1: colour 0, colour 1, their midpoint; index 3 is transparent black and is
    not used here, the block stays opaque)."""
    c0, c1 = _to565(hi), _to565(lo)
    swap = c0 > c1 if three else c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    e0, e1 = _from565(c0), _from565(c1)
    if three:
        pal = np.stack([e0, e1, (e0 + e1) / 2], 1)                             # (n, 3, 3)
    else:
        pal = np.stack([e0, e1, (2 * e0 + e1) / 3, (e0 + 2 * e1) / 3], 1)      # (n, 4, 3)
    dist = ((px[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1)             # (n, 16, 3 or 4)
    idx = dist.argmin(-1).astype(np.uint32)
    if not three:
        idx[c0 == c1] = 0
    err = np.take_along_axis(dist, idx[..., None].astype(np.int64), -1)[..., 0].sum(1)
    return c0, c1, idx, err


def _refine(px, idx, weights):
    """Least-squares end colours for the chosen palette positions (weights: colour 0's share per index):
    (hi, lo, ok) with ok False where the system is singular."""
    w = np.asarray(weights, np.float32)[idx]
    a, b = w, 1.0 - w
    aa, bb, ab = (a * a).sum(1), (b * b).sum(1), (a * b).sum(1)
    ap, bp = np.einsum('nk,nki->ni', a, px), np.einsum('nk,nki->ni', b, px)
    det = aa * bb - ab * ab
    ok = np.abs(det) > 1e-6
    det = np.where(ok, det, 1.0)[:, None]
    return (bb[:, None] * ap - ab[:, None] * bp) / det, (aa[:, None] * bp - ab[:, None] * ap) / det, ok


def _colour_blocks(px, three=False):
    """px: (n, 16, 3) float -> (n, 8) uint8 colour blocks in the 4-colour mode (DXT3 / DXT5 colour halves always
    decode so). three (DXT1 only): a block also tries the 3-colour mode (colour 0, colour 1 and their midpoint) and
    keeps it where its error is lower: the game's own DXT1 files use it for opaque blocks of three colours on a line
    with one in the middle (st12 / st22 b_tu_c_14s_0, level 7: three exact colours the 4-colour mode cannot hit)."""
    n = len(px)
    mean = px.mean(1, keepdims=True)
    d = px - mean
    cov = np.einsum('nki,nkj->nij', d, d)
    axis = np.ones((n, 3), np.float32)
    for _ in range(6):                                     # power iteration: the main colour direction
        axis = np.einsum('nij,nj->ni', cov, axis)
        axis /= np.maximum(np.linalg.norm(axis, axis=1, keepdims=True), 1e-6)
    t = np.einsum('nki,ni->nk', d, axis)
    lo = mean[:, 0] + axis * t.min(1, keepdims=True)
    hi = mean[:, 0] + axis * t.max(1, keepdims=True)
    best = None
    for mode, weights in ((False, (1.0, 0.0, 2.0 / 3.0, 1.0 / 3.0)), (True, (1.0, 0.0, 0.5)))[:2 if three else 1]:
        c0, c1, idx, err = _fit(px, hi, lo, mode)
        # refine the end colours once by least squares on the chosen palette positions, keep it where it helps
        hi2, lo2, ok = _refine(px, idx, weights)
        r0, r1, ridx, rerr = _fit(px, np.where(ok[:, None], hi2, hi), np.where(ok[:, None], lo2, lo), mode)
        better = rerr < err
        cand = (np.where(better, r0, c0), np.where(better, r1, c1), np.where(better[:, None], ridx, idx),
                np.where(better, rerr, err))
        if best is None:
            best = cand
        else:                                              # the 3-colour mode only where strictly better
            take = cand[3] < best[3]
            best = tuple(np.where(take[:, None] if x.ndim == 2 else take, y, x) for x, y in zip(best, cand))
    c0, c1, idx = best[:3]
    bits = (idx << (2 * np.arange(16, dtype=np.uint32))).sum(1).astype(np.uint32)
    out = np.zeros((n, 8), np.uint8)
    out[:, 0], out[:, 1] = c0 & 255, c0 >> 8
    out[:, 2], out[:, 3] = c1 & 255, c1 >> 8
    for k in range(4):
        out[:, 4 + k] = (bits >> (8 * k)) & 255
    return out


def _alpha_blocks(a):
    """a: (n, 16) float -> (n, 8) uint8 DXT5 alpha blocks (8-value mode)."""
    n = len(a)
    a0 = np.clip(np.round(a.max(1)), 0, 255).astype(np.uint32)
    a1 = np.clip(np.round(a.min(1)), 0, 255).astype(np.uint32)
    f0, f1 = a0.astype(np.float32)[:, None], a1.astype(np.float32)[:, None]
    k = np.arange(2, 8, dtype=np.float32)[None, :]
    pal = np.concatenate([f0, f1, ((8 - k) * f0 + (k - 1) * f1) / 7], 1)       # (n, 8)
    idx = np.abs(a[:, :, None] - pal[:, None, :]).argmin(-1).astype(np.uint64)
    idx[a0 == a1] = 0
    bits = (idx << (3 * np.arange(16, dtype=np.uint64))).sum(1)
    out = np.zeros((n, 8), np.uint8)
    out[:, 0], out[:, 1] = a0, a1
    for j in range(6):
        out[:, 2 + j] = ((bits >> np.uint64(8 * j)) & np.uint64(255)).astype(np.uint8)
    return out


def needs_alpha(rgba):
    return bool((rgba[..., 3] < 250).any())


def binary_alpha(rgba):
    """Alpha only fully transparent or opaque (a DXT1 texture with 1-bit alpha, decoded): DXT1 keeps it."""
    a = rgba[..., 3]
    if not (bool(((a == 0) | (a == 255)).all()) and bool((a == 0).any())):
        return False
    # DXT1's transparent texel decodes as black: only when the transparent texels are black already. The town's
    # light maps (s_shadow, t_shadow: DXT5, the light in RGB, alpha 0 everywhere) came out black as DXT1
    return not bool(rgba[..., :3][a == 0].any())


def _punch_blocks(px, a):
    """DXT1 with 1-bit alpha: blocks with a transparent texel (alpha < 128) use the 3-colour mode (colour 0 <= colour
    1, index 3 = transparent black), end colours from the opaque texels' range; other blocks the 4-colour mode."""
    out = _colour_blocks(px, three=True)
    tr = a < 128
    sel = tr.any(1)
    if not sel.any():
        return out
    p, t = px[sel], tr[sel]
    big = np.float32(1e9)
    lo = np.where(t[..., None], big, p).min(1)
    hi = np.where(t[..., None], -big, p).max(1)
    none = ~(~t).any(1)
    lo[none], hi[none] = 0.0, 0.0
    c0, c1 = _to565(lo), _to565(hi)
    c0, c1 = np.minimum(c0, c1), np.maximum(c0, c1)               # c0 <= c1: the 3-colour mode
    e0, e1 = _from565(c0), _from565(c1)
    pal = np.stack([e0, e1, (e0 + e1) / 2], 1)
    idx = ((p[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1).argmin(-1).astype(np.uint32)
    idx[t] = 3
    bits = (idx << (2 * np.arange(16, dtype=np.uint32))).sum(1).astype(np.uint32)
    o = np.zeros((len(p), 8), np.uint8)
    o[:, 0], o[:, 1] = c0 & 255, c0 >> 8
    o[:, 2], o[:, 3] = c1 & 255, c1 >> 8
    for k in range(4):
        o[:, 4 + k] = (bits >> (8 * k)) & 255
    out[sel] = o
    return out


def encode(rgba, alpha=None, punch=False):
    """One mip level: (h, w, 4) uint8 RGBA, top row first -> (format, bytes). punch: DXT1 with 1-bit alpha."""
    alpha = needs_alpha(rgba) if alpha is None else alpha
    b = _blocks(rgba)
    if punch:
        return BC1, _punch_blocks(b[:, :, :3], b[:, :, 3]).tobytes()
    if not alpha:
        return BC1, _colour_blocks(b[:, :, :3], three=True).tobytes()
    colour = _colour_blocks(b[:, :, :3])
    return BC3, np.concatenate([_alpha_blocks(b[:, :, 3]), colour], 1).tobytes()
