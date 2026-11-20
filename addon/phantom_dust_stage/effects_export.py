"""Effects collections -> map effects (steam, sparks, smoke...).

  Effects                 role Effects
    Steam vents           one child collection per effect type: Effect preset (Collection Properties)
      Empty, Empty.001    every object directly in it is one placement: location, rotation about Z
                          (added to the preset's own turn), and scale (multiplies the preset's size)

Presets copy one of the game's own effect entries from the user's game files at export time.
"""
import os
import struct

from ._lib import effects_build
from . import convert as cv


class EffectsError(Exception):
    pass


PORTABLE_KINDS = (2, 22, 24)          # smoke, steam / smoke / fire, sparks: work in any map (FORMATS.md)


MODEL_KINDS = (10, 13, 14, 15)        # effect models: u16 at 0x28 = their slot in the map's MD00 models list


def _imported_entries(scene):
    """(empty, raw entry, home map) of every imported effect in the scene's Effects collections."""
    from .exporter import collections_with_role
    for ec in collections_with_role(scene, 'EFFECTS'):
        for tc in ec.children:
            if getattr(tc, 'pd_effect', '') != 'GAME':
                continue
            for ob in tc.objects:
                if 'pd_effect_raw' in ob:
                    yield ob, bytes.fromhex(ob['pd_effect_raw']), ob.get('pd_effect_map', '')


def foreign_models(scene, game_data, base_texture_count, new_textures):
    """Effect models (Storm Refinery's sea, lamps, flags...) placed by imported effects from another map than
    the one replaced: their model, nodes and textures copied from the home map's files so the effect can be
    kept. Only models without a .ala animation (those are not readable yet). Returns (models for the .alr,
    keys [(home, slot)] in the same order, md00 names {key: name}). New textures are appended to new_textures."""
    from .exporter import original_path
    from ._lib import alr, alr_build, dat
    target = scene.pd_game_original
    wanted = []
    for _ob, raw, home in _imported_entries(scene):
        if raw[0] in MODEL_KINDS and home and home != target:
            key = (home, struct.unpack_from('<H', raw, 0x28)[0])
            if key not in wanted:
                wanted.append(key)
    models, keys, names, files = [], [], {}, {}
    for home, slot in wanted:
        if home not in files:
            try:
                files[home] = (open(original_path(game_data, home + '.dat'), 'rb').read(),
                               open(original_path(game_data, home + '.alr'), 'rb').read())
            except OSError:
                files[home] = None
        if files[home] is None:
            continue
        hd, ha = files[home]
        md = dat.md00(hd)
        if md is None or slot >= len(md[2]):
            continue
        root, anim = md[2][slot]
        h = alr.header(ha)
        if root < 0 or anim != -1 or root >= len(h['roots']):
            continue
        meshes = alr.meshes(ha, h['roots'][root])
        if not meshes:
            continue
        texs = alr.textures(ha)
        tex_new = {}
        out = []
        for m in meshes:
            r = alr_build.raw_mesh(ha, m, h['resource_offset'], apply_node=False)
            over = {}
            for k, t in enumerate(m['materials'][m['material']]['textures']):
                if t is None or t >= len(texs) or texs[t]['cubemap'] or texs[t]['npot']:
                    continue
                if t not in tex_new:
                    tx = texs[t]
                    start = h['resource_offset'] + tx['offset']
                    tex_new[t] = len(new_textures)
                    new_textures.append(dict(name=tx['name'] or 'pd_fx', width=tx['width'], height=tx['height'],
                                             levels=[bytes(ha[start:start + tx['size']])],
                                             mips=tx['mips'], format=tx['raw_format']))
                over[k] = ('new', tex_new[t])
            r['raw']['tex_override'] = over
            out.append(r)
        nodes = [dict(t=n['t'], rot=n['rot'], scale=n['scale'], flags=n['flags'], parent=n['parent'],
                      values=n['values'], marker=n['marker']) for n in meshes[0]['nodes']]
        models.append(dict(meshes=out, nodes=nodes))
        keys.append((home, slot))
        names[(home, slot)] = md[0][slot]
    return models, keys, names


def gather(context, eff_colls, scale, game_data, carried=None):
    """Returns (list of raw entries, count per preset)."""
    cache, entries, counts, skipped = {}, [], {}, {}
    for ec in eff_colls:
        for tc in ec.children:
            preset = getattr(tc, 'pd_effect', 'STEAM_PIPE')
            if preset == 'GAME':                          # imported: each empty keeps the game's own entry
                target = context.scene.pd_game_original
                for ob in tc.objects:
                    if 'pd_effect_raw' not in ob:
                        continue
                    raw = bytearray(bytes.fromhex(ob['pd_effect_raw']))
                    home = ob.get('pd_effect_map', '')
                    key = (home, struct.unpack_from('<H', raw, 0x28)[0]) if raw[0] in MODEL_KINDS else None
                    if key is not None and home != target and carried and key in carried:
                        struct.pack_into('<H', raw, 0x28, carried[key])      # its model, copied into this map
                    elif raw[0] not in PORTABLE_KINDS and home != target:
                        # sounds, effect models, glow... point into their home map's own files: in another map
                        # they read past its lists and the game crashes on load
                        skipped[home or '?'] = skipped.get(home or '?', 0) + 1
                        continue
                    mw = ob.matrix_world
                    rx, _ry, rz = struct.unpack_from('<3f', raw, 0x10)
                    struct.pack_into('<3f', raw, 0x10, rx, 0.0, rz)        # its turn comes from the empty
                    base_scale = struct.unpack_from('<3f', raw, 0x1C)
                    s = mw.to_scale()
                    mult = (s.x, s.z, s.y)
                    entries.append(effects_build.place(bytes(raw), cv.to_game(mw.translation, scale),
                                                       yaw=cv.yaw_to_game(mw.to_euler('XYZ').z),
                                                       scale=tuple(base_scale[k] * mult[k] for k in range(3))))
                    counts['imported'] = counts.get('imported', 0) + 1
                continue
            source_map, index = effects_build.PRESETS[preset][:2]
            if source_map not in cache:
                from .exporter import original_path       # the game's own file, even if a map replaced it
                path = original_path(game_data, source_map + '.dat')
                if not os.path.isfile(path):
                    raise EffectsError('effect preset %s needs %s from the game' % (preset, path))
                cache[source_map] = open(path, 'rb').read()
            raw = effects_build.preset_entry(cache[source_map], index)
            base_scale = struct.unpack_from('<3f', raw, 0x1C)
            for ob in tc.objects:
                mw = ob.matrix_world
                e = mw.to_euler('XYZ')
                s = mw.to_scale()
                # Blender scale (x, y, z) -> game axes (x, z, y)
                mult = (s.x, s.z, s.y)
                entries.append(effects_build.place(raw, cv.to_game(mw.translation, scale), yaw=cv.yaw_to_game(e.z),
                                                   scale=tuple(base_scale[k] * mult[k] for k in range(3))))
                counts[preset] = counts.get(preset, 0) + 1
    for home, n in skipped.items():
        print('Phantom Dust export warning: %d imported effects (sounds, effect models...) from %s left out: they '
              'only work in their own map%s' % (n, home if home != '?' else 'an earlier import',
                                                '' if home != '?' else ' (import it again to keep them there)'))
        counts['left out (other map)'] = counts.get('left out (other map)', 0) + n
    return entries, counts
