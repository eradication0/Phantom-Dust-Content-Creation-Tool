"""The town's light lists and the lights each town draw uses, as Blender lights and light linking.

Game side (clean-room notes from the Xbox executable, research p3-dropped-data.md):
- chunk 0x09 is a light list: u32 count, then 40-byte records: colour (B, G, R, A), type (1 directional, 2 point,
  5 ambient), the light's number in the game's 256-entry light table, flags (bit 1: use that number; bit 3: a light
  of the stage's own draws; bit 4: a light for characters, picked at run time by power / distance^2), direction
  (+8), power (+20), position (+24), a value for directional lights (+36). `st09.dat` plays one when the town
  starts (header 0xFC, numbers from 32 up, the ambient at 63); each area `.dat` (st09_NN, header 0x18) plays its own
  (numbers from 0 up).
- a draw (chunk 0x02, +0x28 count, +0x2C indices) names the lights it is lit with. Only the town reads it. The
  lists were assigned per authored object, not by distance (on every town file each joint's draws share one list;
  the run-time distance rule matches only half of them). The lit shaders take the first point light of the list,
  the second slot the last one; the lists name lights in the order of the light list.

Blender side:
- a collection `Town_Lights` with one light per record: point lights (location, colour, energy = the game's power:
  light ~ power / distance^2 in game units), `pd_town_light` = 'point' / 'ambient' / 'directional' (the record's
  type), `pd_lights_stage` / `pd_lights_characters` (flags bits 3 / 4) and `pd_light_slot` (the light's number);
- each light's light linking receiver collection holds the stage meshes whose draws name it.
Export: the light list chunk from the lights, each draw's list from the light linking, both in the lights' name
order. The import keeps the game's light numbers (pd_light_slot; other files and the props kept as the game's refer
to them) and starts each name with the record's place in the list, so name order is the game's list order (which is
not number order: st09 lists 36 before 35, 63 before 55 and 54).
"""
import struct

import bpy
from mathutils import Vector

from . import convert as cv
from .pdstage import enter

COLL = 'Town_Lights'
TYPES = {1: 'directional', 2: 'point', 3: 'point', 5: 'ambient'}
TYPE_OF = {'directional': 1, 'point': 2, 'ambient': 5}


def stream_offset(b):
    """(offset field position, base number) of the file's light list stream, or None."""
    from ._lib import dat
    kind = dat.layout_kind(b)
    if kind == 'stage' and len(b) >= 0x100:
        return (0xFC, 32) if struct.unpack_from('<i', b, 0xFC)[0] not in (-1, 0) else None
    if kind == 'area' and len(b) >= 0x1C:
        return (0x18, 0) if struct.unpack_from('<i', b, 0x18)[0] not in (-1, 0) else None
    return None


def import_town_lights(context, b, alr_path, parent, scale, stage):
    """Lights of the file's light list and, from the .alr's draws (visuals.IMPORTED), the light linking."""
    so = stream_offset(b)
    recs = enter.read(b, base=so[1], field=so[0])['lights'] if so else []
    if not recs:
        return ''
    from . import visuals
    coll = bpy.data.collections.new(COLL)
    parent.children.link(coll)
    by_index, skipped = {}, 0
    for k, r in enumerate(recs):
        kind = TYPES.get(r['kind'])
        if kind is None:
            skipped += 1
            continue
        # the game's own light number (every town record names it explicitly): area props kept as the game's and
        # other files refer to them by number (st09_03's props name the hub's lights 48 and 63). The name starts
        # with the record's place in the list: the export writes the list, and each draw's lights, in name order (a
        # draw's first point light is the one the lit shaders take; the game's draws list their lights in list
        # order, which is not number order: st09 35/36, st09_05)
        number = r['index']
        name = 'PD Town %02d %s %d' % (k, {'point': 'light'}.get(kind, kind), number)
        ld = bpy.data.lights.new(name, 'SUN' if kind != 'point' else 'POINT')
        ld.color = tuple(c / 255.0 for c in r['colour'])
        ld.energy = r['intensity']
        ob = bpy.data.objects.new(name, ld)
        if kind == 'point':
            ob.location = Vector(cv.to_blender(r['position'], scale))
        elif kind == 'directional':
            d = Vector(cv.to_blender(r['vector'], 1.0))
            if d.length > 0:
                ob.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
        ob['pd_town_light'] = kind
        ob['pd_light_slot'] = number
        ob['pd_lights_stage'] = bool(r['mask'] & 2)
        ob['pd_lights_characters'] = bool(r['mask'] & 4)
        coll.objects.link(ob)
        by_index[number] = ob
    # light linking from the draws
    receivers, linked = {}, 0
    for _ri, _mi, mesh_ob, _off, _joint, idxs in visuals.IMPORTED:
        for idx in idxs:
            light = by_index.get(idx)
            if light is None:
                continue
            rc = receivers.get(light.name)
            if rc is None:
                rc = bpy.data.collections.new('Lit by %s' % light.name)
                light.light_linking.receiver_collection = rc
                receivers[light.name] = rc
            if mesh_ob.name not in rc.objects:
                rc.objects.link(mesh_ob)
                linked += 1
    return 'town lights: %d (from the light list), %d draw-light links%s' % (
        len(by_index), linked, ', %d records of unknown type left out' % skipped if skipped else '')


def town_lights(scene):
    return [o for o in scene.objects if o.type == 'LIGHT' and o.get('pd_town_light') in TYPE_OF]


def draw_lights(ob, lights):
    """Numbers of the town lights whose light linking includes mesh object `ob`, in list order (name order)."""
    out = []
    for L in sorted(lights, key=lambda o: cv.natural_key(o.name)):
        rc = L.light_linking.receiver_collection
        if rc is not None and ob.name in rc.all_objects:
            out.append(int(L['pd_light_slot']))
    return out


def build_stream(scene, scale):
    """The light list stream (one 0x09 chunk and the end chunk) from the scene's town lights, or None."""
    lights = sorted(town_lights(scene), key=lambda o: cv.natural_key(o.name))     # list order = name order
    if not lights:
        return None
    out = []
    for o in lights:
        kind = o['pd_town_light']
        direction = position = (0.0, 0.0, 0.0)
        if kind == 'point':
            position = cv.to_game(o.matrix_world.translation, scale)
        elif kind == 'directional':
            direction = cv.to_game(o.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0)), 1.0)
        out.append(dict(colour=tuple(int(round(max(0.0, min(1.0, x)) * 255)) for x in o.data.color[:3]),
                        kind=TYPE_OF[kind], index=int(o['pd_light_slot']) & 0xFF, vector=direction,
                        intensity=float(o.data.energy), position=position, value_36=0.0,
                        mask=(2 if o.get('pd_lights_stage') else 0) | (4 if o.get('pd_lights_characters') else 0)))
    return enter.build(out)


def put_stream(b, stream):
    """`b` (a stage or area .dat) with its light list stream replaced: the new stream appended, the header pointed
    at it (a stage file's old one is then cut by datfile.compact; an area file keeps the unused bytes)."""
    so = stream_offset(b)
    if so is None:
        return b
    out = bytearray(b)
    out += b'\0' * (-len(out) % 4)
    struct.pack_into('<I', out, so[0], len(out))
    out += stream
    from ._lib import dat
    if dat.layout_kind(b) == 'stage':
        struct.pack_into('<I', out, 0x138, len(out))        # the file size words (stage 0x13C-byte header,
    else:
        struct.pack_into('<I', out, 0x3C, len(out))         # area 0x40-byte header)
    return bytes(out)
