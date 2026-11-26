# p2: the sections the rebuild still took from the game file (SP00, MD00 + blobs, enter chunks, object animations, cube maps)

Worker p2, 2026-11-25. Branch `r-p2` in <local work folder> Proof outputs: <local proof folder> IDA: my copies of
the Xbox XBE database and the PC PDUWP.exe database (read through session `p5pc`, read only). Byte layouts: survey
scripts in <local proof folder> over all 21 stage files of the 2017 PC data and the Xbox disc (the `.dat`
files are identical between the two: `survey/pc.txt` = `survey/xbox.txt`).

Format: claim -> evidence -> confidence.

## 1. SP00: sprite types (header word 0x9C)

| Field | Meaning | Evidence | Confidence |
|---|---|---|---|
| `+0x00` `SP00`, `+0x04` u32 list count, `+0x08` u32 = 1 | the parser starts reading at +12 using +4; +8 is never read | `Stage_ParseSp00` 0xE0DB0 | high |
| frame lists: u32 count, 32-byte frames | frame = quad corners (left, top, right, bottom) and texture rect (u0, v0, u1, v1); corners scaled by 127 into the vertex data | 0xE0DB0 (list pointers), `sub_15EE30` (x127, UVs) | high |
| table: u32 name bytes, u32 count, names, `count` 20-byte entries, then **one more 20-byte entry** | the parser writes zeros into the entry after the last one: a writer must reserve it or the next section's first 20 bytes are overwritten | 0xE0DB0 (`*v10 = 0 ... v10[4] = 0` at `table + 20 * count`) | high |
| entry +0 name index | index into the name list (the parser skips that many strings); "NOUSE" -> no sprite | 0xE0DB0 | high |
| entry +4 list | frame list index (replaced by a pointer in memory) | 0xE0DB0 | high |
| entry +8 **capacity** (was "texture extent" in our docs) | the loader reserves `capacity << 7` bytes (one quad = 4 vertices x 32 bytes) from a 512 KiB pool (Xbox) / 1 MiB (PC); **0 = the sprite type is not made** | `Stage_LoadSp00Animations` 0xE0F30 (`!v8[2]` -> zeroed; `dword_39C670 += v8[2] << 7`), PC `sub_140205790` (same test, pool 0x100000), `sub_15F370` writes quads at `index << 7` | high (on/off), medium (exactly "quads alive") |
| entry +12 frames | how many frames of the list the type plays (80 bytes per frame allocated) | 0xE0F30, `sub_15F210` | high |
| entry +16 blend kind | pair (begin, end) of render-state routines at 0x2CA4C0: 0 cut-out (no blend, alpha > 0xFE), 1 alpha (0x5401: src alpha / inv src alpha), 2 additive (0x1101), 3 darken (0x5001: zero / inv src alpha), 4 0x3901 (inv dst colour / inv src colour), 5 0x1801 (dst colour / one), 6 blend state untouched, 7 routine 0x14BED0; all write no depth | 0xE1710..0xE17F0, blend word decoder 0x14BDE0 with factor table 0x2A40A8 and op table 0x2A4084 | high (words), medium (names) |
| texture lookup | the name up to its '.', as two base-40 words (case-insensitive, 12 characters) in the **stage model** (.alr); not found -> the type is not made | `sub_14CE50` -> `sub_158CB0` | high |
| numbering | the shared Map/st00 table is loaded first, then the stage's: one sprite numbering | 0xE0F30 loop over `dword_39C778[0..1]` | high |

Survey: st01 53 entries of which 8 are made, st02 50 / 11 ... (`survey/sp00.txt`); 160+ named entries have capacity 0
(the `e3a_emit*`, `EnvMap.dds` ones): the game ignores them.

**Blender**: `Sprites` collection, one mesh object per type the game makes (`Sprite NN <texture>`): one quad face per
frame (frame k at local y = k x 0.25), quad corners = the frame's extent (x, z), UVs = the frame's texture rectangle,
material image = the texture; `pd_sprite_number`, `pd_sprite_capacity`, `pd_sprite_blend`. Export: `pdstage/sp00.py`
`build()` (identical frame lists shared, terminator entry written). Entries the game does not make are not
represented (their numbers become NOUSE).

