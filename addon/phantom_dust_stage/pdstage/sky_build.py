"""The sky model (root 2 of a stage .alr): read a map's sky layers and build a custom one.

Every map's sky is made of the same kinds of layer (read from all battle maps and the game's shaders):
  dome    shader svc (vertex format 0x0B: position + BGRA colour, 16 bytes): an unlit gradient, the colour is shown
          exactly as stored (confirmed in game: green / orange / blue test on st04 and st05);
          or shader sc (format 0x09) with a sky picture.
  clouds  shader sbtscloud3 (format 0x03): a cloud shell; texture slot 0 = cloud colour (alpha = cover), slot 1 =
          cloud normal map sampled twice. Material bytes 0x3C-0x47 are three (x, y) s16 scroll speeds: colour layer,
          shape layer A, shape layer B (confirmed: 0 = still; st04 uses (150, -75), (200, -100), (90, 0)).
          The clouds are lit by the map's light colours. Sein (st08) has six cloud layers.
  sun     shaders sc / scal / svcal with flag 0x10 at material 0x0C: a sun or glow picture.
"""
import math
import struct

from . import alr

SKY_ROOT = 2
DOME_FORMAT = 0x0B
DOME_VERTEX_SIZE = 0x10
# st07's svc material (flags 0x0001, no highlight); texture slots point at texture 0, which svc doesn't sample
DOME_MATERIAL = ('0032efb50000000000000000010001000b100100001100000000000000000000000000000000000000000000000000'
                 '007f7f7fff000000000000000000000000000000000000000000000000')
DOME_RADIUS = 12000.0                 # game units; the maps' domes are 12,400-13,600
CLOUD_SHADERS = ('sbtscloud3', 'sbtscloud2')
SCROLL_AT = 0x3C


def _is_sun(mat):
    return bool(mat['raw'][0x0C] & 0x10) and not mat['shader'].startswith('sbtscloud')


def read_sky(b):
    """What a map's sky is made of: dome kind and colours by height, cloud layers with their speeds, sun."""
    h = alr.header(b)
    if len(h['roots']) <= SKY_ROOT:
        return dict(dome=None, dome_colours=[], clouds=[], sun=False)
    rb = h['resource_offset']
    dome, samples, clouds, sun = None, [], [], False
    for m in alr.meshes(b, h['roots'][SKY_ROOT]):
        mat = m['materials'][m['material']]
        sh = mat['shader']
        if sh in CLOUD_SHADERS:
            clouds.append(struct.unpack_from('<6h', mat['raw'], SCROLL_AT))
        elif _is_sun(mat):
            sun = True
        elif sh in ('svc', 'svcal') and dome is None:
            dome = 'gradient'
            vb = m['vbufs'][m['vbuf']]
            base, size = rb + vb['offset'], vb['vertex_size']
            for i in range(vb['count']):
                x, y, z = struct.unpack_from('<3f', b, base + i * size)
                c = b[base + i * size + 12:base + i * size + 16]
                r = math.sqrt(x * x + y * y + z * z) or 1.0
                samples.append((math.degrees(math.asin(max(-1.0, min(1.0, y / r)))), (c[2], c[1], c[0])))
        elif sh in ('sc', 'scal') and dome is None:
            dome = 'picture'
    return dict(dome=dome, dome_colours=samples, clouds=clouds, sun=sun)


