"""The map's light script as Blender lights and worlds.

The stage .dat's "mapLight" script (pdstage/maplight.py) makes 22 calls: per light set (0 stage with its objects and
effects, 1 characters, 2 and 3 the far / background models) one light call, one fog call and three point-light
calls, then a global colour and a global scale. In Blender:

  Lighting (collection)
    PD Light: stage / characters / far 1 / far 2        sun lights: rotation = the set's light direction (the way
                                                         the light travels; the object's scale = the stored
                                                         vector's length), colour = diffuse colour,
                                                         custom properties pd_light_set, pd_light_second (second
                                                         diffuse colour), pd_light_axis (ambient axis)
    PD Point: <set> <slot>                               point lights: location, colour; range = the light's
                                                         custom distance (off = slot unused)
  worlds PD World: <set>                                 colour = the set's ambient colour; mist settings = its fog
                                                         (start, depth = end - start), custom properties
                                                         pd_light_set, pd_fog_mode (0 off, 1/2 exponential,
                                                         3 linear), pd_fog_colour, pd_fog_density
  scene custom properties pd_shadow_colour, pd_glare_level, pd_glare_colour

The scene's world is the stage set's. Export writes the 22 calls from these (build_script).
Colours are the script's bytes / 255 (no colour management); distances are game units x the scene scale.
"""
import math
import struct

import bpy
from mathutils import Matrix, Vector

from . import convert as cv
from ._lib import maplight

SETS = maplight.SET_NAMES                  # ('stage', 'characters', 'far 1', 'far 2')


def _rgb(c):
    return tuple(x / 255.0 for x in c)


def _byte3(c):
    return tuple(max(0, min(255, int(round(x * 255.0)))) for x in c[:3])


def _sun_rotation(d):
    """Euler rotation turning a sun's -Z onto Blender direction d."""
    v = Vector(d)
    if v.length < 1e-12:
        return (0.0, 0.0, 0.0)
    return Vector((0.0, 0.0, -1.0)).rotation_difference(v.normalized()).to_euler('XYZ')


def import_lights(context, b_dat, parent, scale, stage):
    """Lights and worlds from the map's light script; returns a report string."""
    script = next((s for s in (maplight.script_of(bytes(b_dat), v) for v in range(maplight.VARIANT_SLOTS))
                   if s is not None), None)
    if script is None:
        return 'no light script'
    d = maplight.describe(script)
    coll = bpy.data.collections.new('Lighting')
    parent.children.link(coll)
    coll.pd_role = 'LIGHTING'
    scene = context.scene
    points = 0
    for i, s in enumerate(d['sets']):
        name = SETS[i]
        ld = bpy.data.lights.new('PD Light: %s' % name, 'SUN')
        ld.color = _rgb(s.get('diffuse', (0, 0, 0)))
        ld['pd_light_second'] = list(_rgb(s.get('diffuse2', (0, 0, 0))))
        ld['pd_light_axis'] = list(s.get('axis', (0.0, 1.0, 0.0)))
        ob = bpy.data.objects.new('PD Light: %s' % name, ld)
        ob['pd_light_set'] = i
        g = s.get('direction', (0.0, -1.0, 0.0))
        ob.rotation_euler = _sun_rotation(cv.to_blender(g, 1.0))
        length = math.sqrt(sum(x * x for x in g))
        ob.scale = (length, length, length)
        ob.hide_render = i != 0                  # only the stage set lights the bake (Bake Lighting)
        coll.objects.link(ob)
        w = bpy.data.worlds.new('PD World: %s' % name)
        w.color = _rgb(s.get('ambient', (0, 0, 0)))
        w['pd_light_set'] = i
        mode = int(s.get('fog_mode', 0))
        w['pd_fog_mode'] = mode
        w['pd_fog_colour'] = list(_rgb(s.get('fog_colour', (0, 0, 0))))
        w.use_fake_user = True                   # the far sets' worlds are not the scene's: keep them when saved
        start = s.get('fog_start', 0.0)
        w.mist_settings.start = max(0.0, start * scale)
        if start < 0.0:
            # Blender's mist cannot start before the camera; the game's fog can (st04: -70): the start is kept
            # here, and used while the mist start stays at 0
            w['pd_fog_start'] = start
        if mode == maplight.FOG_LINEAR:
            w.mist_settings.depth = max(0.0, (s.get('fog_end', 0.0) - start) * scale)
            w.mist_settings.falloff = 'LINEAR'
            w['pd_fog_density'] = 0.0
        else:
            w['pd_fog_density'] = s.get('fog_density', 0.0)
            w.mist_settings.falloff = 'QUADRATIC'
        if i == 0:
            scene.world = w
        for k, p in enumerate(s['points']):
            p = p or dict(range=0.0, pos=(0.0, 0.0, 0.0), colour=(0, 0, 0))
            pl = bpy.data.lights.new('PD Point: %s %d' % (name, k + 1), 'POINT')
            pl.color = _rgb(p['colour'])
            pl.use_custom_distance = p['range'] != 0.0
            pl.cutoff_distance = p['range'] * scale
            po = bpy.data.objects.new(pl.name, pl)
            po['pd_light_set'] = i
            po['pd_point_slot'] = k
            po.location = cv.to_blender(p['pos'], scale)
            po.hide_render = True
            po.hide_viewport = p['range'] == 0.0
            coll.objects.link(po)
            points += p['range'] != 0.0
    # 2001 (syscall 2:1): the colour the shadow pass lays over every stencilled pixel (character and stage
    # shadows); 2003 (2:3): the glare level the bright pass eases toward each frame, and a glare colour the
    # single-screen chain does not use (clean-room render notes: shadow pass, glare chain)
    calls = {cid: args for cid, args in script['calls'] if cid in (maplight.GLOBAL_COLOUR, maplight.GLOBAL_SCALE)}
    if maplight.GLOBAL_COLOUR in calls:
        scene['pd_shadow_colour'] = list(_rgb(maplight._colour(calls[maplight.GLOBAL_COLOUR][1])))
    if maplight.GLOBAL_SCALE in calls:
        scene['pd_glare_level'] = maplight._num(calls[maplight.GLOBAL_SCALE][0])
        scene['pd_glare_colour'] = list(_rgb(maplight._colour(calls[maplight.GLOBAL_SCALE][1])))
    return 'lighting: 4 light sets, %d point lights in use' % points