## 2. MD00 model list and the blob list (words 0xA0, 0xF4)

| Field | Meaning | Evidence | Confidence |
|---|---|---|---|
| `+4` size of block 0, `+8` size of block 1, `+0x0C` slot count | blocks 0/1: `.alm` / `.ala` source names, **never read** (`0x39E910`/`0x39E914` only by Bind/Free) | `Stage_BindMd00` 0xBE360, xrefs | high |
| pairs `(model, blob)` until a pair with model 0 | model = resource of the stage .alr (`Alr_GetResource(g_StageModel, m)`), -1 none; blob = index into the 0xF4 list, -1 none | `Stage_ResolveMd00Models` 0xBE3D0; PC `sub_1401D9210` (community map: PROVEN-READ) | high |
| slots | stage slots follow the 24 shared ones (effect record byte 0 -> slot 24 + byte), cap 0x90 | 0xBE3D0 (`v0 >= 0x90` hang), engine notes (0xF67E0) | high |
| blob list | u32 count, then u32 length + bytes; a blob is a run of animation chunks (id 5) ended by {0, 8} | 0xBE3D0 walk, survey | high |
| 84-byte blobs | an empty model chunk run (0x15, 0x01, 0x03, 0x16, 0x0D, 0x0F, end): **never referenced** by any pair (47 of them over the 21 files) | `survey/md00.txt` | high |
| block 0/1 names in slots with model -1 | leftovers (e.g. st01 slot 16 `st02_mdl_particle.alm`) | survey | high |

Every blob track (2,226 over all files) uses channel codes 0, 8-byte rotation keys, 16-byte translation keys; 413
have scale keys. **Blender**: `Stage Models` collection: one empty per slot in use (`pd_md00_slot`,
`pd_game_model_root`); for an animated slot the model's joints as empties (`pd_joint`, rest pose from the skeleton)
with one Action each (location / rotation_euler in mode XZY / scale keys = the joint's local transform: game Euler
X, Y, Z (Rz Ry Rx) on the mirrored axes is exactly Blender XZY with angles (-x, -z, -y), so the keys keep the game's
own angles and need no decomposition (decomposing a float32 quaternion moved the angles by a few units per cycle at
the gimbal lock); frame = game frame,
the action's manual frame range = the track length). Export: `stage_extras.build_md00` (slot count 80, town 16,
blobs renumbered, unreferenced placeholders dropped). **Still open**: the slot's *model* (meshes, `vk*` effect
shaders, 0x13/0x14 effect chunks: 742 chunks, 495 `vkpsprite` meshes) is still the game file's root (named by
`pd_game_model_root`); representing it needs the effect chunks and the effect shaders' vertex formats first.

## 3. Enter chunk stream (word 0xFC + 4k)

| Claim | Evidence | Confidence |
|---|---|---|
| battle maps: **both executables** play the stream of word 0xFC + 4 x (stage / 10) (else 0xFC) into the battle light object, which clears its light objects and plays the chunks from light 0; the town (stage % 10 == 9) plays 0xFC from light 32, then the area's list. (My first reading said "Xbox: town only": Hex-Rays drops the pointer, passed in EAX to `sub_8A0C0` at 0xE0567; p5 found it in the assembly, which I confirmed) | Xbox 0xE03B0 asm 0xE0525..0xE0569, 0xE0610; PC `sub_140204860` -> `sub_14019A020` | high |
| every battle map holds an empty stream (one {0, 8} end chunk) or none (-1: st01, st03, st07, st13, st17, st23, st24, st32); st09 holds one light list (chunk 9, 24 records) | survey | high |
| light list record (40 bytes): +0 colour 0x00RRGGBB, +4 kind (1 directional, 2/3 point, 5 hemisphere, other = clear), +5 light index (when flag 0x02), +6 flags (0x02 explicit index, 0x08 / 0x10 masks 2 / 4), +7 unread, +8 vector, +20 intensity, +24 position, +36 (kind 1 only -> light +0x60; points get 1.0) | `sub_14D290` | high |