def dome_colours_at(samples, elevations=(90.0, 35.0, 0.0, -90.0)):
    """Average colour of the dome's vertices nearest each elevation (degrees), as 0-255 tuples."""
    out = []
    for e in elevations:
        near = sorted(samples, key=lambda s: abs(s[0] - e))[:max(1, len(samples) // 12)]
        out.append(tuple(int(round(sum(c[1][k] for c in near) / len(near))) for k in range(3)) if near else (0, 0, 0))
    return out


def _gradient(stops, elevation):
    """stops: [(elevation degrees, (r, g, b) 0-255)] high to low; colour at an elevation, mixed in display space
    (the game shows the stored bytes)."""
    if elevation >= stops[0][0]:
        return stops[0][1]
    for (e0, c0), (e1, c1) in zip(stops, stops[1:]):
        if e1 <= elevation <= e0:
            t = (elevation - e1) / ((e0 - e1) or 1.0)
            return tuple(c1[k] + (c0[k] - c1[k]) * t for k in range(3))
    return stops[-1][1]


def dome_mesh(stops, radius=DOME_RADIUS, segments=32, rings=24, header=None):
    """A sphere around the map's origin, both sides drawn, coloured by elevation: a raw mesh dict for
    alr_build (shader svc, vertex format 0x0B)."""
    data = bytearray()
    index = []
    for r in range(rings + 1):
        el = 90.0 - 180.0 * r / rings
        y = math.sin(math.radians(el)) * radius
        ring_r = math.cos(math.radians(el)) * radius
        c = _gradient(stops, el)
        row = []
        for s in range(segments):
            a = 2 * math.pi * s / segments
            row.append(len(data) // DOME_VERTEX_SIZE)
            data += struct.pack('<3f4B', math.cos(a) * ring_r, y, math.sin(a) * ring_r,
                                int(round(c[2])), int(round(c[1])), int(round(c[0])), 255)
        index.append(row)
    tris = []
    for r in range(rings):
        for s in range(segments):
            a, b_ = index[r][s], index[r][(s + 1) % segments]
            c, d = index[r + 1][s], index[r + 1][(s + 1) % segments]
            for t in ((a, c, b_), (b_, c, d)):
                if len({t[0], t[1], t[2]}) == 3:
                    tris.append(t)
                    tris.append((t[0], t[2], t[1]))          # both sides: the camera is inside
    raw = dict(material=bytes.fromhex(DOME_MATERIAL), format=DOME_FORMAT, vertex_size=DOME_VERTEX_SIZE,
               vertex_bytes=bytes(data), tris=tris)
    if header is not None:
        raw['header'] = header
    return dict(raw=raw)


def _recolour(raw, mesh, stops):
    """Paint a gradient onto a map's own dome mesh (format 0x0B): colour by each vertex's elevation as the game
    places it (node transform applied), keeping the mesh's shape - its uneven triangles give the game's look."""
    data = bytearray(raw['vertex_bytes'])
    size = raw['vertex_size']
    mtx = alr.node_matrix(mesh['nodes'], mesh['node']) if mesh['node'] < len(mesh['nodes']) else None
    for k in range(len(data) // size):
        p = struct.unpack_from('<3f', data, k * size)
        x, y, z = alr.apply(mtx, p) if mtx else p
        r = math.sqrt(x * x + y * y + z * z) or 1.0
        c = _gradient(stops, math.degrees(math.asin(max(-1.0, min(1.0, y / r)))))
        struct.pack_into('<3B', data, k * size + 12, int(round(c[2])), int(round(c[1])), int(round(c[0])))
    raw['vertex_bytes'] = bytes(data)


def rotate_towards(points, target):
    """Rotate points about the origin so their centroid's direction becomes target (a unit vector)."""
    if not points:
        return points
    c = [sum(p[k] for p in points) / len(points) for k in range(3)]
    n = math.sqrt(sum(x * x for x in c)) or 1.0
    a = [x / n for x in c]
    t = target
    k = (a[1] * t[2] - a[2] * t[1], a[2] * t[0] - a[0] * t[2], a[0] * t[1] - a[1] * t[0])
    s = math.sqrt(sum(x * x for x in k))
    cos = max(-1.0, min(1.0, sum(x * y for x, y in zip(a, t))))
    if s < 1e-9:
        if cos > 0:
            return points
        k, s = ((0.0, 0.0, 1.0) if abs(a[2]) < 0.9 else (1.0, 0.0, 0.0)), 0.0     # opposite: half turn
        cos = -1.0
    else:
        k = tuple(x / s for x in k)
    out = []
    for p in points:
        kxp = (k[1] * p[2] - k[2] * p[1], k[2] * p[0] - k[0] * p[2], k[0] * p[1] - k[1] * p[0])
        kdp = sum(x * y for x, y in zip(k, p))
        out.append(tuple(p[i] * cos + kxp[i] * s + k[i] * kdp * (1 - cos) for i in range(3)))
    return out


def _turn_sun(raw, direction):
    """Turn a sun layer (positions already in sky space) so it sits in direction (game space, towards the sun)."""
    data = bytearray(raw['vertex_bytes'])
    size = raw['vertex_size']
    pts = [struct.unpack_from('<3f', data, k * size) for k in range(len(data) // size)]
    for k, p in enumerate(rotate_towards(pts, direction)):
        struct.pack_into('<3f', data, k * size, *p)
    raw['vertex_bytes'] = bytes(data)


def build_sky(b, dome_stops=None, keep_dome=False, clouds='KEEP', cloud_speeds=None, cloud_scale=1.0,
              cloud_texture=None, sun=True, dome_shape='GAME_ORIGINAL', cloud_textures=None, sun_direction=None):
    """Meshes for the sky root, from the game original's sky (bytes b) and the settings.

    dome_stops: [(elevation, (r, g, b))] for a gradient dome (None + keep_dome: the map's own dome).
    dome_shape: 'GAME_ORIGINAL' paints the gradient on the map's own dome mesh (when it has a gradient dome; a picture
      dome falls back to the sphere), 'SPHERE' replaces it with a smooth generated sphere.
    clouds: 'KEEP' (as the map has them), 'CUSTOM' (cloud_speeds = three (x, y) pairs for every layer, or None to
      scale the map's by cloud_scale), 'NONE'.
    cloud_texture: a texture ref ('base', i) / ('new', i) for the cloud colour (slot 0), or None.
    cloud_textures: {slot 0-2: ref} for the cloud colour and the two shape layers (overrides cloud_texture).
    sun: keep the map's sun layer; sun_direction: unit vector (game space) towards the sun to turn it to, or None.
    Returns a model dict for alr_build.rebuild's replace: dict(meshes, nodes, material_unk, extra_node).
    The map's own nodes are kept byte for byte (their flags, 0x34 in the maps, and transforms matter: the
    cloud shell is tilted and lit by its normals); its layers stay on their nodes; the new dome (and anything
    else added) goes on one extra node: identity transform, the map's sky node flags."""
    from . import alr_build                                # local: alr_build imports nothing from here
    h = alr.header(b)
    out = []
    keep = []
    nodes, unk = [], None
    root = h['roots'][SKY_ROOT] if len(h['roots']) > SKY_ROOT else None
    for off, t, size in alr.chain(b, root) if root is not None else []:
        if t == 0x03:
            n = struct.unpack_from('<H', b, off + 8)[0]
            nodes = [bytes(b[off + 16 + 64 * k:off + 16 + 64 * (k + 1)]) for k in range(n)]
        elif t == 0x01:
            unk = struct.unpack_from('<H', b, off + 0x0A)[0]
    flags = struct.unpack_from('<H', nodes[0], 36)[0] if nodes else 0x0004
    painted = False
    extra = len(nodes)
    nodes = nodes + [bytes(alr_build.node_record(flags=flags, node_id=extra))]
    for m in alr.meshes(b, root) if root is not None else []:
        mat = m['materials'][m['material']]
        sh = mat['shader']
        if sh in CLOUD_SHADERS:
            if clouds == 'NONE':
                continue
            rm = alr_build.raw_mesh(b, m, h['resource_offset'], apply_node=False)
            raw = bytearray(rm['raw']['material'])
            if clouds == 'CUSTOM':
                if cloud_speeds is not None:
                    vals = [v for pair in cloud_speeds for v in pair]
                else:
                    vals = [v * cloud_scale for v in struct.unpack_from('<6h', raw, SCROLL_AT)]
                struct.pack_into('<6h', raw, SCROLL_AT, *(int(max(-32768, min(32767, round(v)))) for v in vals))
                over = dict(cloud_textures or {})
                if cloud_texture is not None and 0 not in over:
                    over[0] = cloud_texture
                if over:
                    rm['raw']['tex_override'] = over
            rm['raw']['material'] = bytes(raw)
            keep.append(rm)
        elif _is_sun(mat):
            if sun and sun_direction is not None:
                rm = alr_build.raw_mesh(b, m, h['resource_offset'], apply_node=True)    # into sky space ...
                _turn_sun(rm['raw'], sun_direction)                                   # ... turned to the sun
                rm['node'] = extra
                keep.append(rm)
            elif sun:
                keep.append(alr_build.raw_mesh(b, m, h['resource_offset'], apply_node=False))
        elif keep_dome or dome_stops is None:
            out.append(alr_build.raw_mesh(b, m, h['resource_offset'], apply_node=False))
        elif dome_shape == 'GAME_ORIGINAL' and sh in ('svc', 'svcal'):
            rm = alr_build.raw_mesh(b, m, h['resource_offset'], apply_node=False)
            _recolour(rm['raw'], m, dome_stops)
            out.append(rm)
            painted = True
    if dome_stops is not None and not keep_dome and not painted:
        dome = dome_mesh(dome_stops)
        dome['node'] = extra
        out.insert(0, dome)
    return dict(meshes=out + keep, nodes=nodes, material_unk=unk, extra_node=extra)


# ---------------------------------------------------------------- preview (Blender viewport)

def preview_layers(b):
    """The game original's sky layers for a viewport preview: positions in game space (node transforms applied),
    triangles, UVs (/4096), vertex colours (r, g, b, a bytes), texture indices, kind and cloud speeds.
    kind: 'dome', 'clouds' or 'sun'."""
    h = alr.header(b)
    if len(h['roots']) <= SKY_ROOT:
        return []
    rb = h['resource_offset']
    out = []
    for m in alr.meshes(b, h['roots'][SKY_ROOT]):
        mat = m['materials'][m['material']]
        sh = mat['shader']
        vb = m['vbufs'][m['vbuf']]
        size, fmt = vb['vertex_size'], vb['format']
        base = rb + vb['offset']
        # UV and colour offsets by vertex format (dome 0x0B: colour only; picture 0x09: UV 0x0C, colour 0x10;
        # clouds 0x03: UV 0x10, colour 0x14)
        uv_at, col_at = {0x0B: (None, 0x0C), 0x09: (0x0C, 0x10), 0x03: (0x10, 0x14), 0x01: (0x10, 0x14)}.get(fmt, (None, None))
        mtx = alr.node_matrix(m['nodes'], m['node']) if m['node'] < len(m['nodes']) else None
        pos, uv, col = [], [], []
        for i in range(vb['count']):
            v = base + i * size
            p = struct.unpack_from('<3f', b, v)
            pos.append(alr.apply(mtx, p) if mtx else p)
            uv.append(tuple(x / 4096 for x in struct.unpack_from('<2h', b, v + uv_at)) if uv_at is not None else (0.0, 0.0))
            col.append(tuple(b[v + col_at + k] for k in (2, 1, 0, 3)) if col_at is not None else (255, 255, 255, 255))
        kind = 'clouds' if sh in CLOUD_SHADERS else 'sun' if _is_sun(mat) else 'dome'
        out.append(dict(kind=kind, shader=sh, pos=pos, uv=uv, col=col,
                        tris=alr.triangles_from_indices(m['indices'], m['primitive']),
                        textures=[t for t in mat['textures']],
                        speeds=struct.unpack_from('<6h', mat['raw'], SCROLL_AT) if kind == 'clouds' else None))
    return out
