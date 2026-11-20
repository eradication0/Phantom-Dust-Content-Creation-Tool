# Phantom Dust stage formats

Phantom Dust (2017 UWP release, `PDUWP.exe`). Paths are relative to the game's `Assets\Data`.
Function names are Ghidra addresses in `PDUWP.exe` (image base `0x140000000`).

Status words: **confirmed** = changed in a test file and seen in game. **read from code** = taken from the
decompiled loader, consistent across every map, not tested on its own. **likely** / **unknown** as stated.

## Files that make a map

| File | What it holds |
|---|---|
| `Map\stNN.alr` | Visual stage: meshes, materials, textures, nodes |
| `Map\stNN.dat` | Collision, spawn/orb layouts, object table and more (below) |
| `Map\stNNcam.alr` | Intro camera keyframes (likely) |
| `com\stNN\comdata.cad` | AI navigation mesh (likely) |

Stage names are in `setup\stageset\stageset_en.dat`, e.g. st04 = Panorama Earthquake (`st04Panorama-earth`).
Maps share files across lighting variants only by copy: st04 / st14 / st24 are separate files.
`st00` and `st09_0x` are story/event stages with a different `.dat` header.

## `stNN.dat` header (read from code: `FUN_140203720`)

Magic `ST00`, then u32 values. Offsets are from the start of the file; `FFFFFFFF` = absent.
Section offsets point just past a 4-character tag (e.g. `NM00`).

| Offset | Meaning |
|---|---|
| `0x04 + 4*i` (i = 0..10) | Layout slot i. The match uses slot `layout + 1`, falling back to slot 0 |
| `0x30 + 4*i` (i = 0..10) | Per-layout value (u16 used) |
| `0x5C` | `NM00` object names (e.g. `st04_kaidanA_` = stairs) |
| `0x60` | Object count (a count, not an offset) |
| `0x64` .. `0x84` | `OC00`, `OC01`, `OC02`, `OE00`, `OE01`, `OE02`, `OA00`, `OA01`, `OA02` (unknown) |
| `0x90` | `OB00` object table, 0x38-byte entries; the first 3 u32 are root indices into `stNN.alr` |
| `0x94` | **Collision** (below) |
| `0x98` | `EF00` (unknown, likely effects) |
| `0x9C` | `SP00` (unknown) |
| `0xA0` .. `0xBC` | `MD00`, then the `CP00` spawn layouts |
| `0xD0 + 4*v` | Lighting script (`mapLight`, below) for variant v; unused variants fall back to `0xD0` |
| `0xF4` | Light animation block (an `.alr`-style chunk `0x0E` of `0x05` animation chunks) |
| `0x138` | File size (true in every map) |

Online, the host picks the layout as `rand() % count` and sends it to the other players.

## Spawns and orbs: `CP00` sections (confirmed)

Each map has 4-6 `CP00` sections, one per layout, usually with 4 entries each. Some layouts are exact
duplicates (st02: layout 0 = 3). Exceptions: st01 has 2 entries per layout, st06/16/26 have one layout
with a single entry, and st09 (Sein) has one layout of 8 entries.

```
"CP00"
u32  (size << 16) | count        e.g. 0x01400004 = 4 entries of 0x50
count x entry (0x50 bytes):
  +0x00 f32 x, y, z              spawn position, y up                     confirmed
  +0x0C f32 yaw                  facing, radians                          confirmed
  +0x10 u32 0x80100003
  +0x14 3 x f32 x, y, z          that player's 3 orb points               confirmed
  +0x38 u32 0xFFFFFFFF
  +0x3C u32 x4                   usually 128, 3, 24, 0                    unknown
  +0x4C u32 flags                0x000b641c / 0x000b664c                  unknown
```

Orbs normally lie in front of the spawn's facing, about 50 units apart in a row.

How it was confirmed (st04): stacking orbs 2-3 onto orb 1 put all orbs in one spot; raising every spawn
250 units made players drop from the sky; adding pi to the yaw put the orb row behind the player.

## Collision: header `0x94` (confirmed)

Read from `FUN_1401d3d70`, `FUN_1401d2c20`, `FUN_1401d3040`, `FUN_1401d4070`. Confirmed in game: lowering
every vertex, centre and bounding box by 15 left players standing sunk into the visible floor.

A chain of records, ended by a record whose first byte is `0xFF`:

```
u8  type        surface type 00-20 (below); on vertex lists 33 or 35, unread
u8  kind        8 = vertex list, 3 = triangle chunk (1 also handled, not seen in maps)
u8  flags       0x03 in every map (bit 0: registered in the spatial tree)
u8  0xFF
u32 size        bytes after this 12-byte header; next record at +size+0x0C
u32 0
```

**Kind 8, vertex list:** `size / 12` x f32 xyz. Every map has exactly one.

**Kind 3, triangle chunk** (`size = 0x30 + 20 * n`):

```
+0x0C f32 x3  centre
+0x18 f32     radius
+0x1C f32 x3  bounding box min
+0x28 f32 x3  bounding box max
+0x34 u16     triangle count n
+0x38 u32     which vertex list (index among kind-8 records)
+0x3C n x 20 bytes:
      u16 a, b, c        vertex indices
      u16 attr           unread; 0, or 52 on every triangle in st05 (stale exporter memory)
      f32 x3 normal      normalize((b - a) x (c - a))
```

Chunks are small (1-11 triangles). The game builds its spatial grid (30 x 20 x 30 cells) and tree at load
time from these records, so a writer only needs the records.

**Chunk centre and radius:** the centre is the smallest sphere enclosing the chunk's vertices (matches every
chunk in st04 and st32 to 0.003); the radius is the farthest vertex from that centre; the bounding box is the
exact min/max of the vertices.

**Writing collision (confirmed):** `pdstage/collision_build.py` builds the block from any triangles. Rebuilding
each of the 21 maps from its own triangles gives back the same triangles, surface types and normals (chunking
differs, which the game handles). In game, st04 with its collision fully rebuilt by the writer plus a 40 x 40 x 25
box at every first orb point played normally, and the boxes were solid.