**Blender**: `Enter Lights` collection, one light per record (`pd_light_index`, `pd_light_kind`, `pd_light_mask`,
colour, energy = intensity, location = position, `pd_light_vector` when not zero). Export: one light list with every
index explicit (order free); no collection -> no stream (both executables then place nothing).

## 4. Object animations (OA, definition words +0x0C..+0x17)

| Claim | Evidence | Confidence |
|---|---|---|
| rotation keys are **Euler angles** (u16 frame, 3 x s16, unit pi/16384, X then Y then Z), not quaternion x, y, z as the add-on's `anim_build.py` read them | the only chunk-5 samplers (`sub_14E760`, `sub_14DE40`) convert every rotation key with `sub_1540B0` (half-angle sine table, `(u >> 1) & 0x7FFF`) and slerp (0x153E20); no quaternion path exists | high |
| a translation key is the joint's whole local position (frame 0 = the rest position, e.g. st02 iron road piece 1: rest (0, -13.87, 0), key 0 (0, -13.87, 0)) | 0x14E760 writes the sampled value as the joint's local translation; data | high |
| only state 1 (broken) has animations: st02/12/22 nine iron roads (one track per piece, 90 keys), st06/16/26 one type with a single root track (269 translation / 220 rotation keys) | `survey` (`scripts/oa_check.py`) | high |
| **bug found**: the 1.3.0 hex copy wrote the original keys onto rebuilt pieces whose rest pose is identity (their meshes are written where they stand), so every piece was offset again by its rest position: up to **80.5 units** off over the animation on st02 | `compare_items.py` on the pre-change rebuild (`base/`) | high |

**Blender**: an Action on each broken piece (`break_`/`stay_`) of the type's first placement keying
`delta_location` / `delta_rotation_quaternion` = the piece's motion away from its rest pose (sampled at every key
frame of its own and its parents' tracks, frame = game frame, manual frame range = track length); a root-joint
animation is one Action shared by all pieces. Export: per piece a track for its node (rest identity) or, when every
piece shares one action, one joint-0 track. The export reads pieces at their rest pose (deltas excluded).

## 5. Cube maps

| Claim | Evidence | Confidence |
|---|---|---|
| descriptor bit 2 (`+0x0C` byte) = cube; six faces one after the other, each its full mip chain padded to 128 bytes | sizes over every file: envmap 64x64 DXT1 7 mips = 6 x 2816 = 16896; st07 `s7_envmap_h` B8G8R8A8 = 6 x 21888; `s7_irrad01` 6 x 1408 | high |
| face order +X -X +Y -Y +Z -Z | Direct3D convention; not separately proven in game | medium |
| Xbox B8G8R8A8 faces are swizzled (format 0x06), PC linear (0x86); DXT1 the same bytes | survey | high |
| **2017 PC port data quirk**: st07's two B8G8R8A8 cube maps (`s7_envmap_h`, `s7_irrad01`) carry the linear flag (0x86) but only face 0 was un-swizzled by the port's conversion; faces 1-5 are the Xbox's swizzled bytes, identical to the disc's (read as linear they are scrambled; read swizzled they show the sky and the sun). The PC texture converter `sub_1400BCAC0` skips its Morton step for every level when 0x80 is set, so unless its cube caller treats faces 1-5 apart (not read), the port draws them scrambled (a port bug on Twilight Lane's reflections). The rebuild keeps what the PC file holds | byte comparison PC vs Xbox per face; `sub_1400BCAC0`; decoded picture `<local proof folder>` | high (data), medium (PC display) |
| our engine does not decode cube maps (`decode_textures` returns None), so engine pictures cannot show them | `phantom-app/src/scene.rs` | high |

| the game's cube map mip levels are **their own pictures**, not a reduction of level 0: envmap mip 2 is on average 8 to 55 levels (of 255) away from a box reduction of mip 0 (st02, per face); st07's B8G8R8A8 ones are close (0-8) | `pdstage/cubemap.py` decode, survey | high |

**Blender**: one image per cube map: the six faces side by side left to right (`pd_cube_map`), each face's mip levels
stacked under it (64 x 64 + 32 + ... + 1 = 384 x 127), in the material's texture slot. Export: each face's levels
from the image, encoded (DXT1 opaque / DXT5 with alpha, never 1-bit-alpha DXT1: st07's `s7_envmap_h` has alpha 0
with colour), 128-byte padded, cube bit set. An image of one row of faces gets its levels by halving.

## 6. Effect textures still carried

The export kept a texture's game-file bytes when no Blender image was made for it: the 16-bit formats (B5G6R5
0x05/0x85: 18 textures, B4G4R4A4 0x04/0x84: 1, B5G5R5A1 0x02/0x82: 2), which the importer's DDS path did not read
(st00 effect textures, st01/st08 `cloud_color3`, st08 `e3o_glowup02`, st09 normal maps, st09_03 effect textures).
They are now decoded (Xbox swizzled or PC linear) into Blender images and written from them (DXT, lossy). The
export report names every game-file texture still kept as it is (0 expected).

