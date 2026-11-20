"""PD Stage Shader checks in Blender (no window).

  blender -b --factory-startup --python tests/blender_material.py -- <Assets/Data folder> <out_dir>

1. The PD Stage Shader group builds with exactly the game's settings.
2. Four planes, one per game shader (plain, normal map, reflection, both), with highlight colours and a painted
   shine mask, export to the right shaders, texture roles, specular bytes, vertex alpha and tangents.
3. Importing st04 gives PD materials carrying the game's highlight values and normal maps.
Never touches the game folder (writes to out_dir).
"""
import math
import os
import struct
import sys

import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'addon'))
sys.path.insert(0, ROOT)
import phantom_dust_stage as addon          # noqa: E402
from phantom_dust_stage import pd_material  # noqa: E402
from pdstage import alr                     # noqa: E402

args = sys.argv[sys.argv.index('--') + 1:]
data, out_dir = args[0], args[1]
os.makedirs(out_dir, exist_ok=True)
addon.register()
fails = []


def check(cond, what):
    print(('PASS ' if cond else 'FAIL ') + what)
    if not cond:
        fails.append(what)


def image(name, rgba, size=8):
    img = bpy.data.images.new(name, size, size, alpha=True)
    img.pixels = list(rgba) * (size * size)
    return img


# 1. the group
ng = pd_material.ensure_group()
names = [i.name for i in ng.interface.items_tree if getattr(i, 'in_out', None) == 'INPUT']
check(names == [s[1] for s in pd_material.SOCKETS], 'group inputs are exactly the game settings: %s' % names)

# 2. a scene with one plane per shader
scene = bpy.context.scene
vis = bpy.data.collections.new('Visuals')
scene.collection.children.link(vis)
vis.pd_role = 'VISUALS'
diff = image('pdtest_diffuse', (0.5, 0.4, 0.3, 1.0))
norm = image('pdtest_normal', (0.5, 0.5, 1.0, 0.5))
refl = image('pdtest_refl', (0.2, 0.3, 0.4, 1.0))
cases = [('sd', None, None), ('sbts', norm, None), ('sdrefs', None, refl), ('sbtsrefs', norm, refl)]
for k, (kind, n, r) in enumerate(cases):
    bpy.ops.mesh.primitive_plane_add(size=4, location=(k * 6, 0, 6.4))
    ob = bpy.context.object
    ob.name = 'plane_' + kind
    for c in ob.users_collection:
        c.objects.unlink(ob)
    vis.objects.link(ob)
    light = ob.data.color_attributes.new('PD_Light', 'BYTE_COLOR', 'POINT')
    for d in light.data:
        d.color_srgb = (0.8, 0.6, 0.4, 1.0)
    mat = pd_material.setup(bpy.data.materials.new('mat_' + kind), diffuse=diff, normal=n, reflection=r,
                            specular=(0.2, 0.2, 0.2), shininess=40, shine=0.25, reflection_strength=0.5)
    ob.data.materials.append(mat)
    check(pd_material.game_shader(pd_material.read(mat)) == kind, '%s: panel shows the right game shader' % kind)

# shine mask painted on the last plane: PD_Shine black -> alpha 0
ob = bpy.data.objects['plane_sbtsrefs']
bpy.context.view_layer.objects.active = ob
ob.select_set(True)
bpy.ops.pdstage.paint_shine()
bpy.ops.object.mode_set(mode='OBJECT')
for d in ob.data.color_attributes['PD_Shine'].data:
    d.color_srgb = (0.0, 0.0, 0.0, 1.0)

out_dat = os.path.join(out_dir, 'st04.dat')
bpy.ops.export_scene.phantom_dust_stage(filepath=out_dat, game_original='st04', game_data=data, remove_objects=True)
b = open(os.path.join(out_dir, 'st04.alr'), 'rb').read()
h = alr.header(b)
texs = alr.textures(b)
seen = {}
for m in alr.meshes(b, h['roots'][0]):
    mat = m['materials'][m['material']]
    if mat['shader'].startswith('sshadow'):
        continue
    vb = m['vbufs'][m['vbuf']]
    roles = struct.unpack_from('<H', mat['raw'], 0x16)[0]
    cols = alr.read_colours(b, h['resource_offset'], vb)
    seen[mat['shader']] = (vb['format'], vb['vertex_size'], roles, bytes(mat['raw'][0x34:0x38]), cols,
                           [texs[t]['name'] for t in mat['textures']], m, vb)
for kind, n, r in cases:
    check(kind in seen, '%s exported' % kind)
    if kind not in seen:
        continue
    fmt, size, roles, spec, cols, tnames, m, vb = seen[kind]
    bump = n is not None
    check((fmt, size) == ((3, 0x20) if bump else (1, 0x18)), '%s: vertex format %d size %d' % (kind, fmt, size))
    check(roles == {'sd': 1, 'sbts': 0x21, 'sdrefs': 0x41, 'sbtsrefs': 0x421}[kind], '%s: texture roles %04x' % (kind, roles))
    g = round(pd_material._srgb(0.2) * 255)          # colour sockets are linear; bytes match the picker's hex
    check(spec[:3] == bytes((g, g, g)) and spec[3] == 40, '%s: specular bytes %s (want %02x x3, power 40)'
          % (kind, spec.hex(), g))
    alpha = {c[3] for c in cols}
    want = {0} if kind == 'sbtsrefs' else {64}
    check(alpha == want, '%s: vertex alpha (shine mask) %s, want %s' % (kind, alpha, want))
    check({c[:3] for c in cols} == {(204, 153, 102)}, '%s: baked light bytes %s' % (kind, {c[:3] for c in cols}))
    check(tnames[0] == 'pdtest_diffu', '%s: diffuse texture in slot 0' % kind)
    if r is not None:
        check(any(t.startswith('pdtest_refl') for t in tnames), '%s: reflection texture used' % kind)
    if bump:
        # tangent = +U, binormal = +V of Blender's UV map, converted to game axes; the plane faces up (game +Y)
        v = h['resource_offset'] + vb['offset']
        unpack = lambda w: (((w & 0x7FF) ^ 0x400) - 0x400) / 1023, ((((w >> 11) & 0x7FF) ^ 0x400) - 0x400) / 1023, \
            (((w >> 22) ^ 0x200) - 0x200) / 511
        nrm, tan, bit = (unpack(struct.unpack_from('<I', b, v + o)[0]) for o in (0x0C, 0x18, 0x1C))
        check(abs(nrm[1] - 1) < 0.01, '%s: normal up %s' % (kind, nrm))
        check(abs(tan[0] - 1) < 0.01, '%s: tangent = +X (Blender +U) %s' % (kind, tan))
        check(abs(bit[2] + 1) < 0.01, '%s: binormal = game -Z (Blender +Y, +V) %s' % (kind, bit))

# 3. import gives game values
bpy.ops.import_scene.phantom_dust_stage(filepath=os.path.join(data, 'Map', 'st04.dat'), visuals=True)
mats = [m for m in bpy.data.materials if pd_material.group_node(m) is not None]
check(len(mats) > 10, '%d imported PD materials' % len(mats))
bump = [m for m in mats if pd_material.read(m)['normal'] is not None]
check(len(bump) > 0, '%d imported materials with a normal map' % len(bump))
shiny = [m for m in mats if any(pd_material.read(m)['specular'][:3])]
check(len(shiny) > 0, '%d imported materials with a highlight, e.g. %s' % (
    len(shiny), [(m.name, pd_material.read(m)['specular']) for m in shiny[:2]]))

print('\n%d failures' % len(fails))
sys.exit(1 if fails else 0)