def scene_has_lights(scene):
    return any(o.type == 'LIGHT' and 'pd_light_set' in o for o in scene.objects)


def _list(v, n, default):
    try:
        out = [float(x) for x in v]
        return out if len(out) == n else list(default)
    except (TypeError, ValueError):
        return list(default)


def build_script(scene, scale, stage):
    """The 22-call script (maplight.parse form) from the scene's PD lights and worlds."""
    suns, points, worlds = {}, {}, {}
    for o in scene.objects:
        if o.type != 'LIGHT' or 'pd_light_set' not in o:
            continue
        i = int(o['pd_light_set'])
        if o.data.type == 'SUN':
            suns.setdefault(i, o)
        elif o.data.type == 'POINT' and 'pd_point_slot' in o:
            points.setdefault((i, int(o['pd_point_slot'])), o)
    for w in bpy.data.worlds:
        if 'pd_light_set' in w:
            worlds.setdefault(int(w['pd_light_set']), w)
    if scene.world is not None and 'pd_light_set' in scene.world:
        worlds[int(scene.world['pd_light_set'])] = scene.world
    sets = []
    for i in range(4):
        sun, w = suns.get(i), worlds.get(i)
        s = dict(axis=(0.0, 1.0, 0.0), direction=(0.0, -1.0, 0.0), diffuse=(0, 0, 0), diffuse2=(0, 0, 0),
                 ambient=(0, 0, 0), fog_mode=0, fog_a=0.0, fog_start=0.0, fog_colour=(0, 0, 0), points=[None] * 3)
        if sun is not None:
            m = sun.matrix_world
            d = (m.to_3x3().normalized() @ Vector((0.0, 0.0, -1.0))).normalized() * m.to_scale().z
            s['direction'] = cv.to_game(d, 1.0)
            s['axis'] = _list(sun.data.get('pd_light_axis'), 3, (0.0, 1.0, 0.0))
            s['diffuse'] = _byte3(sun.data.color)
            s['diffuse2'] = _byte3(_list(sun.data.get('pd_light_second'), 3, (0, 0, 0)))
        if w is not None:
            s['ambient'] = _byte3(w.color)
            s['fog_mode'] = mode = int(w.get('pd_fog_mode', 0))
            s['fog_start'] = w.mist_settings.start / scale
            if w.mist_settings.start == 0.0 and 'pd_fog_start' in w:
                s['fog_start'] = float(w['pd_fog_start'])
            s['fog_a'] = (s['fog_start'] + w.mist_settings.depth / scale if mode == maplight.FOG_LINEAR
                          else float(w.get('pd_fog_density', 0.0)))
            s['fog_colour'] = _byte3(_list(w.get('pd_fog_colour'), 3, (0, 0, 0)))
        for k in range(3):
            p = points.get((i, k))
            if p is not None and p.data.use_custom_distance:
                s['points'][k] = dict(range=p.data.cutoff_distance / scale, colour=_byte3(p.data.color),
                                      pos=cv.to_game(p.matrix_world.translation, scale))
        sets.append(s)
    try:
        n = int(stage[2:4])
    except (TypeError, ValueError):
        n = 0
    return maplight.script_from(sets, _byte3(_list(scene.get('pd_shadow_colour'), 3, (0, 0, 0))),
                                float(scene.get('pd_glare_level', 1.0)),
                                _byte3(_list(scene.get('pd_glare_colour'), 3, (0, 0, 0))), n)


NONE32 = 0xFFFFFFFF


def script_slot(stage):
    """Header word 0xD0 + 4 * k the game runs for this stage: k = the stage number's tens digit (docs "dat_stage":
    word 0xD0 + 4 * k, else 0xD0)."""
    try:
        return min(int(stage[2:4]) // 10, maplight.VARIANT_SLOTS - 1)
    except (TypeError, ValueError):
        return 0


def put_script(b, script, stage):
    """New .dat bytes with the script appended and the stage's light words pointed at it; every other light word
    cleared (the game's maps have one script). The old script, unused, is removed by datfile.compact."""
    buf = bytearray(b)
    buf += b'\0' * (-len(buf) % 4)
    off = len(buf)
    buf += maplight.build(script)
    # the word the game runs for the stage, and word 0xD0 (the one it falls back to when that is -1: a map exported
    # for one slot and installed over another still has its lights); one script
    k = script_slot(stage)
    for v in range(maplight.VARIANT_SLOTS):
        struct.pack_into('<I', buf, maplight.H_SCRIPT + 4 * v, off if v in (0, k) else NONE32)
    struct.pack_into('<I', buf, 0x138, len(buf))
    return bytes(buf)