## Proof (<local proof folder>, README.md has every table; code r-p2 at 6e10fe9)

Field-by-field, `scripts/compare_items.py` (original vs rebuilt; import -> export u1 -> import -> ... u3; fallback off):

| Item | What is compared | PC: 21 stage files x u1, u3 | Xbox (6 maps), Ascension (st03 slot) |
|---|---|---|---|
| SP00 | for every entry the game makes a sprite of: texture (as the loader looks it up in the rebuilt .alr), capacity, blend, every frame's 8 floats | same on all (176 sprite types; the 160+ entries the game ignores are not kept) | same |
| MD00 + blobs | per slot: model / blob presence, the model's content, every animated joint's local transform sampled at every frame | same on all; 171 animations; max 0.00012 units, 1.7e-6 degrees | same |
| enter lights | the light list per light object: kind, colour, mask, vector, intensity, position | same (st09: 24 of 24; battle maps none) | same |
| object animations | every broken piece's vertices moved by the animation, at every frame | same; 2,406 vertices; max 0.013 units (before this work: 80.5 units on st02) | same |
| cube maps | decoded faces, every mip level | same; envmap mean error 0.03-0.5 of 255 (top level), st07 `s7_envmap_h` 2.1, `s7_irrad01` 5.5 (16 px, DXT) | Xbox st07: 1.7 / 3.2 |
| carried textures | the export's own count of game-file textures written as they are | 0 on every map | 0 |

Edit and undo (`final8_edits.tsv`, st02, st06, st07, st09): every edit (sprite quads wider, a stage-model key raised, a
piece animation key raised, the cube map darkened, an enter light moved) changes its own item only, and the undo is
equivalent to the original again: 18 of 18.

Engine (`eng/`): original | hybrid (the game's files with only these sections from the rebuilt .dat) | full rebuild,
pixel diff, wide and 4:3, three views at frame 150: st02 and st05 hybrid = 0.000 mean difference in every view. The
engine shows the MD00 animation (control: st05 without blobs changes the picture, mean 1.31 overview), so the zero is
meaningful there. It does not draw the stage's own SP00 sprite types in any view tried (control: every capacity 0
changes nothing on st02, st04, st05, st07), it does not decode cube maps, and the battle has no way to break an
object: those three are proven by the field comparison only. Cube maps: picture `eng/cube_maps.png`.

## Open

- The MD00 slots' models (meshes with `vk*` effect shaders, 0x13/0x14 effect chunks) are still the game file's roots.
- The town's area files (`st09_NN.dat`: their own MD00, blobs and light lists) are exported whole, as before.
- Engine pictures of stage sprite types, cube-mapped surfaces and broken-object animations (engine support missing).
- `s7_irrad01` (16 x 16 B8G8R8A8 cube) loses detail as DXT1 (mean 5.5); a plain-format path for small textures would
  keep it exact.
- xemu requests R-p2-1..3 (capacity 0, enter light on a battle map, Euler keys) in xemu-requests.md.
