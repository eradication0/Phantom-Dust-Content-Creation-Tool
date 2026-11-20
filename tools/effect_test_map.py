"""Build an effect test map: one labelled pad per effect preset the add-on offers (pdstage/effects_build.PRESETS),
with that effect placed in the middle of its pad, so every preset can be checked in game.

    python tools/effect_test_map.py GAME_MAP_DIR BASE_DAT BASE_ALR OUT_DIR [--map st03]

GAME_MAP_DIR: the game's Assets/Data/Map folder (presets are copied from the game's own map files; a
pd_addon_backup copy is used if the map was replaced). BASE_DAT / BASE_ALR: the game's own files of the map
being replaced (Lost Palace, st03). Builds on tools/surface_test_map.py: plain floor (surface 08), invisible edge
walls, spawns on the near row facing the pads.
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'addon', 'phantom_dust_stage'))
import surface_test_map as stm  # noqa: E402
from pdstage import effects_build  # noqa: E402

EXTRA = []          # extra (preset, label, size multiplier, height) pads, e.g. ('BLACK_SMOKE', 'x3', 3.0, 0.0)


def pads():
    """(preset, label, size multiplier, height above the floor) per pad."""
    out = [(k, v[2], 1.0, 0.0) for k, v in effects_build.PRESETS.items()]
    return out + EXTRA


def label_atlas_for(labels):
    def atlas(values, cols, rows, size=512, tested=(), start=False):
        from PIL import Image, ImageDraw, ImageFont
        import colorsys
        im = Image.new('RGBA', (size, size), (40, 40, 40, 255))
        d = ImageDraw.Draw(im)
        cw, ch = size // cols, size // rows
        try:
            num = ImageFont.load_default(size=int(ch * 0.34))
            font = ImageFont.load_default(size=int(cw * 0.17))
        except TypeError:
            num = font = ImageFont.load_default()
        for i, text in enumerate(labels):
            cx, cy = (i % cols) * cw, (i // cols) * ch
            r, g, b = (int(255 * c) for c in colorsys.hsv_to_rgb((i * 0.61803) % 1.0, 0.45, 0.85))
            d.rectangle([cx, cy, cx + cw - 1, cy + ch - 1], fill=(r, g, b, 255), outline=(20, 20, 20, 255), width=3)
            n = str(i + 1)
            tw, th = d.textbbox((0, 0), n, font=num)[2:]
            d.text((cx + (cw - tw) / 2, cy + ch * 0.12), n, fill=(15, 15, 15, 255), font=num)
            lines = text.replace(',', '').split()
            for j, line in enumerate(lines):
                lw = d.textbbox((0, 0), line, font=font)[2]
                d.text((cx + (cw - lw) / 2, cy + ch * (0.56 + 0.12 * j)), line, fill=(15, 15, 15, 255), font=font)
        for j in range(len(labels), cols * rows):            # unused cells: plain grey
            cx, cy = (j % cols) * cw, (j // cols) * ch
            d.rectangle([cx, cy, cx + cw - 1, cy + ch - 1], fill=(90, 90, 90, 255), outline=(20, 20, 20, 255), width=3)
        levels, w, cur = [], size, im
        while True:
            r_, g_, b_, a_ = cur.split()
            levels.append(Image.merge('RGBA', (b_, g_, r_, a_)).tobytes())
            if w == 1:
                break
            w //= 2
            cur = im.resize((w, w), Image.BOX)
        return size, size, levels, im
    return atlas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('map_dir')
    ap.add_argument('base_dat')
    ap.add_argument('base_alr')
    ap.add_argument('out_dir')
    ap.add_argument('--map', default='st03')
    ap.add_argument('--raise', dest='lift', type=float, default=10.0,
                    help='height of every effect above the floor, game units (10 = 1 m in Blender)')
    a = ap.parse_args()
    todo = pads()
    labels = [t[1] for t in todo]
    stm.label_atlas = label_atlas_for(labels)
    d, m, stats, preview = stm.build(a.base_dat, a.base_alr, [0x08] * len(todo))

    cache, entries = {}, []
    cols = stm.COLS
    rows = (len(todo) + cols - 1) // cols
    x0, z_far = -cols * stm.PAD / 2, rows * stm.PAD / 2
    for i, (preset, label, mult, up) in enumerate(todo):
        src, index = effects_build.PRESETS[preset][:2]
        if src not in cache:
            p = os.path.join(a.map_dir, 'pd_addon_backup', src + '.dat')
            cache[src] = open(p if os.path.isfile(p) else os.path.join(a.map_dir, src + '.dat'), 'rb').read()
        raw = effects_build.preset_entry(cache[src], index)
        c, r = i % cols, i // cols
        pos = (x0 + (c + 0.5) * stm.PAD, up + a.lift, z_far - (r + 0.5) * stm.PAD)
        scale = tuple(x * mult for x in struct.unpack_from('<3f', raw, 0x1C))
        entries.append(effects_build.place(raw, pos, scale=scale))
        print('%2d  %-18s kind %2d from %s #%d  scale %s' % (i + 1, label, raw[0], src, index,
                                                               tuple(round(x, 2) for x in scale)))
    d = effects_build.set_effects(d, entries)
    os.makedirs(a.out_dir, exist_ok=True)
    open(os.path.join(a.out_dir, a.map + '.dat'), 'wb').write(d)
    open(os.path.join(a.out_dir, a.map + '.alr'), 'wb').write(m)
    preview.save(os.path.join(a.out_dir, a.map + '_effect_labels.png'))


if __name__ == '__main__':
    main()
