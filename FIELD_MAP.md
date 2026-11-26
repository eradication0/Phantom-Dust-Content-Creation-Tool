# Field map: stage `.dat` and `.alr` -> Blender

Every field of the two files a map export writes, what it means, and where the export takes it from. Status words:

- **Scene**: real Blender data the user sees and edits (objects, meshes, materials, lights, world), or a custom
  property that names a game setting (object type, surface kind, ...).
- **Computed**: derived on export from scene data (counts, offsets, bounds, normals, sizes).
- **Constant**: the same value in every file of the game (Xbox and 2017 PC); written as that value.
- **Game file (not in scene yet)**: not represented in Blender in this branch. In a rebuild the export takes the
  section from the slot's game file (the map the scene was exported to), whole and unchanged. These are the gaps.
- **Dropped**: read by the game, not represented and not carried: lost on a rebuild.

Sources: `FORMATS.md` (this repository), community references (Phantom Dust wiki "File Formats", Esper-RE structures;
facts only), and separate clean-room notes on the game's files (stage layout, stage collision list, ALR container,
SSB scripts, effect classes). "Rebuild" below means the default export (option "Preserve unedited parts from the
original file" off).

## Stage `.dat` (`ST00`, 0x13C-byte header)

### Container

| Field | Meaning | Blender | Status |
|---|---|---|---|
| `+0x000` magic `ST00` | file kind | - | Constant |
| `+0x004` u32[11] placement list offsets, `+0x030` u32[11] counts | object layouts: list 0 = default, list `1 + variant` used by that variant (lists 0, 2, 3 used) | one `Objects` collection per layout (`Layout 0`, `Layout 2`, ...; this round imports every layout, 1.3.0 imported one) | Computed |
| `+0x05C` NM00 offset, `+0x060` name count | object type names | the type collections' names | Computed |
| `+0x064..0x084` OC/OE/OA tags | sections the object definitions point into | - | Computed |
| `+0x088`, `+0x08C`, `+0x0C0..0x0CC`, `+0x0DC..0x0F0`, `+0x100..0x134` | -1 in every file; no reader in either executable | - | Constant |
| `+0x090` OB00, `+0x094` collision, `+0x098` EF00, `+0x09C` SP00, `+0x0A0` MD00 | section offsets | - | Computed |
| `+0x0A4..0x0BC` CP00 groups | start-point groups (up to six) | the `Spawn_Points` layout collections | Computed |
| `+0x0D0 + 4k` light script per variant | the `mapLight` SSB script | lights and worlds (below) | Computed |
| `+0x0F4` blob list | the MD00 models' animation blobs (runs of animation chunks) | the joint Actions of the `Stage Models` slots | Scene -> built (`stage_extras.build_md00`; unreferenced 84-byte placeholders dropped) |
| `+0x0F8` sound table | one 16-byte row per object definition | object type collection settings | Computed |
| `+0x0FC + 4k` enter chunk stream | ALR chunk run played at stage start by both executables (battle maps: word `0xFC + 4 * tens digit`, else `0xFC`, into the battle light from light 0; the town: from light 32); only chunk 9 (light list) occurs | `Enter Lights` collection: one light per record (`pd_light_index`, `pd_light_kind`, `pd_light_mask`) | Scene -> built (`pdstage/enter.py`); no collection = no stream |
| `+0x138` file size | | - | Computed |
| section tags (`PS0/`, `PS01`, `NM00`, `OB00`, ...) sitting before their data | | - | Constant per section |

### Placement entry (0x24 bytes)

| Field | Meaning | Blender | Status |
|---|---|---|---|
| `+0x00` i32 object | object definition index | the object's type collection | Computed |
| list membership | which of lists 0, 2, 3 the placement is in | object `pd_layouts` (a placement in several lists is one object) | Scene |
| `+0x04` u8 table, `+0x05` u8 class | behaviour class (factory table and index) | type collection `pd_preset` / `pd_category` / `pd_type` | Scene |
| `+0x06` u8 phase | argument of the object's method +160 (st01: floor group of a piece); jump power on jump pads | object `pd_jump_power` (pads), else object `pd_extra[0]` | Scene |
| `+0x07` u8 argument | argument of method +168 (0 on every st01 placement) | object `pd_extra[1]` | Scene |
| `+0x08` u32 | not read; 0 in every entry | - | Constant |
| `+0x0C` f32[3] position, `+0x18` f32[3] rotation | | object location and rotation | Scene |

### `NM00` names, `OB00` definitions (0x38 bytes), sound rows (16 bytes)

| Field | Meaning | Blender | Status |
|---|---|---|---|
| names | one per definition | type collection name | Scene |
| `+0x00` s32[3] models | ALR root per state (intact, broken, debris) | the type's meshes (intact object, `break_`/`stay_` pieces, `debris_`) | Computed (root indices of the written `.alr`) |
| `+0x0C` s32[3] animations | OA chunk streams (moving objects: iron roads, containers; state 1 only). Rotation keys are Euler angles (pi/16384), not quaternions | Actions on the broken pieces keying `delta_location` / `delta_rotation_quaternion` (a root-joint run = one Action shared by every piece) | Scene -> built (`stage_extras.export_piece_animation`); the hex copy is gone |
| `+0x18` s32[3] collision | OC collision lists per state | `collider_` / `collider_broken_` / `collider_debris_` meshes with `pd_surface`; `pd_no_collider` on a placed object whose game object has none (else the export makes a box) | Scene -> built on export |
| `+0x24` s32[3] effects | OE effect lists per state | `pd_object_effects` (hex copy; inherited from 1.3.0) | **Gap**: should become effect empties parented to the type's object |
| `+0x30` u32[2] | not read | - | Constant (0, -1 in entry 0; the game's other entries hold leftovers; written 0, -1) |
| sound row `s16[8]` | per-event sound ids; word 1 hit/break, word 2 pieces; word 4 also the pieces' life in seconds | type collection `Break sound` / `Piece sound`; the other words `pd_object_sounds` | Scene (words 1, 2) / Scene custom property (the rest) |
| root node values (the `.alr` root's first joint `extra`: hits, damage, debris stays) | | type collection `pd_hits`, `pd_damage`, `pd_debris_stays`; `pd_root_values` | Scene |

### Stage collision (header `+0x94`)

| Field | Meaning | Blender | Status |
|---|---|---|---|
| chunk `+0x00` kind | surface kind | collision collection `pd_surface` | Scene |
| `+0x01` shape 3/8 | mesh / vertex pool | - | Computed |
| `+0x02` flags (3), `+0x03` part (0xFF) | every stage chunk 3 / 0xFF | - | Constant |
| `+0x04` size, `+0x08` reserved 0 | | - | Computed / Constant |
| mesh `+0x0C` sphere, `+0x1C` box | bounds of the chunk's triangles | - | Computed |
| `+0x34` triangle count, `+0x38` pool index | | - | Computed |
| `+0x36` u16 group | 0x030B or 0x0034; no reader in either executable | - | Computed (written 0x030B) |
| triangle `i0 i1 i2`, normal | | collision mesh faces | Scene -> Computed normals |
| triangle `+0x06` u16 | 0 on most maps, 52 in every triangle of st05/15/24/25; no reader in the collision builders (`0xBA270`, `0xB9630`, PC `sub_1401D3040`) per our notes (issue #522; gameplay ledger: "unknown_06, none found") | - | Computed (0); not carried: **to represent** as a per-collision-mesh property if a reader is ever found |
| pool kind byte (35 or 33) | not a surface kind; never queried | - | Computed (35) |
| terminator `FF FF CC CC 0 CCCCCCCC` | | - | Constant |
| chunking (triangles per chunk) | broad-phase cells | - | Computed (by surface kind, spatial split) |

### `EF00` effect list (header `+0x98`), records of 0x5C bytes

| Field | Meaning | Blender | Status |
|---|---|---|---|
| `+0x00` u8 class | effect class (sound node, glare, sprite emitter, animated model, wind, ...) | empty `pd_fx_class` | Scene |
| `+0x01` u8 when | 0 while the variant shows, 1 hit, 2 break, 3 other; town: area + 6 | `pd_fx_when` | Scene |
| `+0x02` u8 id | 0xFF = always | `pd_fx_id` | Scene |
| `+0x03` u8 | draw mode of classes 10/13; start tick of shakes | `pd_fx_mode` | Scene |
| `+0x04` f32[3] position | | empty location | Scene |
| `+0x10` f32[3] rotation | | empty rotation | Scene |
| `+0x1C` f32[3] scale | | empty scale | Scene |
| `+0x28` u8[12] | class parameters (sound: repeat limit, map-bank flag; sprites: start, end, period, life, sprite, alpha, frames, colour; ...) | `pd_fx_params` (12 integers 0-255) | Scene |
| `+0x34` f32[10] | class values (sound: period, sound id; sprites: size, growth, drift, rise, angle, spin, wind share; ...) | `pd_fx_values` (10 numbers) | Scene |
| 1.3.0: the whole record as `pd_effect_raw` (hex) | | removed this round | - |

### `CP00` start-point groups

| Field | Meaning | Blender | Status |
|---|---|---|---|
| `+0x04` u8 count, 3 bytes | records in the group | spawn empties in the layout collection | Computed |
| record `+0x00` f32[3] position, `+0x0C` facing | | spawn empty location and Z rotation | Scene |
| `+0x10` u32 0x80100003 | not read | - | Constant |
| `+0x14` f32[9] capsule points | the three orb points | `_ORB_n` child empties | Scene |
| `+0x38` u32[6] | not read; constant (128, 3, 24, 0, ...) per file | - | Constant |

### `MD00` stage model list (header `+0xA0`), blob list (`+0xF4`)

| Field | Meaning | Blender | Status |
|---|---|---|---|
| block 0, block 1 (name strings, animation name strings; no reader in the game) | | the slot empties' names | Computed (unread) |
| pairs `(model root, blob)` x 80 | the stage's extra models (effect slot 24 + slot) and their animation blobs | `Stage Models` collection: an empty per slot (`pd_md00_slot`, `pd_game_model_root`), joint empties with Actions | Scene -> built; **the model itself (meshes, `vk*` shaders, 0x13/0x14 effect chunks) is still the game file's root** |

### `SP00` sprite animations (header `+0x9C`)

Frame lists, frames (quad extent, texture rectangle), the texture-name table and entries (name, list, capacity = quads
alive, 0 = off; frames; blend kind). `Sprites` collection: one mesh per sprite type the game makes (one quad per frame,
UVs = texture rectangle, material image = texture; `pd_sprite_number`, `pd_sprite_capacity`, `pd_sprite_blend`).
Scene -> built (`pdstage/sp00.py`). Entries the game ignores (NOUSE, capacity 0, no such texture) are not kept.

### Light script (`mapLight`, header `+0xD0 + 4 * k`)

SSB container: 0x20-byte header (`+0x00` header size, `+0x04` function table offset, `+0x08`/`+0x0C` string pool
offsets, `+0x10` 0, `+0x14` -1, `+0x18` an id no reader in the script VM uses, `+0x1C` 0), code words, one
function-table entry `maplight` (two base-40 words). All Computed: the header from the code's length; `+0x18` as
`1788801600 + 1600 x stage number` (the game's value for st01-st09; st12-st26 hold other values, unread); the slot
`k` = the stage number's tens digit (the word the game runs). Argument encoding as the game's scripts: a number 0 as a
short integer, other numbers as floats; a colour below 0x10000 as a short integer, else 32 bits (written from values,
the 20 scripts of the 2017 PC files come out byte-identical: `tests/rebuild_offline_test.py`). The 22 calls:

| Call | Arguments | Blender | Status |
|---|---|---|---|
| `2000` x 4 | per set: ambient axis, light direction, diffuse colour, second diffuse colour, ambient colour | per set a sun light `PD Light: <set>` (object custom property `pd_light_set`; direction = the light's -Z, its length = the object's scale; colour = diffuse; light custom properties `pd_light_second` (colour) and `pd_light_axis`) and a world `PD World: <set>` (colour = ambient) | Scene |
| `2002` x 4 | per set: fog mode, start, end (linear) or density (exponential), colour | the set's world: `pd_fog_mode` (0 off, 1/2 exponential, 3 linear), mist `start`, mist `depth` = end - start, `pd_fog_density`, `pd_fog_colour`. A start below zero (st04 -70, Blender's mist cannot) is kept as `pd_fog_start` and used while the mist start is 0 | Scene |
| `2005` x 12 | per set and slot 0-2: range, position, colour | point lights `PD Point: <set> <slot>` (`pd_light_set`, `pd_point_slot`; location, colour; range = the light's custom distance, off = slot unused) | Scene |
| `2001` (syscall 2:1) | a word, a colour | scene `pd_shadow_colour`: the colour the shadow pass lays over every stencilled pixel (character and stage shadows: `0x151E60`, full-screen rectangle of `dword_2DD4B0`, set by 2:1; render notes) | Scene |
| `2003` (syscall 2:3) | glare level, glare colour (0 on 18 of 20 maps) | scene `pd_glare_level` (the level the bright-pass glare eases toward each frame, `0x89440`; stage entry starts at 0.5) and `pd_glare_colour` (copied with it; the single-screen glare chain passes 0 instead, only the split-screen chain may use it) | Scene |

The four sets are named `stage`, `characters`, `far 1`, `far 2`. The scene's world is the stage set's; the other
worlds have a fake user so they are kept when the file is saved.

## Stage `.alr`

| Field | Meaning | Blender | Status |
|---|---|---|---|
| header `0x11`: version 0x52, word 7, resource offset/size, root offsets | | - | Computed / Constant |
| `0x15` texture descriptors: format, mips, size, data | | the materials' Blender images | Scene: each image encoded from its pixels (DXT1 when opaque, DXT5 with alpha, with mip levels) under the texture number of the same name (the `.dat`'s effects use texture numbers), else appended. Lossy re-encoding; DXT1 textures with 1-bit alpha come back as DXT5 (twice the size) |
| texture name (two base-40 words) | | the image's name | Scene |
| textures no material uses (effect textures `e3...`, sprite sheets) | used by number by the `.dat`'s effects, SP00 and the model list | Blender images with their name and `pd_texture_number` (fake user) | Scene, written from the images under their numbers. Cube maps: one image with the six faces side by side (`pd_cube_map`), written as six 128-byte-aligned faces with the cube bit |
| `0x16` vertex buffers: format, stride, mask, count, data | | mesh positions, corner normals (the game's normals imported as custom normals), UV map, colour attribute `PD_Light` (RGB baked light, A shine mask), tangents from the UV map | Computed (format = the material's shader's) |
| `0x01` materials: shader name | one of 46 shaders | material `pd_game_shader` (set on import), else the add-on's four stage shaders (`sd`, `sbts`, `sdrefs`, `sbtsrefs`) from the material's maps, `lbts` (baked light maps), `sbtscloud3` (Scrolling Textures) | Scene. Written from game settings for the 29 shaders whose vertex format is a subset of position / normal / UV / colour / tangent frame; others (shadow shaders, `scrash2`, `swd`, the `vk` effect shaders of objects) fall back to the four |
| materials: `+0x0C` flags, `+0x11` filter, `+0x14` blend, `+0x16` texture-stage roles, `+0x18` textures | | `pd_material_flags`, `pd_material_filter`, `pd_material_blend`, `pd_texture_roles`; textures: the material's diffuse / normal / reflection images by role, other slots `pd_texture_<k>` (an image) | Scene |
| materials: `+0x10` vertex format | | - | Computed (from the shader) |
| materials: `+0x34` specular colour and power | | material highlight colour and shininess | Scene |
| materials: `+0x30` colour, `+0x38` word | ARGB words; no reader found in the shader classes nor the material setup (models ledger, `fmt.alr.material`: "unknown: 0x30 (ARGB colour, no reader) and 0x38") | `pd_material_colour`, `pd_material_word_38` (A, R, G, B) | Scene; **meaning unknown**: no reader in either executable per our notes; not re-checked in the IDB this round |
| materials: `+0x3C..+0x4B` shader parameters | per shader class: eye-vector w and bump scale (lit), parallax scales and height, cloud scroll rates, shadow length | `pd_shader_params` (eight numbers) | Scene (no per-class names in the UI yet) |
| `0x02` draws: sphere, box | | - | Computed |
| draws: light count, light indices | the draw's lights | - | **Dropped** (written 0) |
| draws: material, joint, vertex buffer, primitive, vertex start/count, indices | | mesh faces per material | Computed (triangle lists) |
| `0x03` skeleton: joints (position, rotation, scale, flags, parent, name, `extra`) | | stage: applied into the vertices (one joint); objects: root `extra` values (hits, damage, debris stays) and piece values | **Partly dropped**: stage joints, joint names and flags (bit 11 hides a joint's draws: the hidden shot markers) |
| `0x12` draw instances (st08, st09) | repeat a draw under another joint | written as copies | Computed (copies) |
| `0x13` effect parameters, `0x14` effect functions | named effect objects on the model | - | **Dropped** |
| `0x05` animation tracks | animation chunks in the model file | - | **Dropped**; `stNNcam.alr` is not written |
| shadow volumes (`sshadowc`, `sshadowch`) | character shadows on the stage | `ShadowCasters` meshes | Scene -> Computed (one `sshadowc` volume from the casters) |
| sky dome (root 2) | | Phantom Dust Sky settings | Scene (the add-on's sky model and its `sbtscloud3` / `svc` materials, not the game's dome mesh) |
| object models (roots of the object definitions) | | the object type collections' meshes | Scene; the game's own object roots are emptied (root numbers kept: the model list uses numbers) |

## Out of scope this round (stated explicitly)

These are read by the game and still not Blender data; each needs its own work:

- draw light indices (101 stage draws, all in the town, use three run-time lights; written 0);
- stage joints, joint names and flags (bit 11 hides the shot-marker joints): the stage is flattened to one joint;
- the effect chunks of models (`0x13` parameters, `0x14` effect functions);
- object effect lists (`pd_object_effects` hex);
- the sky dome mesh and its joints (the add-on's sky settings replace it);
- the MD00 slots' models (meshes with `vk*` effect shaders and 0x13/0x14 effect chunks: the game file's roots, named by
  `pd_game_model_root`); the town's area files (`st09_NN.dat`, their MD00, blobs and light lists) are kept whole.

## What a rebuild loses (this branch)

- `.dat`: the checks of what the game reads (spawns, collision, placements in every list with their class, turn,
  collider size and sounds, effects, light script values, MD00, SP00, blob list, enter chunks) come out the same on
  the maps measured (ROUNDTRIP_FIXES.md). SP00, MD00 with its blob list, the enter stream and the object animations
  are now written from the scene (proof: notes/p2-stage-sections.md); the MD00 slots' models are
  still the game file's roots. Still hex properties inherited from 1.3.0 (against the no-raw-data rule): the object
  effect lists (`pd_object_effects`); also
  `pd_root_values`, `pd_object_sounds` words other than 1 and 2, `pd_extra`. Not kept: the collision chunking and
  the per-map triangle word (`+0x06`, 52 on st05/15/24/25, no known reader).
- `.alr`: everything marked Dropped above, texture re-encoding loss, and the game's sky dome and shadow volumes
  (rebuilt from the add-on's sky settings and the shadow casters).