**Replacing collision without resizing (confirmed):** append the new block (records plus the `0xFF` end
byte) at the end of the file, set header `0x94` to its offset and `0x138` to the new file size. The old block
stays in place unused, so no other offset changes. Tested on st04 with a lowered copy appended: players sank
into the floor, and the file grew by 111 KB with no load problems. (Growing the block in place would instead
shift `EF00`, `SP00`, `MD00`, the `CP00` layouts and about half the object-table offsets.)

Every battle map parses with no out-of-range index, every normal unit length and matching its winding
(about 1,200 to 9,300 triangles per map).

**Surface types are one global material list** (tested in game 2026-11-18 on a pad-per-number test map,
`tools/surface_test_map.py`). Valid numbers are `00`-`20`: the footstep table at `PDUWP.exe 0x1402f6270` holds two
s32 sound ids per number (the second column is used for some characters) for 33 numbers, and the code skips
anything from `0x21` up. Each map just uses the numbers it needs.

| No. | In game | No. | In game |
|---|---|---|---|
| 01 | silent: no steps, landing or craters | 12 | silent wall: nothing |
| 02 | metal steps, weak metal landing | 14 | **jump-through wall** (below) |
| 04, 06 | plastic steps, metal landing | 16 | sticky steps, no landing sound, no craters |
| 05 | metal steps, metal landing | 18 | ceramic steps |
| 07 | stone steps, stone landing | 19 | rattling steps |
| 08 | stone steps, strong landing (most common) | 1A | light steps |
| 09 | stone steps, crackling landing | 1B | metal grate steps |
| 0A | wood steps, crackling landing | 1C | light wood steps |
| 0B | pebble steps, no landing sound, no craters | 1D | grass steps |
| 0D | water steps, glass landing | 1E | dirt steps |
| 10 | **restricted area wall**: blob effect and warning sound (the maps' invisible edges) | 1F | **camera wall** (below) |
| | | 20 | dampened wood steps |

| 00 | solid, no sounds, no craters | 11 | **respawn on touch** |
| 03 | same as 02 (metal steps, craters) | 17 | cloth steps, landing sound, no craters |
| 0C | each step a small explosion, then a looping high ringing | 0E | no steps, water landing |
| 0F | no steps, generic landing | 13 | solid, silent, no craters |
| 15 | hollow pipe steps, no landing sound, craters | | |

18-1E and 20 have a strong landing and craters; so do 02, 04-0A and 0D. All 33 numbers tested. The add-on's dropdown offers the usable ones (all with craters, cloth, and 10 / 14 / 11), generic first. The game also skips
`1F` records in two collision loops (`0x140163a4e`, `0x140164846`). The landing-sound and crater lookups are not
found yet.

**Selective walls (2026-11-20)**, from Tinkerer_Red's research (Xbox, console-measured; `PHANTOM_DUST_FORMATS_REFERENCE.md`)
and retested on PC with `tools/surface_diff_test_map.py`:

| Type | Players | Camera | Attacks | The game uses it for |
|---|---|---|---|---|
| 12 | stopped | pass | pass | railings and fences |
| 14 | stopped on the ground; a jump passes near its top (solid while rising and falling) | pass | pass | the edge of Edgar's Dream's walkway (st01 only) |
| 1F | pass | **stopped** | pass | camera-only copies of railings, sheets above the edge walls |

Used as floors (the game never does): players cannot land on 14 and fall through 1F, then get respawned by the fall
rule. That was the earlier "fall-out" reading. PC filters: camera `0x140164060` / `0x140164531`
(`sub al,12h; test al,0FDh` skips 12 and 14), movement `0x140255404` (14) / `0x140255425` (1F), AI line of sight
`0x140164240` (every type blocks it except 10). 0C is a game bug (a looping step sound that is never stopped fills the
sound pool). Craters come from any attack hit or a landing from more than 80 units, and their size comes from the
type; on st08 types 04 and 18 make none. `addon/.../surfaces.py` has the names (shown in the add-on's surface dropdown) and how much each map
uses each number.

## `com\stNN\comdata*.cad`: AI navigation data (likely; on hold)

On hold: custom maps are not expected to need bots.

The game loads `com\st%02d\comdata%d.cad` and `camdata.cam`. Two formats exist:

**Battle maps: `comdataN.cad`, not decoded.** Always exactly 674,312 bytes. Starts with a u32 count
(st04: 340) followed by xyz points at floor heights; the rest is unknown. Maps have 1-3 of these
(st04: `comdata0`-`2`; `comdata0` and `comdata1` are identical). Maps 12-26 mostly have none
(only st24 has one), so those variants may share data or run without it.

**Battle-map layout (first read, 2026-11-18; from st02-st08 and st24, not confirmed in game).** Sections sit at
fixed offsets in every file; unused space is zero. One file per stage variant (`comdata0/1/2`; st04's 0 and 1 are
identical, 2 differs and matches st24's only file). The user's report: on a custom map in an existing slot the bot
walks into walls, as expected while the game original's file stays in use.

| Offset | Contents | Evidence |
|---|---|---|
| `0x0000` | u32 point count, then f32 xyz points (room for 1000): **corners of flat rectangles**, 4 per rectangle, all four at one height (st04: 340 points = 85 rectangles at heights like 117.9 / 57.4) | every file |
| `0x2EE4` | u32 rectangle count, then 0x54-byte entries per rectangle: small indices and `FFFFFFFF` runs (likely neighbours / doorway lists) | size = count x 0x54 |
| `0x58E8` | u32 count, then 0x2C-byte entries: two xyz points (a shared edge), two rectangle numbers, u32 0, f32 length, u32 0: **doorways between rectangles** | st04 comdata2 |
| `0xB0EC` | u32 count, then 0x18-byte entries: xyz, u32, u32, f32 (special spots with a rectangle number?) | 3 in st04 comdata2 |
| `0xB3C0` | u32 count, then 0x10-byte entries: u32 + xyz (typed points, upper level) | |
| `0xB5A4` - end | 627,812 bytes: increasing u32 runs separated by `FFFFFFFF` (likely **precomputed routes** between rectangles) | |

Next step: find the loader in PDUWP.exe (`FindStrRefs.java` on `comdata%d.cad`, then decompile its callers) to name
the fields and the route table before writing a generator. `camdata.cam` (776 bytes) likely belongs with it.

**st01 only: `comdata.cad`, small format:**

```
u32 n_verts, u32 n_quads_a, u32 n_quads_b
n_verts x f32 xyz
(n_quads_a + n_quads_b) x u32[4]     quad vertex indices
```

Not tested in game.

`camdata.cam` (776 bytes in every map) is not decoded.

## `.alr` containers

Same container as the original Xbox release (see [desert-breeze-dust](https://github.com/ZacheerKour/desert-breeze-dust),
`docs/FORMATS.md`): header `0x11`, root offsets at `0x20`, each root a chain of `[u32 type][u32 size]` records
ending at type 0. In `stNN.alr`, root 0 is the main stage mesh (type 2 meshes, type 3 node list with 64-byte
entries from record offset +16). Many roots are empty placeholders, and type 19 records are all zero.
No spawn or orb data was found in the `.alr`.

### Reading models and textures (confirmed by import)

Following the Phantom Dust wiki ALR page and Esper-RE `alr.h`, checked on st04 (`pdstage/alr.py`):
- Header: resource buffer offset at `0x0C` and size at `0x14` add up to the file size; the buffer starts on a
  `0x1000` boundary. Version is `0x52` in the 2017 release.
- `0x15` texture table: names decode with the base-40 text encoding (`st04_c_kabe3`, `st04_n_...`); sizes match
  format and mip count for 63 of 64 entries. st04 uses BC1, BC3 and uncompressed BGRA (`0x86`).
  **Texture data is linear** in the 2017 release (not Xbox-swizzled).
- `0x02` meshes: index data starts at `+0x68`; every index is within its `0x16` vertex buffer. Primitive 5 =
  triangle list, 6 = strip. Node transforms (`0x03`) composed as T * Rz * Ry * Rx * S, then parents.
- Imported into Blender, the stage, background and sky render correctly textured and line up with the
  collision and spawns.
- **Game space is left-handed** (Direct3D): Blender = (x, z, y) x scale, a mirror. The earlier
  Blender = (x, -z, y) (a rotation) showed every map mirrored in Blender, and maps built in Blender came out
  mirrored in game (reported). Proof from the files: the game's sign textures (Dawn City `kanban_f`, Lost Palace
  `st03_j_shop`, Panorama `st04_c_pop1`, with readable text) are mapped so their text runs left to right only in a
  left-handed space (kanban_f: 98 of 98 wall triangles; shop fronts 874 to 210). The mirror reverses triangle
  winding, so every conversion swaps two corners; yaw changes sign.

### Writing models (confirmed in game)

`pdstage/alr_build.py` rebuilds an `.alr` from its parts: header (root offsets), texture table (new entries
appended), each root's chunk chain (replaced roots rebuilt, others copied), padding to `0x1000`, then the base
resource buffer unchanged with new vertex/texture data appended. With no changes it reproduces all 22 map
files byte for byte.

- New meshes use vertex format `0x01` (shader `sd`, 0x18 bytes): position (3 floats), **packed normal** at
  `0x0C` (11/11/10 bits signed: x * 1023, y * 1023, z * 511), UV int16 / 4096 at `0x10`, and a **baked vertex
  colour** at `0x14` (bytes B, G, R, A). The colour is the stage's baked lighting: the game multiplies the texture
  by it. Format `0x03` (`sbts`) has the same colour at `0x14`, plus tangent data at `0x18`/`0x1C`.
- Material, vertex-buffer and mesh fields not understood are copied from an existing `sd` mesh.
- Mesh header `+0x08` centre and `+0x14` radius: smallest enclosing sphere; `+0x18`/`+0x24` bounding box.
- New textures: uncompressed BGRA (`0x86`), power of two, full mip chain, 12-character base-40 name.
- Confirmed in game on st04: the stage rebuilt from its own meshes with colours (and the `sshadow*` shadow
  meshes carried over) looks like the original; without the colours it is uniformly too bright. A stage exported
  from Blender with an added textured, vertex-lit cube (and collider) shows correctly.

### Shadow mesh (confirmed in game)

Each stage model has a mesh with shader `sshadowch` (vertex format `0x07`: position + packed normal, 0x10 bytes),
and st04 also a small `sshadowc` one (format `0x10`, position only). In st04 the `sshadowch` mesh is mostly
walls, pillars and stairs between heights 50 and 160, a third of it coinciding with visible triangles: it behaves
like **shadow volumes** of the stage.

Tested on st04:
- Stage without any shadow mesh: characters cast **no shadow**.
- Stage rebuilt with the original shadow meshes carried over: character shadows as normal.
- Shadow mesh = a copy of every stage triangle: surfaces turn dark, patchy and partly see-through.
- Shadow mesh = a **1-unit closed box 1000 units below the stage**: clean surfaces and character shadows work.
  The writer uses this by default; the stage then casts no shadows of its own.

## Stage materials and shaders (highlight confirmed in game; normal and reflection maps pending)

Read from the game's compiled shaders (`SD`, `SBTS`, `SDREFS`, `SBTSREFS` `*_vs.cso` / `*_ps.cso` next to `PDUWP.exe`;
they keep their constant names: `tools/dump_cso.py` prints them) and from every material entry of st02-st08, st13.
`pdstage/alr_build.material_record` writes these; `pd_material.py` is the Blender side (PD Stage Shader).

**What the stage shaders compute** (per pixel; `tex` = diffuse texture, `vc` = vertex colour):

| Shader | Colour |
|---|---|
| `sd` | `saturate(tex * (sun * max(N.L, 0) + hemisphere ambient) * vc.rgb)` + `cSPECULAR.rgb * (N.H)^cSPECULAR.w * vc.a * view term` |
| `sbts` | normal-mapped sun + ambient from the game's lights, times `vc.r` (only that channel: baked shade); highlight also times the normal map's alpha |
| `sdrefs` | `sd` + reflection map (sphere-mapped with `cTMAT`) `* its alpha * vc.a * view term * light * 4` |
| `sbtsrefs` | `sbts` + reflection |

The highlight is added after the clamp, so a broad grey highlight on every vertex (what v1.0 wrote, copied
from the game original's material: grey 0.5, power 20) washes sunlit walls out to white.
There are no roughness, metalness or emission inputs in these shaders.

**Material entry (0x4C bytes, in the `0x01` chunk):**

| Offset | Meaning | Evidence |
|---|---|---|
| `0x00` | shader name, two base-40 words (`sbtsrefs` needs both) | |
| `0x0C` | flags: `0x01`, `0x08` always; **`0x04` = highlight on** (set exactly when `0x34` is non-zero); **`0x20` = normal map** (all `sbts*`) | every map |
| `0x0D` | **`0x04` = reflection map** (all `*refs`); `0x40` on some fences/billboards (unknown); `0x01` on Spiral Highway's road markings, whose DXT1 texture is 73% transparent (likely alpha test) | every map |
| `0x10` | vertex format (`0x01` / `0x03`); `0x11` usually `0x10`; `0x12` material index | |
| `0x16` | u16 texture-slot roles, a nibble per slot: 1 diffuse, 2 normal map, 4 reflection map (`sd 0x0001`, `sbts 0x0021`, `sdrefs 0x0041`, `sbtsrefs 0x0421`) | desert-breeze-dust; every map |
| `0x18` | 4 x u16 texture indices (unused slots hold any texture) | |
| `0x30` | `00 00 00 FF` always | |
| `0x34` | **highlight: B, G, R, power** (D3DCOLOR order). Game range: black (a third of `sd` materials), grey `19`-`7F`, power 2-80 (the shader clamps to 128) | every map |
| `0x40`-`0x4B` | small values on some `sbts`/`*refs` (`0x32`, `0x64`, `0x0A`...): unknown | |

**Vertex formats used by stage shaders:**

| Format | Size | Layout |
|---|---|---|
| `0x01` (`sd`, `sdrefs`) | `0x18` | f32 pos[3], packed normal, s16 uv[2] / 4096, BGRA colour |
| `0x03` (`sbts`, `sbtsrefs`) | `0x20` | the same, then packed **tangent** at `0x18` and **binormal** at `0x1C` (same 11/11/10 packing as the normal) |

The vertex colour's **alpha is the shine mask**: it scales the highlight and the reflection, nothing else.
Vertex-buffer entries (`0x16` chunk) keep the Xbox attribute mask at `+0x04`: `0x00CF` (format 1), `0x30CF` (format 3).

Tangents in the game's files: unit length, orthogonal, binormal = +V of the UV map as Blender shows it (game V
flipped), tangent = normal x binormal (always one handedness; on about two thirds of triangles that is +U). The
shader takes them as stored (light = (L.T, L.B, L.N) against the normal map's RGB), so the writer stores Blender's
own tangent and bitangent: OpenGL-style normal maps (green up) work, mirrored UVs included.

**Confirmed in game (2026-11-18, the user's st03 export, only `0x34` and the `0x04` flag changed):**
- `0x34` = 0: the washed-out sunlit walls looked like normal lit walls (the cause of the glow).
- `0x34` = `00 00 FF 50` (B, G, R, power 80): sunlit faces shone pure red, so the byte order is B, G, R. Whole flat
  faces lit evenly, fully red or not at all: the highlight is per vertex with a fixed half-vector (`cDL_SVEC`), so the
  power only selects which face angles shine. Full colour (255) is far stronger than anything in the game's files
  (at most `0x7F`).

## Light maps and shadow maps (read from the files and the shaders; lbts confirmed in game on a battle stage)

### Light maps: shader `lbts` (underground hub; works on battle stages)

The game has real light maps, used by the underground hub (`st09_01.alr`, 14 meshes): shader `lbts` (and
`lbtsrefs`), vertex format `0x1F` (0x20 bytes, attribute mask `0x0010304F`):
`pos (3 f32) | packed normal | UV0 (2 x u16 / 4096) | packed tangent | packed binormal | UV1 (2 x u16 / 4096)`,
the same as `sbts` (format 3) without the vertex colour and with a second UV map. No vertex colour, so no baked
vertex light.

Material texture slots (`+0x18`): slot 0 diffuse (on UV0), **slot 1 light map** (on UV1), slot 2 normal map (on
UV0; the hub uses a 4x4 flat normal `ug_h_normal` where there is none), slot 3 sphere map (`lbtsrefs`). Nibble mask
at `+0x16` = `0x0261` (slot 0 = 1, slot 1 = 6, slot 2 = 2); `+0x12` = `0x26` (dbts: 0).

In the hub all lbts meshes share one vertex buffer and **one 512 x 512 DXT5 light map for the whole room**
(`ug_1_light1`): UV1 is an atlas inside 0-1, UV0 tiles freely (0-16, the floor texture repeats 16 times). The light
map is dark (mean RGB about 10/255) with alpha almost all 0.

`LBTS_ps` (per pixel; `tex` diffuse, `lm` light map, `n` normal map):
`colour = tex * (cAMBIENT + lm.rgb) + lm.rgb * lm.a + point-light highlight * lm.rgb`.
No sun term: the light map is the whole stage light, the map's ambient colour is added on top, and the light
map's alpha adds its colour once more without the texture (glow; keep it 0). Each material names its own
light-map texture, so a map could also use one light map per mesh.

Tested in game (`tools/lightmap_test_map.py`, over Lost Palace; four checker pads, UV0 tiling 8 x 8): `lbts` loads
and draws on a battle stage, the tiled texture stays sharp and the light map lies over it on UV1, exactly as the
formula says: a white light map makes the pad much brighter than a normal `sd` pad (texture x (ambient + 1)), a
coloured one tints it, and the hub's light map shows its glow (its alpha adds the light map's colour on top, like
emission). So a light map for a normal-looking surface holds about `light - ambient`, alpha 0.

The light map's **blue channel also decides where character shadows show**. `LBTS_ps` writes its output alpha
from it (`alpha = 2 * (tex.a * 2 - 1.5) * (lm.b * c0.z + c0.w)`, also used for the alpha test), and the shadow pass
darkens by that alpha. In game: on the red and green squares of the test light map (blue 0) the player's
real-time shadow disappeared; on the blue square and the white areas it showed. So where the baked light is dark
(or has no blue, like orange light) characters cast no shadow: in baked shadow that is what you want; strongly
orange or red light would hide them.

### Shadow map overlay: Twilight Lane (`st07`, `st17`)

Lane keeps its normal stage meshes (`sd`/`sbts` with vertex light) and adds **119 extra `sdal` meshes** (format
`0x01`, the plain `sd` vertex) that repeat the stage surfaces they darken, all using one 512 x 512 DXT5 texture
`s7_yogoshi2`: colour almost black (mean RGB 0, 0, 16: a dark blue), **alpha = shadow strength**, laid out as one
atlas for the whole map (the overlay UVs sit inside 0-1, the stage's own UVs tile up to 16). `SDAL_ps` outputs the
texture's alpha, so the overlay is blended over the stage: it can only darken, towards that dark blue. Every
material in the map also names `s7_yogoshi2` in its unused slots 2-3 (filler). Four `isyogore` meshes (dirt
decals with an irradiance cube map) are separate.

## Sky (root 2 of `stNN.alr`) (dome colours and cloud speeds confirmed in game)

Every map's sky is the same kinds of layer (`pdstage/sky_build.py` reads and builds them):

| Layer | Shader / vertex format | What it does |
|---|---|---|
| Dome | `svc` / `0x0B` (16 bytes: f32 pos[3], BGRA colour) | Unlit: `SVC_ps` outputs the vertex colour as is. **Confirmed**: a green / orange / blue gradient written into st04's and st05's dome showed exactly so. Some maps use `sc` / `0x09` (pos, UV, colour) with a sky picture instead (st02, st13) |
| Clouds | `sbtscloud3` / `0x03` | Slot 0 = cloud colour (alpha = cover), slot 1 = cloud normal map sampled twice (shape layers that cut the outline). Lit by the map's light colours. Material `0x3C`-`0x47` = three (x, y) s16 scroll speeds: colour, shape A, shape B (offsets `c90.xy`, `c90.zw`, `c91.xy` in `SBTSCLOUD3_vs`). **Confirmed**: all six 0 freezes every layer; shape layers at 0 stand still while the colour layer moves. Very large values (2000) looked slower: likely wrap-around. Game range about -160 to 250 (st08: up to 800) |
| Sun | `sc` / `scal` / `svcal` with `0x10` set at material `0x0C` | Sun or glow picture |

Sein has 8 cloud layers. The add-on's custom sky carries the map's cloud and sun meshes over **on their own
nodes** (the sky nodes have flags `0x34` and transforms, e.g. a 15° tilt; baking the transform into the vertices and
dropping the nodes made the clouds look big and soft in game), with speeds / texture changed in their material.
The gradient dome is painted onto the map's own dome mesh or is a generated sphere (radius 12000, both sides).

In-game findings (user, 2026-11-18, Dawn City): clouds rebuilt with the original nodes keep the game's look, and
their scrolling follows the uneven cloud mesh (part of the game's charm). A painted gradient, on a sphere or on the
map's own dome, looked too smooth / lacking detail compared with the original: the maps' dome colours carry
detail (st05: 23 distinct colours including a sun glow) that a 4-colour gradient loses. Paused there; ideas: keep
the map's colours and tint / shift them, or more gradient stops.

## Objects: props and breakables (confirmed in game)

Read from `FUN_140203720` (object table) and `FUN_140203dc0` (creates placed objects), with names from Esper-RE
`st00.h`. New objects written by `pdstage/objects_build.py` appear, block players and break in game.

- **`NM00`** (header `0x5C`, count at `0x60`): object names, NUL-terminated (`st04_kaidanA_` = stairs).
- **`OB00`** (header `0x90`): one `0x38`-byte entry per object:
  `u32 model[3]` (`.alr` root index for the **intact**, **broken** and **debris** states, `FFFFFFFF` = none),
  then 9 file offsets: `[6]` = the object's own **collision chain** (same record format as the stage collision,
  in object-local space), `[9]` = its **effect block** (a small `EF00` table, e.g. a break burst); the others are
  unused in maps. The last two u32 are uninitialised (`cdcdcdcd`) except in the first entry.
- **Placements** (header `0x04 + 4*slot`, counts at `0x30 + 4*slot`, section tags `PS00`/`PS01`): `0x24`-byte
  entries `s32 object, u8 category, u8 type, u8, u8, u32 0, f32 pos[3], f32 rot[3]`. A match uses slot
  `layout + 1`, else slot 0. Setting the counts to 0 removes every placed object (confirmed).
- **category / type pick the object's class** through the factory table at `0x1402dc4f0`. Category 2 is the
  destructible family: 1 `Rep01` (breaks, pieces scatter: boxes, chairs, handrails), 2 (cones, barricades),
  3 `Rep03` (crumbles: desks, benches, fences), 7/8 breakable walls, 12/13 falling ceiling pieces, 18 breaks when
  touched (glass railings), 48 crumbling pillars, and more. Category 4: 15 `ReadLim` ("genkai"/limit), **16 `Jump`**
  (jump pads). Category 1: simple hittable props (type 4: lights). Category 3: hub-world doors and chairs.
- **Object models** are small local-space `.alr` roots. The game reads **four per-node values** (bytes `0x30-0x3F`
  of each 64-byte node, as floats) when an object breaks:
  - broken models: each piece on its own node with `(3, 0, 0, 0)`. Tested: a broken model made of two such
    pieces breaks into 2 in game; a single node with zeros makes the object vanish.
  - debris roots: `(2, 2)` (boxes) made new debris disappear after breaking; zeros left it lying there.
  - intact roots: zeros, or `(0, 3)` on desks and lockers (meaning not yet known).
  Original nodes use flags `0x0004`.
- **Read from the code** (`pdStageObjAHitCrash`, `pdStageObjARoll`, `FUN_1401ec350`/`FUN_1401ec800`):
  - **Hits to break** = intact root node value 3 (object field `+0x4e`, minimum 1). Each hit lowers it; the hit that
    finds it below 2 breaks the object. Confirmed in game (3 hits).
  - **Damage on contact** = second value of the current model's root node: passed to the player when a moving
    broken/debris object touches them (only if the value is non-zero). Not yet seen in game (debris barely moves).
  - Breaking spawns the object's effect entries of kind 2 (its `EF00` effect block) at the hit, then launches the
    next state's model as a physics body: speed = sqrt(1200 / max(mass, 200)) along the hit direction, plus a small
    random upward kick, **capped at 1.5 units per frame**; mass comes from the model. A per-object scale exists in
    the code but nothing in the files sets it. So debris speed/distance is fixed by the game.
  - Object table offset slots per state (intact, broken, debris): `[3..5]` animation (`OA` sections, `.alr` 0x05
    chunks; e.g. Spiral Highway's collapsing bridges), `[6..8]` collision (`OC`), `[9..11]` effects (`OE`).

### Object animations and variants

- Object table `[3..5]` (per state) point at **animations** (tags `OA00`, `OA01`... precede them): a chain of
  node blocks ended by `u32 0, u32 8`. Block: `u32 5, u32 block size, f32 last frame, u16 node, u16 8,
  u32 translation keys, u32 rotation keys, f32 0, u16 0, u16 16`, then translation keys `f32 frame, x, y, z`
  (the node's position in the object's space) and rotation keys `u16 frame, i16 x, y, z` (unit quaternion
  * 32767, w = +sqrt(1 - ...)). The iron roads have a block per piece (nodes 1-12, 90 keys), the container one
  for node 0 (269 / 220 keys). `pdstage/anim_build.py` reads and writes them byte-exact. Storm Refinery's container (2-6, broken state)
  and Spiral Highway's iron roads (2-26) have them; their classes (`Mvan`) need one: exported without it the
  game crashes on load. The add-on carries them over raw (`pd_object_anims`) and leaves such an object out if
  it has none.
- Placement slots: slot 0 is every layout's fallback, slot n is layout n - 1's own table. 14 maps have a slot 2
  (their second object layout: jump pads on or off, bridges already broken); Panorama Boss only has slot 3;
  Lane, Sein and Edgar's Dream only slot 0. Import offers slot 2 as "variant 2".
- Effect kinds 10/13 place a model from `MD00` (u16 at entry `0x28` = slot). Storm Refinery's animated sea is
  slot 10 (root 63, shader `vkwater`, no `.ala`), placed by a kind 13 entry: exported over another map it
  pointed at that map's slot 10. The add-on now copies such models (meshes, nodes, textures as stored) into the
  new `.alr`, gives them a free slot 0-19 in a rebuilt `MD00` (appended, header `0xA0` repointed: `MD00`, u32
  names size, u32 animation names size, u32 80, the names, then 80 `(root, animation)` pairs) and repoints the
  effect. Models with a `.ala` animation still can't be moved.
- Damage: intact root value 2 when the object has no debris model, else debris root value 2 (debris value 1 =
  2: the debris goes away). Broken roots are all zero.
- Imported effect entries of kinds other than 2, 22 and 24 (sounds, effect models, glow, stage parameters) index
  their home map's own lists: exported over another map they are left out (they can crash it).
- New textures are written DXT1 (`0x0C`, opaque) or DXT5 (`0x0F`, with alpha), like the game's own: a Storm
  Refinery import exported over Lost Palace made a 67 MB `.alr` with plain BGRA textures.

### Broken pieces: break, stay and the piece's own children (read from the files and the exe)

- A broken model's **pieces are the children of its root node** (parent 0). Each piece usually has one child node
  of its own holding its `sshadow` shadow mesh (sometimes extra visible detail); children move with their piece.
  Node translations are all zero in the game's files: the meshes are in object space.
- **Node `+0x2C` marker `0x4B085FC0` = the piece stays** where it is and gets no physics (Lost Palace `st03_bridgeA`
  piece 15 with its child 16, `st03_bridgeE` piece 7; also Spiral Highway's car and walls). `0xC3500000` also
  skips physics (rare). Every other node has `FFFFFFFF`.
- A **piece's first value** (2, 3 or 4 in the game's files, 0 in Sein and Edgar's Dream) is passed to
  `pdStageObjRollBase` vtable `+0x40` (`0x1401f7060`) and stored at `+0xF8`; non-zero adds the piece to the
  `pdStageColPtr_StObjAtck` list, so it hurts players while it moves fast. It does not change how it flies.
- Older add-on exports wrote every node (shadow children included) as its own piece with `(3, 0, 0, 0)` and no
  marker: pieces meant to stay flew off, and every shadow mesh became a separate light physics body (the fastest
  ones, from the mass rule above), most likely the scattering seen on Lost Palace's bridge pillars.
- **Mass** (`FUN_1401f7dd0`): each flying piece is a body made from **one mesh record of its node**: mass = the
  volume of that record's box (`+0x18` min, `+0x24` max, game units), and the same box (shrunk 15% per side along
  axes longer than 5; axes under 1 become 1) is its physics shape. Lost Palace: bridge A pieces 17000-60000, bridge
  pillar pieces 3500-7600 (launch speed 0.4-0.6). A piece whose model was split into several meshes (one per
  material) gets the box of only one of them: lighter, smaller and much faster. The add-on writes the whole piece's
  box on every mesh of the piece, resized to the Mass setting if one is set.
- **Why the pillars break with the bridges: contact, checked along the object's up axis** (confirmed in game:
  raising the bridge stops it, even with its pieces falling on the pillars). Classes with `Ver` / `VerU` parts test
  another object that breaks (`FUN_1401da920` / `FUN_1401dad10`, both via `FUN_1401fe590`): for every chunk of their
  own collision (the `.dat` collision record's bounding sphere, `+0x0C` centre, `+0x18` radius) a segment of
  length radius + 1 game unit is cast along the object's down axis (`Ver`, from the centre) or up axis (`VerU`,
  through the centre both ways), and tested against the other object's collision chunks. If it touches, the object
  reacts: `Ver` (Rep01-04: boxes, desks...) falls when what it stands on breaks; `VerU` (Rep28: Lost Palace bridge
  pillars) breaks when what rests on it breaks. Nothing in the placement links them: only the colliders' positions.
- Intact roots: value 3 = hits (above); some have value 4 = 1 (Spiral Highway's car, Light Palace gift box),
  meaning unknown. The add-on keeps unknown root values from an imported object (`pd_root_values`).
- The add-on names parts by prefix: `collider_`, `collider_broken_`, `collider_debris_` (collision per state,
  `[6..8]`), `break_` / `stay_` (pieces), `debris_`. The objects' own effect tables (`[9..11]`, `EF00`, u16 count,
  u16 size, then `0x5C`-byte entries) are carried over raw when exporting over the same map.

Types the maps use, by class: 1-15 car (Brk, Hit, Hwcrms; pieces never fly), 2-4 Light Palace bridges X/Y (+Hitif),
2-6 / 2-26 animated (Mvan, Col: Storm Refinery container, Spiral Highway iron roads), 2-17 gift box (Roll, Tch),
2-23 Lost Palace bridges A/B/C (Crm, CrmF), 2-28 bridge pillars (VerU, Pl, Crm), 2-53 Dawn City flying sign (Brk,
Crm, no Hit), 2-54 Dawn City rubble, signs and track (Fltif only), 2-58 Sein bridges (FallCrm), 2-65 to 2-73 Edgar's
Dream stairs and walls (Brk only), 2-74 Edgar's Dream rubble (like Rep01).

### Jump pads and falling out (confirmed in game)

- **Jump pads** (category 4, type 16, class `pdStageObjJump`): the game's pads have no model, only a flat square
  collider (30-60 units wide) as the trigger, and put the **jump strength in the first spare placement byte**
  (+6): 100, 120, 200 or 250 in the maps. A pad written with 200 launched a player to about twice the height of
  a 60-unit wall.
- **No kill height in map files**: it is in the game's code: **y = 0** on the battle maps (Tinkerer_Red; tested on
  st03 2026-11-20: walking down a ramp to y = -50 respawns the player just below 0, and a floor at +30 is fine).
  Edgar's Dream (st01) starts at -400 and rises during the battle. So every floor of a custom map must stay above
  y = 0. Narrow gaps are hard to fall through (players catch on edges).
- Category 4 also has `ReadLim` ("genkai", type 15) and trigger walls (types 1-12), only used in Sein (st09).

### Object behaviour classes (read from the exe)

The factory table at `0x1402dc4f0` holds one constructor table per category; each constructor builds a class whose
RTTI names list its behaviour parts: `Hit` (reacts to attacks), `Brk` (breakable), `Roll` (broken pieces become
rolling physics bodies), `Crm` (pieces crumble in place), `Tch`/`TchR` (breaks on touch), `Wall`, `Ceil` + `RollF`/
`CrmF` (falls), `NoCam` (ignored by the camera). Category 2: 1 `Rep01` and 2 `Rep02` (Ver, On, Roll, Hit), 3 `Rep03`
(Ver, On, Crm, Hit), 4/5 (+ Hitif), 6 (Mvan, Col), 7 `Wall` (Wall, Roll), 8 `Crm` (Wall, Crm), 12 `Ceil` (Roll,
RollF), 13 `CeilCrm` (Crm, CrmF), 17 (Tch, Roll), 18 (Tch, Crm), 22/23 (RollF/CrmF), 27-30 (VerU, Pl/Pl2), 37/38
(VerS, OnS), 42/43 (Hitif, Rand), 47 (Roll), 48 (Crm). Category 1: 4 = Hit, Hitif, NoCam. Category 4: 1-12 and 20
`Read` (Col), 15/21 `ReadLim`, 16 `Jump`, 22-24 `Door`.

## Stage models list: `MD00` (header `0xA0`)

`MD00`, u32 size, u32 size, u32 80; then 80 NUL-terminated model names (`NOUSE` = empty), 80 animation names
(`.ala`), then 80 pairs `s32 .alr root, s32 animation` (-1 = none). Slots have fixed roles:

| Slots | Role |
|---|---|
| 0-19 | the map's moving or effect models (fans, lamps, glow tiles, emitters) |
| 20-33 | broken-object (`crs`) models |
| 35 | `*_crs_chakudan`: impact debris (rock chunks with the map's `e3o_stNNcrs` texture, shader `scrash2`) |
| 40, 41, 42 | impact model on iron, stone, soil |
| 45 | hit smoke |
| 53-55 | stone splinters (`hahen`) |

Most maps use plain dented-crater meshes for 40-42 (shader `sd`, textures `e3o_hit01/02`). **Twilight Lane** uses
`st07_mdl_hit_strange` in all three: a stencil "hole" (`vkstncl00`, `e3o_hole01`) plus an animated glow
(`vkcolanim4`, `e3o_glowup`) in slot 45, and no impact debris (slot 35 = -1): the glowing holes that heal. Sein uses
Highway's models. Where the `.ala` animations themselves are stored is not known yet (header `0xF4` holds the
light animations, numbered chunks of type 5), so the Lane impacts can't be moved to another map yet.

## Effects (`EF00`, header `0x98`) (confirmed in game)

`0x5C`-byte entries: `u8 kind, u8 layout filter (0 = always, else only for layout value - 6), u8 0xFF, u8 0,
f32 position[3], f32 rotation[3] (radians), f32 scale[3]`, then 13 kind-specific values. Count and byte size
follow the `EF00` tag (`u16, u16`). The kind picks the effect class through the table at `0x1402dc520`
(`FUN_1401ef940`):

| Kind | Class | Kind | Class |
|---|---|---|---|
| 2, 3, 8 | smoke (`pdvkEbSmoke`) | 13, 10 | effect model (lamps, signs) |
| 4 | belt smoke | 14, 15 | effect model (other) |
| 5 | glow | 16, 17 | screen shake |
| 6, 9 | crash (break burst) | 18, 19 | water drops |
| 7 | jump point | 20 | stage parameters (`pdvkEbStgParam`, one per map): the stage's variants, see below |
| 11, 12 | sound emitter | 21, 22 / 23, 24 | steam / sparks |

Copied into another map (tested in Panorama Earthquake's slot): **steam** (Sein), **sparks** (Sein) and
**smoke** work; **glow** (Twilight Lane) draws as a white square and **water drops** (Lost Palace) don't show:
they need their home map's textures. Effect models, sound emitters and crash bursts reference map-specific
resources (small index values), so they aren't portable either. A new table is written by
`pdstage/effects_build.py`, appended to the file with header `0x98` repointed.

All maps scanned (2026-11-18): the kinds actually used are 2 smoke (Panorama), 5 glow (Lane, Sein), 6 crash,
10/13 effect models, 12 sound emitters (every map), 19 water drops (Palace, Sein), 20 stage parameters, 22 steam
and 24 sparks (Sein). Only kinds 2, 22 and 24 work in any map. Checked in game with `tools/effect_test_map.py`
on Lost Palace: kind 22 is steam, smoke or fire depending on its parameters (Sein #137 steam pipe, #79 smoke,
#3 faint smoke, #17 animated fire, stuttery); kind 24 Sein #75 sparks, #7 light sparks; kind 2 Panorama #21 and
#23 the same black, spread-out smoke.

**Stage variants.** Per the user's knowledge of the game, the stage-parameters effect (kind 20) goes with the
stage's **variants**: different effects, object positions and so on for the same stage, one of which is picked
at random when a match starts. In the files this shows up as the per-layout placement tables (`PS00`/`PS01`...,
one per layout slot) and the effect entries' layout filter byte (an effect shown only in one variant). The
add-on currently writes one variant (placement slot 0, effects for all layouts) and the clean slate drops the
game original's kind-20 entry.

## Lighting: the `mapLight` script (header `0xD0`) (confirmed in game)

Loaded by `FUN_140199b00` (it falls back to `maplight%d.ssb` files, which the PC version doesn't ship). A
compiled SSB script: header (0x20 bytes: header size, function table offset, string pool offset twice, 0,
`FFFF FFFF`, a u32 that varies per file, 0), 32-bit code words, a function table with one entry (`maplight`,
two base-40 words, start at word 8) and an empty string pool. The code is only argument pushes and native calls:

| Word | Meaning |
|---|---|
| `(v << 16) \| 0x0E` | push the small int v |
| `(low 16 bits << 16) \| 0x0F`, then the 32 bits | push a float, or a packed `0x00RRGGBB` colour |
| `(id << 16) \| (count << 8) \| 0x01` | call native `id` with the last `count` pushed values |
| `0x00000005` | return |

The game keeps four light sets (0x58 bytes each at `0x1403e8a40`). Set 0 lights the stage, placed objects
and effects; set 1 lights characters; sets 2 and 3 are used while drawing the far models (`FUN_1401c87f0`).

| Call | Arguments |
|---|---|
| `2000` | ambient axis (3 floats), light direction (3 floats, the way the light travels: y < 0 = from above), light colour, second colour, ambient colour, set |
| `2002` | fog: a, b, colour, mode (0 off, 1/2 exponential with density a, 3 linear from b to a), set |
| `2005` | point light: range, position (3 floats), colour, slot 0-2, set |
| `2001` | 0, a colour |
| `2003` | a scale (0.7-1.1 across maps), 0 |

Confirmed in game: set 0's light and ambient colours tint the stage, objects and effects (multiplying the
baked vertex colours, with the shaded side getting the ambient colour); set 1's tint characters. **Fog does
nothing on PC**: the fog render states the script feeds (`0x5C`-`0x60`, `0x8A`) have no case in the PC
version's render-state setter `FUN_140020660`, and a test with bright fog colours showed none.
`addon/phantom_dust_stage/pdstage/maplight.py` reads and writes the script (every map's script rebuilds byte-identical);
`tools/dump_ssb.py` prints it.

**Character light direction (confirmed in game):** set 1's direction is read with its two horizontal axes
swapped: a scene sun travelling along game `(x, y, z)` needs set 1 = `(z, y, x)` for the characters' real-time
shadows to fall the same way as the stage's baked shadows (set 0 keeps `(x, y, z)`). The exporter writes it so.

## Not yet known

- Material bytes `0x40`-`0x4B`, the `0x40` flag at `0x0D`; whether the highlight power byte above 128 is clamped or scaled.
- What surface types mean, and the `128, 3, 24, 0` / flags values in spawn entries.
- `OA`/`OC`/`OE` sections, `SP00`, `MD00`, the object table beyond its first 3 fields.
- `stNNcam.alr` details; natives `2001` and `2003` of the lighting script; the light animation block.
