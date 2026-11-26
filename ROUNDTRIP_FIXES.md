# Round-trip fixes (prepared for the add-on's author)

Branch `roundtrip-fixes`, on top of `d42caa7` (Phantom Dust Stage 1.3.0): plain fixes to the add-on, found by
importing the game's own maps, editing them and exporting them back. Where a fact about the formats comes from
separate notes on the game's files, the commit says so. Nothing was pushed or published: this file and the branch
are for the author to review.

Reported problem: the add-on could not load and export the game's **original** maps. An unedited round trip
(import an original stage, export it) should give the same files, and must never give broken ones; an edit should
change only what was edited, and taking the edit back should give the original files back.

## Read this first: what the numbers below measure

**The default export now builds both files from what is in Blender.** Every field of the stage `.dat` and the `.alr`
is mapped to its meaning and to its Blender source in [FIELD_MAP.md](FIELD_MAP.md) (or to "computed on export",
or listed as a gap). The scene holds no copies of the original file: no digests, no record offsets, no raw records.

The copy-back of the earlier rounds is still there, as an option that is **off by default**:

- export option **"Preserve unedited parts from the original file"**: parts whose import digest did not change keep
  the original file's bytes, and simple edits are written into the original records (`roundtrip.py`,
  `collision_build.patch()`, the in-place vertex, placement and light-script writers);
- import option **"Record for preserving unedited parts"**: the import records what the fallback needs (the digests
  `pd_roundtrip`, `pd_mesh`, `pd_meshes`, `pd_placement`). Off, the scene holds only what it shows.

Section **"Built from the scene (default)"** has the numbers of the default export (fallback off). Every section
marked **(fallback)** further down measures the copy-back option, not the default.

## Light scripts: what they hold (survey of the 2017 PC files)

Every battle map except `st32` has exactly one light script. 20 of the 21 stage files have one; `st32` has none.
It sits in one variant slot of header `0xD0` + 4 x variant: slot 0 for st01-st09, st16, st17 and st26; slot 1 for
st12-st15; slot 2 for st22-st25.

Every script has the same 22 calls:

| Calls | Native | What it sets | Effect in game |
|---|---|---|---|
| 4 | `2000` | per light set: ambient axis, light direction, diffuse colour, second diffuse, ambient colour | The four sets are the stage (with objects and effects), the characters, and two far / background sets. Set 0's light and ambient shade the stage's baked vertex colours. Set 1 tints the characters and gives the direction of their real-time shadow. |
| 4 | `2002` | per set: fog mode (0 off, 1/2 exponential with a density, 3 linear from a start to an end) and fog colour | Fog does nothing on the 2017 PC port: its render-state setter has no case for the fog states (FORMATS.md). On the Xbox it fogs the set. |
| 12 | `2005` | per set: 3 point-light slots, each with range, position and colour | 15 maps have at least one active point light (range > 0). Several "ranges" are 1e8-1e9, which amounts to a light without falloff. |
| 1 | `2001` | 0 and a global colour | Probably a global add or tint, not confirmed. 13 of the 20 maps have a non-zero value, e.g. st03 (15, 18, 25). |
| 1 | `2003` | a global scale and a second colour | Scale 0.70-1.10 (e.g. st02 0.71, st07 1.10), probably a light intensity multiplier, not confirmed. The second argument is a packed colour too: 0 on 18 maps, st03 (15, 25, 20), st09 (78, 153, 26). |

Non-trivial fog: 19 of the 20 maps have fog in at least one set; only st09 (the town hub) has none, and its stage
light is black (0, 0, 0). What `2001` and `2003` (both colours and the scale) do in game is not researched yet.

**In Blender (this round, default export):** the import makes the whole script real Blender data and the export
writes the 22 calls from it (`maplights.py`; FIELD_MAP.md has every argument):

- the four light sets: sun lights `PD Light: stage`, `characters`, `far 1`, `far 2` (direction, colour; the second
  colour and the ambient axis as custom properties) and one world per set, `PD World: <set>` (ambient colour; fog
  mode, start and end in the world's mist settings, fog colour and density as custom properties). The scene's world
  is the stage set's;
- the twelve point-light slots: point lights `PD Point: <set> <slot>` (location, colour, range = the light's custom
  distance; a slot not in use has it off);
- `2001` and `2003`: scene custom properties `pd_light_global_colour`, `pd_light_global_scale`,
  `pd_light_global_scale_colour`.

Written from the values alone, the 20 scripts of the 2017 PC files come out byte-identical (code words, offline:
`tests/rebuild_offline_test.py`). The old "Phantom Dust Lighting" panel (stage and character colours, the sun) still
drives the in-place light edit of the fallback.

## Built from the scene (default)

### What the export does now (fallback off)

- **Stage `.dat`.** Every section the scene holds is written from it: spawns (into the slot's start-point records),
  collision from the collision meshes (`collision_build.build_block`), the effect list from the effect empties, the
  object names, definitions, object collision, sound rows and **every placement list** (0, 2, 3: a placement in
  several lists is one Blender object with `pd_layouts`), the light script from the lights and worlds. The game
  file's section a new one replaces is then **cut out** (`pdstage/datfile.py`: sections are cut at every offset the
  game reads, including the offsets inside the object definitions; one pass, offsets moved), so each section is in
  the file once and nothing is appended twice. Since branch `r-p2`, the sprite types (SP00), the stage model list
  (MD00) with its animation blobs, the enter stream's light list and the object animations are Blender data too and
  written from it (section "Sprites, stage models, enter lights, object animations, cube maps" below).
- **Effects** are real Blender data: the empty's location, rotation (all three angles) and scale, plus named
  fields (`pd_fx_class`, `pd_fx_when`, `pd_fx_id`, `pd_fx_mode`, `pd_fx_params`, `pd_fx_values`). The 1.3.0 hex copy
  of the record (`pd_effect_raw`) is gone.
- **Objects**: a game object without collision keeps none (`pd_no_collider`; the export used to give it a box); a
  debris root keeps the game's own value (3 on Panorama's rubble, not 2). The game's own object models are emptied in
  the `.alr` when every object type is written new (root numbers kept: the model list uses them).
- **`.alr` materials keep the game's shader and settings** (`pd_game_shader`, flags, filter, blend, texture roles,
  the two colour words, eight shader parameters, extra texture slots as images). The writer makes the material record
  from them and the vertex buffer in the shader's own format: 29 shaders (`sd`, `sdyfog`, `sbtsyfog`, `sdal`, `sv`,
  `sc`, `sbpx`, `sbpxrefpal`, `sdrefp`, `dbts`, ...). 1.3.0 wrote every mesh with one of its four shaders.
- **Normals**: the game's vertex normals are imported as custom normals and written back (the shading stays the
  game's). Corners that write the same vertex bytes are one vertex.
- **Textures** are encoded from the Blender images (DXT1, DXT1 with 1-bit alpha, DXT5) under the texture number of
  the same name, so each texture is in the file once (the `.dat`'s effects use texture numbers). 1.3.0 reused the
  game's bytes for any image named like a game texture, even an edited one.
- **Lights**: see "Light scripts" above.

### Sprites, stage models, enter lights, object animations, cube maps (branch `r-p2`)

What each is (evidence: the Xbox and PC executables; field tables in FIELD_MAP.md) and its Blender form:

- **Sprite types (SP00)**: collection `Sprites`, one mesh per type the game makes: a quad per frame (corners = the
  frame's extent, UVs = its texture rectangle), the material's image = the texture (looked up by name in the
  `.alr`), `pd_sprite_number`, `pd_sprite_capacity` (quads alive; 0 = the game makes no sprite: the word our notes
  called a texture extent), `pd_sprite_blend`. The writer keeps the 20-byte entry the game's parser zeroes after
  the table (without it the parser overwrites the next section).
- **Stage model list (MD00) and the animation blobs**: collection `Stage Models`, an empty per slot in use
  (`pd_md00_slot`: effect records name slot 24 + it; `pd_game_model_root`), the model's joints as empties with an
  Action each (the joint's local translation, rotation as Euler XZY = the game's own angles, scale; frame = game
  frame). Unreferenced placeholder blobs (84 bytes, 47 in the game's files) are not kept. **Open**: the slot's model
  itself is still the game file's root (its `vk*` effect shaders and 0x13/0x14 effect chunks are not Blender data).
- **Enter stream**: collection `Enter Lights`, a Blender light per record of its light list (chunk 9). Both
  executables play it at stage start (battle maps from light 0, the town from light 32).
- **Object animations**: rotation keys are Euler angles (unit pi/16384), not quaternions; a translation key is the
  joint's whole local position. Actions on the broken pieces keying `delta_location` / `delta_rotation_quaternion`
  (the motion away from the rest pose); one Action shared by all pieces = the root joint moves. **Bug fixed**: the
  hex copy (`pd_object_anims`) put the game's keys on rebuilt pieces whose rest pose is identity, so every piece was
  offset again by its rest position (st02's iron roads up to 80 units).
- **Cube maps**: one image per cube map, six faces side by side, each face's mip levels under it (the game's lower
  levels are their own pictures); written as six 128-byte-aligned faces with the cube bit. The 16-bit textures
  (B5G6R5, B4G4R4A4, B5G5R5A1) are now images too: no texture of a stage file is kept from the game file any more
  (the export report counts them).

Proof (<local proof folder>, `scripts/compare_items.py`; findings notes/p2-stage-sections.md):
on all 21 stage files (PC, cycles u1 and u3), six Xbox maps and Ascension, every item compares the same (sprites as
the game makes them; every stage-model animation sampled at every frame, max 0.00012 units; every broken piece's
vertices at every frame, max 0.013 units; enter lights; cube faces at every mip); no game-file texture is kept;
edit and undo of each item behave (18 of 18). Engine: the game's files with only these sections rebuilt draw
pixel-identical (st02, st05).

### Mip levels and texture formats (branch `r-mips`, 2026-11-26; fallback off)

Operator report: on st08 the tower's ring platform shows a different texture in the rebuild at a distance.

**Cause.** The import kept only each texture's top mip level (Blender's `.dds` loader reads level 0), and the export
made the lower levels again by a 2 x 2 box reduction. The game's lower levels are pictures of their own: survey of
the original files only (`<local proof folder>`, every stage `.alr`, no Blender), **579 of
the 1400 multi-level textures of the 2017 PC files** (all 30 stage/area files) have a level that differs from the
box reduction of the level above by more than 6/255 mean per channel (DXT noise of a box reduction measures 1-5);
the original Xbox files give the same 579 of 1400 (their compressed textures are the same bytes). The game samples
the lower levels at a distance (st08 `ta105s_0`, the ring: levels 1-8 were 7 to 24 off). The export also wrote
the uncompressed textures it had imported as DXT: `0x85` B5G6R5 (`cloud_color3`, `e3o_glowup02`), `0x86` B8G8R8A8
(`e3o_tower`, `e3a_emita01/10`, `e3a_glare01`, ...) and DXT3 `0x0E` as DXT5; and one DXT1 texture with
transparent texels (`e3o_para03`) as DXT5.

**Fix** (`pdstage/texlevels.py`, `visuals._mip_image`, `visuals_export.game_texture`):

- Import: levels 1 .. n-1 of every plain texture become one Blender image `<name> mips` (level 1 at the top, each
  next level under it, left-aligned), linked from the texture's image as `pd_mip_image` (cube maps keep p2's
  layout). Each level is loaded through Blender's own `.dds` reader, like level 0. `pd_texture_storage` is now the
  game's format (`dxt1`, `dxt3`, `dxt5`, `b8g8r8a8`, `b5g6r5`, `b4g4r4a4`, `b5g5r5a1`; old scenes' `plain` reads as
  `b8g8r8a8`), `pd_texture_swizzled` marks the Xbox release's uncompressed rows.
- Export: an imported texture is written in its own format and level count; uncompressed formats stay uncompressed
  (linear, or swizzled when imported from the Xbox release). **Rule for the lower levels:** they come from the
  `mips` image while the texture's image is still the imported picture: not painted in this session
  (`is_dirty`), not replaced by a file (still packed), the same size, and the `mips` image has the layout's size.
  Otherwise they are made from level 0 (box reduction). Painting the `mips` image itself is written as painted.
  **Image > Regenerate Mip Levels** (Image Editor) makes them again from level 0 on demand, and a save handler does
  it for painted images before Blender re-packs them on save (so a saved, reopened file stays consistent).
- One Blender image per texture within an import: the stage, object, sky and texture-table imports each had their
  own cache, so a texture used by the stage and an object became two images (`ta105s_0`, `ta105s_0.001`) for one
  texture number, and the export wrote whichever came last (a picture painted on the other was lost). st08: 84
  images -> 59.

**Proof** (`<local proof folder>`; code `afa3712`; scope as the operator set it: st08, st01, st17, st22):

| map | formats differing before -> after | worst lower level (>= 4 x 4 texels), mean 0-255, before -> after | render 4:3 mean (max), before -> after | wide mean (max) |
|---|---|---|---|---|
| st08 | 6 -> 0 | 105.5 -> 2.09 | 3.56 (8.29) -> 0.27 (0.44) | 2.45 (5.06) -> 0.24 (0.33) |
| st01 | 3 -> 0 | 37.1 -> 0.63 | 2.24 (3.60) -> 0.40 (0.80) | 1.76 (2.53) -> 0.41 (1.05) |
| st17 | 4 -> 0 | 63.8 -> 2.86 | 2.09 (3.39) -> 1.04 (2.31) | 1.73 (2.89) -> 0.79 (1.74) |
| st22 | 3 -> 0 | 37.1 -> 7.56 (one 4 x 8 level of `b_tu_c_14s_0`: two DXT1 blocks; 0 since `r-fixes2`'s 3-colour mode) | 2.24 (5.13) -> 0.96 (3.41) | 1.72 (3.92) -> 0.77 (2.42) |

- Per level (`scripts/mipcmp2.py`, every texture, every level, cube faces included): top levels unchanged (worst
  1.56-2.00, as before); levels under 4 x 4 texels within 8.6. u1 -> u3 stable (worst lower level 1.31).
- st08 ring platform close-ups (`ring_near`, `ring_far`): 2.33 / 3.07 -> 0.26 / 0.28. corner_c 8.29 -> 0.31,
  overview 4.28 -> 0.22.
- Edit rule in Blender (`scripts/rb_mips.py`): painting `ta105s_0` changes only that texture in the export; its
  levels come out as box reductions of the painted level 0 (2.9-5.0, DXT noise); every other texture is unchanged.
- Offline (`tests/texlevels_test.py`, 3012 textures of the PC and Xbox files): every uncompressed level re-encodes
  to the game's bytes and format byte; DXT levels within 4 (levels under 4 x 4: 9.69 at worst).
- Field comparison (plugin-pi's scripts, u1/u3): no regression on the four maps; the only difference is that
  `cloud_color3`, `e3o_glowup02`, `e3o_tower` now come out byte-identical (written from the Blender pixels in the
  game's format, not copied).
- Controls: original rendered twice 0.00; a broken `.alr` laid in the same way 43.8 (the mod is loaded; absolute
  `community_mods_dir`). Sheets: `eng/sheet_pc_<st08|st01|st17|st22>_<4x3|wide>.png`, `eng/sheet_ctl_st08_*.png`
  (original | before c7ab959 | after | diffs).

Still differing (not mips): st17's lit windows in corner_a/b (2.1-2.3) and st22's road at spawn 2 (3.4) remain;
not looked into in this round.

### Pre-existing failures from the bloat review (branch `r-fixes2`, 2026-11-26)

Proof: <local proof folder> (scripts/, s1/, s3/; hash sets out/t2-t4.sha against plugin-ps's out/ref.sha; the
six untouched round trips pc st03, st08, st09, st09_05, st24 and Ascension st03, cycles u1-u3, fallback off).

1. **DXT1 3-colour mode** (`6c3b321`, `pdstage/dxt.py`). `tests/texlevels_test.py` failed on `b_tu_c_14s_0`
   level 7 (st12, st22; PC and Xbox): the game's block is in DXT1's 3-colour mode (c0 <= c1: colour 0, colour 1 and
   their midpoint, all opaque), three exact colours the 4-colour-only encoder could not hit (mean 7.56). The export
   was wrong, not the test: DXT1 blocks (opaque and the opaque blocks of 1-bit alpha textures) now also try the
   3-colour mode and keep it where the squared error is strictly lower; DXT3 / DXT5 colour halves stay 4-colour
   (they always decode so). Level 7 is now byte-identical; worst re-encode error over the 3012 PC + Xbox textures
   9.69 -> 3.50, 0 failures. Round trips: every .dat identical; the .alr changes only inside DXT1 textures (st03 45033
   bytes, st08 30003, st09 12084, st09_05 90630, st24 109664, Ascension 64842; nothing outside texture data). Per
   texture against the original's decode (`s1/tex_cmp.py`, u1): better on 24/24 (st03), 38/38 (st08), 13/14 (st09),
   43/43 (st09_05), 45/46 (st24), 26/28 (Ascension); summed mean |diff| 1.63 -> 0.66, 2.15 -> 1.88, 0.76 -> 0.46,
   6.03 -> 4.51, 6.34 -> 5.04, 2.53 -> 1.74; u3 the same. The few worse ones (`e3o_04sea01` +0.002, `e3m_noise02`
   u3 +0.09, Ascension `pd_st22_clou` / `pd_st22_shap` +0.1) are textures whose lower levels the export makes again
   by box reduction instead of taking the game's (ref already 0.26-0.33 per level on `pd_st22_clou`; written by
   `game_texture` from the imported levels it comes out at 0.000-0.005): the game made those levels with a 4-colour
   encoder, which the old encoder imitated. That those textures lose their game levels is open.
2. **Copy-back fallback** (`3bba0a0`). (a) A moved effect: since the effects became named fields, the fallback
   rebuilt the whole EF00 table from the empties, so other entries changed by float rounding (st03 35 bytes, st24
   4). `effects_export.in_game_order`: with the fallback on, each built entry equal to a base-file entry up to
   rounding keeps that entry's bytes and place, the moved ones take the places nothing matched (same count only).
   Now 2 bytes on both maps. (b) A moved stage mesh: `visuals_export.gather` returns `dict(meshes, nodes)` for a
   model with joints (since the stage joints), and `model_inputs` / `model_digests` skipped anything not a list, so
   no per-object digest existed, `_patch_moved_meshes` saw no edited object and bailed out (the .alr was rebuilt,
   32 KB smaller). `_model_meshes` reads both shapes. Now patched in place: 73 bytes change on st03 (the mesh's 52
   own vertices +2.0 units, its record's centre / box), no other vertex. Suite (`fb/t4`): 26 of 26 pass on st03
   and st24 (was 22). The default export is unaffected: t2 (this commit) is byte-identical to the reference set on
   all 36 files.
3. **DXT1 cube maps decoded with the GPU's 565 rule** (merge of `r-slim-cubedxt`, `072a25d`). The old cube decoder
   expanded 565 colours as floor(c * 255 / 31): against bit replication (the D3D / NV2A rule, and dxt.py's) it is
   0 or 1 low on 15 of 32 red/blue and 30 of 64 green values (mean -0.07 to -0.34 per channel over the envmaps);
   the engine's own decoder (`phantom-formats` texture.rs, round(c * 255 / 31)) differs from replication on 4 of 32
   and from floor on 15. Every cube texel decoded with the GPU rule, original vs output (`s3/cube_cmp.py`):

   | map | mean abs diff before -> after | exact texels | max |
   |---|---|---|---|
   | st03 (u1 / u3) | 0.098 -> 0.093 / 0.099 -> 0.093 | 94.9% -> 95.3% | 8 -> 6 / 8 -> 8 |
   | st08 | 0.024 -> 0.022 / 0.025 -> 0.023 | 98.6% -> 98.7% | 9 -> 6 |
   | st24 | 0.065 -> 0.060 / 0.068 -> 0.062 | 96.8% -> 97.0% | 9 -> 8 |
   | Ascension st03 | 0.098 -> 0.093 / 0.099 -> 0.093 | 94.9% -> 95.3% | 8 -> 6 / 8 -> 8 |

   Closer on every map and cycle (also on ps's own before/after pair without fix 1: st03 0.106 -> 0.101). Only the
   `envmap` bytes change (st03 103 bytes, st08 23, st24 42); st09 / st09_05 (no cube map) and every .dat identical.
   A difference of at most 1/255 per channel is not visible in an engine render, so none was made.

### Combined branch `roundtrip-int` (2026-11-25): r-p1 + r-p2 + r-p3 + r-p4, rebuild-only numbers

**All numbers in this section are rebuild-only: the copy-back option ("Preserve unedited parts") was off in every
export.** Code: branch `roundtrip-int` (commit 09b7c8f for every table and picture below). Proof:
<local proof folder> (scripts, `rb/summary.md`, `eng/sheet_*.png`).

**Merge decisions** (one representation per feature):

- Town per-draw light lists: **p3's Blender light linking** (collection `Town_Lights`, one light per light-list
  record; each light's receiver collection = the draws it lights) replaces p1's `pd_draw_lights` number list. Light
  linking is real Blender data and also writes the `.dat` light list itself (p1 kept only numbers into it); every
  joint's draws share one list on all 2,932 town joints (p3 survey), i.e. the lists were authored per object, which
  is what light linking is. No object model of `st09.alr` has a light list (survey: only roots 0/1 of `st09` and
  roots 0-2 of the areas), so p1's object-model lists were not needed. Changed after the merge: the lights keep the
  game's own numbers (p3 renumbered them in list order, which broke the props kept as the game's: `st09_03`'s props
  name the hub's lights 48 and 63) and each light's name starts with its place in the list, so the written list and
  every draw's lights keep the game's order (the game's draws list their lights in list order, which is not number
  order: `st09` lists 36 before 35, `st09_05` and `st09_07` likewise). Result: the raw draw light bytes of `st09`
  are the game's; all 9 town files: same records, same set and order per draw.
- The `.dat` 0xFC light list: battle maps keep **p2's `Enter Lights`**; the town's is `Town_Lights` (one
  collection, one writer per map). Survey of the 9 town streams: every record explicit-index, kinds 2 and 5 only,
  zero vectors, so both writers are lossless there.
- Sky dome: **p3's** root-2 meshes on the general joint empties (`pd_joint`, the same for every root; needed for
  the town's draw instances anyway) replace p1's separate `pd_sky_joint` empties. Kept from p1: a map whose root 2
  is empty (st09, st32) gets no sky (the add-on's preset sky only on request).
- Game materials keep their maps when **either** rule says so (p4: every shader the export writes from game
  settings; p1: a normal / reflection slot or a highlight colour: the town's dbts, lbts). Object normals: p1's
  (p4 had the same fix).
- 16-bit textures: p3's per-level decoder in `alr.texture_dds` (p1's and p2's decoders dropped), so the images also
  carry p4's level count and storage. `compress()`: p4's no-cut-out rules, p1's black-transparent rule and p2's
  cube-map arguments together. Objects: p2's piece Actions with p4's per-placement class, sounds and root values.

**Fixes found by the combined measurement**: sprite entries the loader makes no pool for (capacity 0) are kept when
their texture is in the `.alr` (p2 dropped them as "ignored", but the rain streaks of families 3 and 9 draw sprite
40, `e3a_drop01`, capacity 0, Xbox 0x105410: the engine drew white quads over st03 / st13 / st23); specular power
kept as the game has it, also 0 (st08's svcal came back 0 -> 1).

**Object shadow volumes** (operator finding: breakable objects lost their shadows, e.g. Spiral Highway's tall walls,
the Palace catwalk and pillar). Each object model carries its own shadow volume (shader `sshadow`, `sshadowch` or
`sshadowc`, on a joint of its own: under the intact root, under each broken piece, under the debris root), drawn by
the stencil shadow pass and gone with the intact model when the object breaks; the import skipped every `sshadow*`
mesh, so the rebuild had none. Now each volume is a mesh part with the game's shadow material (`shadow_<name> N` on
the placement, `<piece> shadow N` under a piece, `debris_shadow_<name> N` with the debris), flat faces (each face's
normals turned by the joint as the game turns them); the zero-area edge strips the game stretches into the volume's
sides are left out on import and made again on export for `sshadow` / `sshadowch` (`sshadowc` is already
stretched), on every edge whose two faces have different normals. Field check (`scripts/shadowcmp.py`, per
placement and state: shader, faces as rounded positions, every corner normal within 2 degrees, joint depth): see
the "object shadow volumes" column. Strip counts are not equal: some maps' files also hold strips between two faces
of one normal (st02 47,148 vs 43,124 written; st03 33,388 vs 32,944), which stretch to zero area either way; no rule
in the data tells which, and they draw nothing.

**Per map** (field comparison with the workers' own scripts: p2 `compare_items`, p3 `compare_dropped`, p1 material
audit, p4 placements and what the game reads from the `.dat`; "copied" = vertex buffers byte-identical to the game
file's; renders: mean abs difference per channel 0-255 vs the original, six views, prebuilt engine):

| group | map | fields equal (u1 vs original) | object model roots: placements differing (open, p4 E/F) | object shadow volumes equal (placement states) | still copied from the game file | u3 = u1 (fields) | joints r0/r1/r2 | render mean 4:3 / wide (6 views) |
|---|---|---|---|---|---|---|---|---|
| pc | st01 | yes | same | - | .alr roots 21 roots (all MD00 slot models) | yes | 0:Y 2:Y | 2.24 (max 3.60) / 1.76 (max 2.53) |
| pc | st02 | yes | 48 of 410 | 286/286 | .alr roots 16 roots (all MD00 slot models) | yes | 0:flags 1:Y 2:Y | 1.29 (max 3.66) / 1.05 (max 2.80) |
| pc | st03 | yes | same | 270/270 | .alr roots 27 roots (all MD00 slot models) | yes | 0:flags 2:Y | 0.96 (max 1.31) / 0.83 (max 1.18) |
| pc | st04 | yes | 92 of 272 | 280/284 | .alr roots 26 roots (all MD00 slot models) | yes | 0:Y 1:Y 2:Y | 0.91 (max 1.46) / 0.92 (max 1.57) |
| pc | st05 | yes | 22 of 119 | 114/114 | .alr roots 21 roots (all MD00 slot models) | yes | 0:flags 2:Y | 0.46 (max 0.63) / 0.37 (max 0.49) |
| pc | st06 | yes | 2 of 535 | 290/290 | .alr roots 18 roots (all MD00 slot models) | yes | 0:flags 2:Y | 1.21 (max 1.70) / 1.08 (max 1.32) |
| pc | st07 | yes | same | - | .alr roots 8,12,13,14,15 (all MD00 slot models) | yes | 0:flags 2:Y | 0.97 (max 2.08) / 0.82 (max 1.61) |
| pc | st08 | yes | 16 of 49 | - | .alr roots 49 roots (all MD00 slot models) | yes | 0:flags 1:flags 2:Y | 3.56 (max 8.29) / 2.45 (max 5.06) |
| pc | st09 | NO: collision: 8377 triangles, 2 not matched | same | - | .alr roots 8 (all MD00 slot models) | yes | 0:flags | - |
| pc | st09_01 | yes | - | - | .alr roots 2,3,4 (not MD00: [2, 3, 4]); area .dat except its light list | yes | 0:Y 1:Y 2:Y | - |
| pc | st09_02 | yes | - | - | .alr roots 6 roots (not MD00: [2, 3, 4, 5, 6, 7]); area .dat except its light list | yes | 0:Y 1:Y 2:Y | - |
| pc | st09_03 | yes | - | - | .alr roots 6 roots (not MD00: [2, 3, 4, 5, 6, 7]); area .dat except its light list | yes | 0:Y 1:Y 2:Y | - |
| pc | st09_04 | yes | - | - | .alr roots 2,3,4 (not MD00: [2, 3, 4]); area .dat except its light list | NO joints 0 | 0:Y 1:Y 2:Y | - |
| pc | st09_05 | yes | - | - | .alr roots 2,3,4,5,6 (not MD00: [2, 3, 4, 5, 6]); area .dat except its light list | yes | 0:Y 1:Y 2:Y | - |
| pc | st09_06 | yes | - | - | .alr roots 2,3,4,5,6 (not MD00: [2, 3, 4, 5, 6]); area .dat except its light list | yes | 0:Y 1:Y 2:Y | - |
| pc | st09_07 | yes | - | - | .alr roots 12 roots (not MD00: [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]); area .dat except its light list | yes | 0:Y 1:Y 2:Y | - |
| pc | st09_08 | NO: materials: 1 {'sshadow': 1}
| pc | st12 | yes | 48 of 410 | 286/286 | .alr roots 16 roots (all MD00 slot models) | yes | 0:flags 1:Y 2:Y | 0.70 (max 1.19) / 0.54 (max 0.95) |
| pc | st13 | yes | same | 270/270 | .alr roots 27 roots (all MD00 slot models) | yes | 0:flags 2:Y | 1.04 (max 1.46) / 0.94 (max 1.31) |
| pc | st14 | yes | 92 of 272 | 280/284 | .alr roots 25 roots (all MD00 slot models) | yes | 0:Y 1:Y 2:Y | 0.80 (max 1.28) / 0.77 (max 1.33) |
| pc | st15 | yes | 22 of 119 | 114/114 | .alr roots 21 roots (all MD00 slot models) | yes | 0:flags 2:Y | 0.39 (max 0.55) / 0.32 (max 0.43) |
| pc | st16 | yes | 2 of 535 | 290/290 | .alr roots 16 roots (all MD00 slot models) | yes | 0:flags 2:Y | 1.24 (max 2.50) / 1.09 (max 1.98) |
| pc | st17 | yes | same | - | .alr roots 11,12,13,14 (all MD00 slot models) | yes | 0:flags 2:Y | 2.09 (max 3.39) / 1.73 (max 2.89) |
| pc | st22 | yes | 48 of 410 | 286/286 | .alr roots 15 roots (all MD00 slot models) | yes | 0:flags 1:Y 2:Y | 2.24 (max 5.13) / 1.72 (max 3.92) |
| pc | st23 | yes | same | 270/270 | .alr roots 27 roots (all MD00 slot models) | yes | 0:flags 2:Y | 0.57 (max 0.79) / 0.50 (max 0.71) |
| pc | st24 | NO: materials: 1 {'sshadow': 1}
| pc | st25 | yes | 22 of 119 | 62/62 | .alr roots 23 roots (all MD00 slot models) | yes | 0:Y 2:Y | 0.36 (max 0.51) / 0.29 (max 0.42) |
| pc | st26 | yes | 2 of 535 | 290/290 | .alr roots 17 roots (all MD00 slot models) | yes | 0:flags 2:Y | 0.92 (max 1.24) / 0.83 (max 1.17) |
| pc | st32 | yes | same | - | .alr roots 8 (all MD00 slot models) | yes | 0:Y | 0.36 (max 0.68) / 0.24 (max 0.48) |
| xb | st01 | yes | same | - | .alr roots 21 roots (all MD00 slot models) | yes | 0:Y 2:Y | 2.24 (max 3.60) / 1.76 (max 2.53) |
| xb | st02 | yes | 48 of 410 | 286/286 | .alr roots 16 roots (all MD00 slot models) | yes | 0:flags 1:Y 2:Y | 1.29 (max 3.66) / 1.05 (max 2.80) |
| xb | st04 | yes | 92 of 272 | 280/284 | .alr roots 26 roots (all MD00 slot models) | yes | 0:Y 1:Y 2:Y | 0.91 (max 1.46) / 0.92 (max 1.57) |
| xb | st06 | yes | 2 of 535 | 290/290 | .alr roots 18 roots (all MD00 slot models) | yes | 0:flags 2:Y | 1.21 (max 1.70) / 1.08 (max 1.32) |
| xb | st07 | yes | same | - | .alr roots 8,12,13,14,15 (all MD00 slot models) | yes | 0:flags 2:Y | 0.97 (max 2.08) / 0.82 (max 1.61) |
| xb | st08 | yes | 16 of 49 | - | .alr roots 49 roots (all MD00 slot models) | yes | 0:flags 1:flags 2:Y | 3.56 (max 8.29) / 2.45 (max 5.06) |
| xb | st09 | NO: collision: 8377 triangles, 2 not matched | same | - | .alr roots 8 (all MD00 slot models) | yes | 0:flags | - |
| asc | st03 | yes | same | - | .alr roots 27 roots (all MD00 slot models) | yes | 0:flags 2:flags | 0.11 (max 0.21) / 0.09 (max 0.19) |

Notes: "object model roots" (hits / damage / debris / piece count differ on some placements) is the open p4 item
E/F (object shadow joints, stairs as one piece), equal to or better than p4's own numbers (st05 22 vs 24). st09's 2
"unmatched" collision triangles are the same triangles across a 0.01 rounding step (-463.29 vs -463.28). Joint
"flags" on root 0 = the joint that held the shadow volumes loses bit 0x04 (no reader, p3). st09_04 / st09_08 u3
joints drift ~0.002 rad near 90 degrees (Euler from Blender's float matrix; p3 saw the same). st24 / st09_08 lose one
`sshadow` material (pre-existing: p4 / p1). Still copied: the MD00 slot models (as expected) and the town areas'
roots 2+ (props) with the rest of the area `.dat`; no other root or section.

**Renders against the best single branch** (no regression; every map at or below its best worker score):

| map | merged (4:3, 6 views) | best single branch | s48 (round start) |
|---|---|---|---|
| st01 | 2.24 | 2.66 (p4) | 12.87 |
| st02 | 1.29 | 1.49 (p1) | 3.38 |
| st03 | 0.96 | 2.63 (p4) | 14.38 |
| st04 | 0.91 | 1.01 (p1) | 1.13 |
| st05 | 0.46 | - | 3.35 |
| st06 | 1.21 | 1.51 (p4) | 1.98 |
| st07 | 0.97 | - | 1.06 |
| st08 | 3.56 | - | 5.65 |
| st12 | 0.70 | - | 1.03 |
| st13 | 1.04 | 3.50 (p4) | 14.49 |
| st14 | 0.80 | - | 1.06 |
| st15 | 0.39 | - | 5.46 |
| st16 | 1.24 | 4.03 (p4) | 11.82 |
| st17 | 2.09 | - | 2.18 |
| st22 | 2.24 | - | 5.02 |
| st23 | 0.57 | 0.94 (p4) | 7.07 |
| st24 | 1.19 | - | 2.67 |
| st25 | 0.36 | - | 3.35 |
| st26 | 0.92 | - | - |
| st32 | 0.36 | - | 24.15 |

Xbox maps (st01, 02, 04, 06, 07, 08: Xbox original without a mod vs the rebuild from the Xbox import) score the
same as the PC ones (the engine does not decode cube maps, the only bytes that differ); Ascension (st03 slot) 0.11
/ 0.09. Controls: the original rendered twice = 0.00 (deterministic), a broken `.alr` laid in the same way = 18.8
(the mod is loaded; absolute `community_mods_dir`).

**Town, real game flow** (story start in each area, characters hidden, the rebuilt `st09` and `st09_NN` laid in
together; p3's area-4 view had scored 4.22 with p1's materials):

| area | merged | p1 (area files only) | broken-file control |
|---|---|---|---|
| 1 | 1.10 | 1.61 | 17.3 |
| 2 | 0.27 | 0.82 | 18.9 |
| 3 | 0.60 | 0.69 | 25.5 |
| 4 | 0.81 | 1.24 | 34.2 |
| 5 | 1.81 | 1.69 | 39.1 |
| 6 | 0.62 | 0.81 | 36.6 |
| 7 | 0.65 | 0.41 | 13.5 |
| 8 | 0.51 | 0.75 | 30.4 |

**Dedicated object-shadow views** (kept in the standard sheet set: `scripts/shadow_sheets.py`, Palace views picked
by `scripts/palace_pick.py`; columns original | rebuilt | control = the rebuild before this fix (28ecf5e, no object
shadows) | original with the object broken | rebuilt with the object broken, and the diffs; 4:3 and wide). The
engine breaks an object with `--hit T:100+P:R` (P = the placement's index in list 0, found in each file by class and
position): the broken columns show the shadow gone in both. Views: **highway** (st02/12/22) the operator's camera
(eye 72.31, 239.83, 205.61, target 71.44, 239.42, 205.31; the engine's preview camera draws 60 degrees across, the
operator's was 45 degrees high) along tall breakable wall `kabeF` (list-0 placement 51) on sunlit road, plus an
overhead wall view and a lamp view (both in shade: kept as controls); **Palace** (st03/13/23) catwalk `bridgeA` and
pillar `poleA`, each the instance and side (of every instance, two cameras along the light script's set-0 light)
where the original and the no-shadow control differ most, i.e. the object's shadow lies on lit ground; st04/14
lockers `rockerA`, st24 bench `nagaisuB`, st05/15/25 sign `kanbanC`, st06/16/26 tank `tankA`. Characters are not
hidden (the battle mode has no switch); they stand at the spawns, out of these views. **Operator view, before ->
after the shadow fix** (mean abs diff vs original, 4:3 / wide): st02 4.42 / 3.20 -> 0.69 / 0.67, st12 2.40 / 1.76 ->
0.63 / 0.61, st22 11.93 / 7.92 -> 1.61 / 1.41; Palace catwalk st03 14.78 -> 0.42, st13 13.90 -> 0.29, st23 7.89 ->
0.16; pillar st03 4.86 -> 0.63, st13 7.03 -> 0.63, st23 3.25 -> 0.36.

| map | view | rebuilt vs original 4:3 / wide | control (no object shadows) 4:3 | broken: rebuilt vs original 4:3 |
|---|---|---|---|---|
| st02 | lamp | 1.19 / 1.10 | 1.19 | 1.19 |
| st02 | operator_wall | 0.69 / 0.67 | 4.42 | 1.06 |
| st02 | wall | 1.29 / 1.13 | 1.51 | 1.29 |
| st03 | catwalk | 0.42 / 0.38 | 14.78 | 1.08 |
| st03 | pillar | 0.63 / 0.55 | 4.86 | 1.55 |
| st04 | lockers | 0.93 / 0.88 | 2.56 | 1.00 |
| st05 | sign | 0.88 / 0.70 | 1.37 | 1.25 |
| st06 | tank | 0.70 / 0.64 | 2.82 | 3.45 |
| st12 | lamp | 0.79 / 0.72 | 0.79 | 0.79 |
| st12 | operator_wall | 0.63 / 0.61 | 2.40 | 1.17 |
| st12 | wall | 0.51 / 0.45 | 0.51 | 0.51 |
| st13 | catwalk | 0.29 / 0.27 | 13.90 | 1.81 |
| st13 | pillar | 0.63 / 0.52 | 7.03 | 2.60 |
| st14 | lockers | 0.73 / 0.69 | 2.80 | 0.80 |
| st15 | sign | 0.81 / 0.65 | 1.26 | 1.08 |
| st16 | tank | 0.90 / 0.81 | 4.12 | 3.31 |
| st22 | lamp | 3.11 / 2.55 | 3.11 | 3.11 |
| st22 | operator_wall | 1.61 / 1.41 | 11.93 | 2.39 |
| st22 | wall | 3.00 / 2.47 | 3.26 | 3.00 |
| st23 | catwalk | 0.16 / 0.16 | 7.89 | 1.10 |
| st23 | pillar | 0.36 / 0.31 | 3.25 | 1.88 |
| st24 | bench | 0.84 / 0.81 | 0.84 | 0.84 |
| st25 | sign | 0.70 / 0.55 | 0.70 | 0.87 |
| st26 | tank | 0.55 / 0.53 | 1.45 | 2.28 |

**Edit and undo** (every edit kind of the harness incl. sky mesh, joint, town light and light link; mode
`alledits`, each export against the untouched export of the same map):

**Checked on 11 of 29 maps** (st01-st09, st12, st14; the batch was stopped there on the operator): 150 edits (48 kinds not applicable were skipped): 144 changed only their own item; 0 undos not equal to the untouched export (bytes, or the same items within 0.01 units / the p2 animation tolerance). The point-light edit changes nothing on maps whose set-0 point slot is off (an position of an off slot is not written): st01, st07, st08, st09, st14.
Exceptions:

- st01 pointlight: changed [], undo identical bytes
- st04 cube: changed ['blob list', 'textures'], undo equal items
- st07 pointlight: changed [], undo identical bytes
- st08 pointlight: changed [], undo equal items
- st09 pointlight: changed [], undo identical bytes
- st14 pointlight: changed [], undo equal items

(pointlight: the moved slot is off on those maps, so nothing is written; st04 cube: the blob difference is the
float residue of the md00anim edit taken back earlier in the same session, not the cube edit.)

**Open**: st02 / st12 / st22 one beam near the iron road (corner views) is missing in every rebuild (p1's too;
object related, not investigated); st08's tower walkway is lit differently (diff 8.3 on corner_c; also in s48);
fine texture noise on grates (DXT re-encoding); MD00 slot models and area props still the game file's roots;
4 broken pieces of the st04 / st14 / st24 sign (class 2-48) whose shadow-volume corners keep a normal other than the
game's; edit / undo not run on 18 of 29 maps.

### Results (fallback off; commit 171cf49 for the tables, the engine pictures and the checks below)

Headless Blender 5.1, every map: import (fallback recording off), export; new scene, import that export, export
(cycle 2); again (cycle 3). "Check" = `tools/check_stage.py` (problems / content differences). "What the game reads"
= `tools/stage_semantics.py` on the `.dat` (spawns, collision triangles, placements in every list with class,
position, turn, collider size and sounds, effects, light script values, MD00, SP00, blob list, enter chunks) and on
the object model roots of the `.alr` (hits, damage, debris values, piece count). Bytes changed is a statistic only.

**2017 PC files**

| Map | Game .dat / .alr | Rebuilt .dat | .alr | Check (problems / content differences) | What the game reads (.dat) | Bytes changed .dat / .alr | Cycle 2 vs 1 | Cycle 3 vs 2 | Cycle 3: what the game reads |
|---|---|---|---|---|---|---|---|---|---|
| st00 | 131,296 / 1,786,752 | 131,296 (+0.0%) | 1,197,376 (-33.0%) | 0 / 3 | same | identical / 1683271 B | identical / 19810 B | identical / 929 B | same |
| st01 | 860,678 / 6,002,816 | 861,898 (+0.1%) | 7,030,592 (+17.1%) | 0 / 57 | differs: placements (106 in lists [0], 29 not matched of 106 (rebuilt has 106)), object model roots (.alr) (MODEL ROOTS: 29 of 106 placements differ (hits/damage/debris values or piece count)) | 836731 B / 6889217 B | 40465 B / 2444622 B | 403 B / 1761676 B | differs: placements (106 in lists [0], 29 not matched of 106 (rebuilt has 106)), object model roots (.alr) (MODEL ROOTS: 29 of 106 placements differ (hits/damage/debris values or piece count)) |
| st02 | 566,128 / 9,823,488 | 596,225 (+5.3%) | 10,912,176 (+11.1%) | 0 / 78 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | 571801 B / 10675060 B | 42490 B / 3570119 B | 3419 B / 2917325 B | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) |
| st03 | 406,243 / 10,680,832 | 389,087 (-4.2%) | 10,759,488 (+0.7%) | 0 / 64 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | 383332 B / 10350369 B | 43674 B / 3167182 B | 1344 B / 1536820 B | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) |
| st04 | 479,232 / 11,186,304 | 467,263 (-2.5%) | 11,659,872 (+4.2%) | 0 / 116 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | 446586 B / 11339944 B | 24828 B / 2887626 B | 671 B / 2189235 B | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) |
| st05 | 450,224 / 12,265,088 | 453,594 (+0.7%) | 12,587,888 (+2.6%) | 0 / 78 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | 421586 B / 12210371 B | 50679 B / 3762748 B | 35787 B / 2421818 B | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) |
| st06 | 360,509 / 11,244,160 | 378,847 (+5.1%) | 10,388,384 (-7.6%) | 0 / 57 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | 332300 B / 10845464 B | 66756 B / 1880205 B | 295 B / 999111 B | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) |
| st07 | 359,477 / 11,936,000 | 429,793 (+19.6%) | 13,558,224 (+13.6%) | 0 / 5 | same | 384114 B / 13186731 B | 100603 B / 4066166 B | 14 B / 1738281 B | same |
| st08 | 479,544 / 12,521,728 | 515,608 (+7.5%) | 14,831,424 (+18.4%) | 0 / 72 | differs: object model roots (.alr) (MODEL ROOTS: 16 of 49 placements differ (hits/damage/debris values or piece count)) | 495616 B / 14588408 B | 52867 B / 6964161 B | 54 B / 6042525 B | differs: object model roots (.alr) (MODEL ROOTS: 16 of 49 placements differ (hits/damage/debris values or piece count)) |
| st09 | 324,287 / 2,534,144 | 369,763 (+14.0%) | 2,925,344 (+15.4%) | 0 / 7 | differs: collision (8377 triangles, 2 not matched), placements (54 in lists [0], 9 not matched of 54 (rebuilt has 54)), object model roots (.alr) (MODEL ROOTS: 9 of 54 placements differ (hits/damage/debris values or piece count)) | 344804 B / 2877807 B | 79534 B / 1053238 B | 17 B / 841924 B | differs: collision (8377 triangles, 2 not matched), placements (54 in lists [0], 9 not matched of 54 (rebuilt has 54)), object model roots (.alr) (MODEL ROOTS: 9 of 54 placements differ (hits/damage/debris values or piece count)) |
| st09_01 | 2,390 / 10,320,896 | 2,390 (+0.0%) | 11,328,864 (+9.8%) | 0 / 3 | same | identical / 11197455 B | identical / 3752060 B | identical / 3752833 B | same |
| st09_02 | 4,319 / 7,897,088 | 4,319 (+0.0%) | 7,975,264 (+1.0%) | 0 / 2 | same | identical / 7687009 B | identical / 2654495 B | identical / 2009927 B | same |
| st09_03 | 4,638 / 8,555,008 | 4,638 (+0.0%) | 8,968,368 (+4.8%) | 1 / 2 | same | identical / 8797695 B | identical / 3892302 B | identical / 2372014 B | same |
| st09_04 | 2,355 / 4,347,008 | 2,355 (+0.0%) | 4,669,696 (+7.4%) | 0 / 2 | same | identical / 4562258 B | identical / 1554949 B | identical / 713075 B | same |
| st09_05 | 2,723 / 10,072,064 | 2,723 (+0.0%) | 11,435,536 (+13.5%) | 0 / 2 | same | identical / 11292085 B | identical / 4124458 B | identical / 2476731 B | same |
| st09_06 | 2,670 / 8,508,928 | 2,670 (+0.0%) | 9,087,648 (+6.8%) | 0 / 2 | same | identical / 8799431 B | identical / 3592986 B | identical / 3206708 B | same |
| st09_07 | 3,730 / 9,368,832 | 3,730 (+0.0%) | 7,736,768 (-17.4%) | 0 / 2 | same | identical / 9138873 B | identical / 2032724 B | identical / 772028 B | same |
| st09_08 | 2,346 / 8,606,976 | 2,346 (+0.0%) | 9,203,616 (+6.9%) | 0 / 2 | same | identical / 9037733 B | identical / 2546472 B | identical / 1769636 B | same |
| st12 | 566,419 / 10,184,192 | 596,517 (+5.3%) | 11,150,768 (+9.5%) | 0 / 77 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | 573266 B / 10805752 B | 42488 B / 3540368 B | 3423 B / 2904403 B | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) |
| st13 | 406,211 / 10,736,000 | 389,055 (-4.2%) | 10,834,496 (+0.9%) | 0 / 65 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | 383224 B / 10471684 B | 43618 B / 3226635 B | 1352 B / 1583551 B | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) |
| st14 | 412,405 / 10,810,496 | 400,439 (-2.9%) | 11,474,016 (+6.1%) | 0 / 115 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | 383727 B / 11193963 B | 24832 B / 2787500 B | 675 B / 2196330 B | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) |
| st15 | 450,224 / 11,473,408 | 453,622 (+0.8%) | 11,796,000 (+2.8%) | 0 / 77 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | 421764 B / 11437794 B | 50702 B / 3733448 B | 35788 B / 2414514 B | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) |
| st16 | 360,151 / 12,046,208 | 378,487 (+5.1%) | 10,317,056 (-14.4%) | 0 / 56 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | 329898 B / 11410535 B | 66696 B / 1791543 B | 291 B / 993552 B | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) |
| st17 | 344,679 / 11,645,440 | 414,993 (+20.4%) | 11,860,560 (+1.8%) | 0 / 5 | same | 373912 B / 11545067 B | 100597 B / 3965792 B | 8 B / 1644508 B | same |
| st22 | 565,801 / 10,025,600 | 595,901 (+5.3%) | 11,213,488 (+11.8%) | 0 / 78 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | 566531 B / 10957606 B | 42492 B / 3568284 B | 3419 B / 2926136 B | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) |
| st23 | 402,835 / 10,558,848 | 385,679 (-4.3%) | 10,609,216 (+0.5%) | 0 / 64 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | 380730 B / 10195265 B | 43676 B / 3135006 B | 1349 B / 1383997 B | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) |
| st24 | 320,427 / 9,225,984 | 316,270 (-1.3%) | 9,378,048 (+1.6%) | 0 / 70 | differs: placements (59 in lists [3], 59 not matched of 59 (rebuilt has 59)), object model roots (.alr) (MODEL ROOTS: 59 of 59 placements differ (hits/damage/debris values or piece count)) | 306601 B / 9096420 B | 9043 B / 1141451 B | 112 B / 134337 B | differs: placements (59 in lists [3], 59 not matched of 59 (rebuilt has 59)), object model roots (.alr) (MODEL ROOTS: 59 of 59 placements differ (hits/damage/debris values or piece count)) |
| st25 | 451,980 / 11,589,248 | 455,378 (+0.8%) | 11,835,840 (+2.1%) | 0 / 77 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | 423071 B / 11428784 B | 50852 B / 3722332 B | 35920 B / 2261624 B | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) |
| st26 | 363,210 / 12,246,144 | 382,027 (+5.2%) | 10,465,440 (-14.5%) | 0 / 57 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | 332334 B / 11586205 B | 67692 B / 1852892 B | 293 B / 1011583 B | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) |
| st32 | 41,197 / 1,147,136 | 110,505 (+168.2%) | 1,093,904 (-4.6%) | 0 / 1 | same | 69313 B / 593493 B | 3209 B / 5560 B | identical / 2425 B | same |

**Original Xbox files**

| Map | Game .dat / .alr | Rebuilt .dat | .alr | Check (problems / content differences) | What the game reads (.dat) | Bytes changed .dat / .alr | Cycle 2 vs 1 | Cycle 3 vs 2 | Cycle 3: what the game reads |
|---|---|---|---|---|---|---|---|---|---|
| st00 | 131,296 / 1,786,752 | 131,296 (+0.0%) | 1,197,376 (-33.0%) | 0 / 3 | same | identical / 1670463 B | identical / 20319 B | identical / 906 B | same |
| st01 | 860,678 / 6,002,816 | 861,898 (+0.1%) | 7,030,592 (+17.1%) | 0 / 57 | differs: placements (106 in lists [0], 29 not matched of 106 (rebuilt has 106)), object model roots (.alr) (MODEL ROOTS: 29 of 106 placements differ (hits/damage/debris values or piece count)) | 836731 B / 6889195 B | 40465 B / 2444622 B | 403 B / 1761676 B | differs: placements (106 in lists [0], 29 not matched of 106 (rebuilt has 106)), object model roots (.alr) (MODEL ROOTS: 29 of 106 placements differ (hits/damage/debris values or piece count)) |
| st02 | 566,128 / 9,823,488 | 596,225 (+5.3%) | 10,912,176 (+11.1%) | 0 / 78 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | 571801 B / 10674994 B | 42490 B / 3570119 B | 3419 B / 2917325 B | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) |
| st03 | 406,243 / 10,680,832 | 389,087 (-4.2%) | 10,759,488 (+0.7%) | 0 / 64 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | 383332 B / 10350663 B | 43674 B / 3167182 B | 1344 B / 1536820 B | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) |
| st04 | 479,232 / 11,186,304 | 467,263 (-2.5%) | 11,659,872 (+4.2%) | 0 / 116 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | 446586 B / 11339766 B | 24828 B / 2887626 B | 671 B / 2189235 B | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) |
| st05 | 450,224 / 12,265,088 | 453,594 (+0.7%) | 12,587,888 (+2.6%) | 0 / 78 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | 421586 B / 12210386 B | 50679 B / 3762748 B | 35787 B / 2421818 B | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) |
| st06 | 360,509 / 11,244,160 | 378,847 (+5.1%) | 10,388,384 (-7.6%) | 0 / 57 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | 332300 B / 10845638 B | 66756 B / 1880205 B | 295 B / 999111 B | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) |
| st07 | 359,477 / 11,936,000 | 429,793 (+19.6%) | 13,558,224 (+13.6%) | 0 / 5 | same | 384114 B / 13186503 B | 100603 B / 4066166 B | 14 B / 1738281 B | same |
| st08 | 479,544 / 12,521,728 | 515,608 (+7.5%) | 14,831,424 (+18.4%) | 0 / 72 | differs: object model roots (.alr) (MODEL ROOTS: 16 of 49 placements differ (hits/damage/debris values or piece count)) | 495616 B / 14589606 B | 52867 B / 6964161 B | 54 B / 6042525 B | differs: object model roots (.alr) (MODEL ROOTS: 16 of 49 placements differ (hits/damage/debris values or piece count)) |
| st09 | 324,287 / 2,534,144 | 369,763 (+14.0%) | 2,925,344 (+15.4%) | 0 / 7 | differs: collision (8377 triangles, 2 not matched), placements (54 in lists [0], 9 not matched of 54 (rebuilt has 54)), object model roots (.alr) (MODEL ROOTS: 9 of 54 placements differ (hits/damage/debris values or piece count)) | 344804 B / 2877711 B | 79534 B / 1053238 B | 17 B / 841924 B | differs: collision (8377 triangles, 2 not matched), placements (54 in lists [0], 9 not matched of 54 (rebuilt has 54)), object model roots (.alr) (MODEL ROOTS: 9 of 54 placements differ (hits/damage/debris values or piece count)) |
| st09_01 | 2,390 / 10,320,896 | 2,390 (+0.0%) | 11,328,864 (+9.8%) | 0 / 3 | same | identical / 11197036 B | identical / 3752060 B | identical / 3752833 B | same |
| st09_02 | 4,319 / 7,897,088 | 4,319 (+0.0%) | 7,975,264 (+1.0%) | 0 / 2 | same | identical / 7686922 B | identical / 2654495 B | identical / 2009927 B | same |
| st09_03 | 4,638 / 8,555,008 | 4,638 (+0.0%) | 8,968,368 (+4.8%) | 1 / 2 | same | identical / 8796852 B | identical / 3892042 B | identical / 2371929 B | same |
| st09_04 | 2,355 / 4,347,008 | 2,355 (+0.0%) | 4,669,696 (+7.4%) | 0 / 2 | same | identical / 4563495 B | identical / 1554949 B | identical / 713075 B | same |
| st09_05 | 2,723 / 10,072,064 | 2,723 (+0.0%) | 11,435,536 (+13.5%) | 0 / 2 | same | identical / 11292054 B | identical / 4124458 B | identical / 2476731 B | same |
| st09_06 | 2,670 / 8,508,928 | 2,670 (+0.0%) | 9,087,648 (+6.8%) | 0 / 2 | same | identical / 8799202 B | identical / 3592986 B | identical / 3206708 B | same |
| st09_07 | 3,730 / 9,368,832 | 3,730 (+0.0%) | 7,736,768 (-17.4%) | 0 / 2 | same | identical / 9138873 B | identical / 2032724 B | identical / 772028 B | same |
| st09_08 | 2,346 / 8,606,976 | 2,346 (+0.0%) | 9,203,616 (+6.9%) | 0 / 2 | same | identical / 9037983 B | identical / 2546472 B | identical / 1769636 B | same |
| st12 | 566,419 / 10,184,192 | 596,517 (+5.3%) | 11,150,768 (+9.5%) | 0 / 77 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | 573266 B / 10804652 B | 42488 B / 3540368 B | 3423 B / 2904403 B | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) |
| st13 | 406,211 / 10,736,000 | 389,055 (-4.2%) | 10,834,496 (+0.9%) | 0 / 65 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | 383224 B / 10472049 B | 43618 B / 3226635 B | 1352 B / 1583551 B | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) |
| st14 | 412,405 / 10,810,496 | 400,439 (-2.9%) | 11,474,016 (+6.1%) | 0 / 115 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | 383727 B / 11194293 B | 24832 B / 2787500 B | 675 B / 2196330 B | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) |
| st15 | 450,224 / 11,473,408 | 453,622 (+0.8%) | 11,796,000 (+2.8%) | 0 / 77 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | 421764 B / 11437673 B | 50702 B / 3733448 B | 35788 B / 2414514 B | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) |
| st16 | 360,151 / 12,046,208 | 378,487 (+5.1%) | 10,317,056 (-14.4%) | 0 / 56 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | 329898 B / 11410496 B | 66696 B / 1791543 B | 291 B / 993552 B | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) |
| st17 | 344,679 / 11,645,440 | 414,993 (+20.4%) | 11,860,560 (+1.8%) | 0 / 5 | same | 373912 B / 11545249 B | 100597 B / 3965792 B | 8 B / 1644508 B | same |
| st22 | 565,801 / 10,025,600 | 595,901 (+5.3%) | 11,213,488 (+11.8%) | 0 / 78 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | 566531 B / 10956969 B | 42492 B / 3568284 B | 3419 B / 2926136 B | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) |
| st23 | 402,835 / 10,558,848 | 385,679 (-4.3%) | 10,609,216 (+0.5%) | 0 / 64 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | 380730 B / 10195519 B | 43676 B / 3135006 B | 1349 B / 1383997 B | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) |
| st24 | 320,427 / 9,225,984 | 316,270 (-1.3%) | 9,378,048 (+1.6%) | 0 / 70 | differs: placements (59 in lists [3], 59 not matched of 59 (rebuilt has 59)), object model roots (.alr) (MODEL ROOTS: 59 of 59 placements differ (hits/damage/debris values or piece count)) | 306601 B / 9096519 B | 9043 B / 1141451 B | 112 B / 134337 B | differs: placements (59 in lists [3], 59 not matched of 59 (rebuilt has 59)), object model roots (.alr) (MODEL ROOTS: 59 of 59 placements differ (hits/damage/debris values or piece count)) |
| st25 | 451,980 / 11,589,248 | 455,378 (+0.8%) | 11,835,840 (+2.1%) | 0 / 77 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | 423071 B / 11428423 B | 50852 B / 3722332 B | 35920 B / 2261624 B | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) |
| st26 | 363,210 / 12,246,144 | 382,027 (+5.2%) | 10,465,440 (-14.5%) | 0 / 57 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | 332334 B / 11586249 B | 67692 B / 1852892 B | 293 B / 1011583 B | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) |
| st32 | 41,197 / 1,147,136 | 110,505 (+168.2%) | 1,093,904 (-4.6%) | 0 / 1 | same | 69313 B / 617282 B | 3209 B / 5560 B | identical / 2425 B | same |

**Ascension 0.4 (community map, its own files as the original)**

| Map | Game .dat / .alr | Rebuilt .dat | .alr | Check (problems / content differences) | What the game reads (.dat) | Bytes changed .dat / .alr | Cycle 2 vs 1 | Cycle 3 vs 2 | Cycle 3: what the game reads |
|---|---|---|---|---|---|---|---|---|---|
| st30 | 1,051,324 / 11,190,544 | 865,228 (-17.7%) | 8,794,896 (-21.4%) | 0 / 3 | same | 951850 B / 9455981 B | 6 B / 59973 B | 6 B / 3025 B | same |

**Edit, export, take the edit back in the scene, export** (PC; edits: spawn 1 m, collision mesh 0.5 m, stage mesh
0.2 m, object 1 m, effect 1 m, stage light colour, stage fog start, a point light 1 m, showcase = the biggest stage
mesh 2 m). Undo is compared with the untouched rebuild. The run was stopped at the end of the time budget: maps
without rows were not run.

| Map | Edit | Edit .dat / .alr vs untouched rebuild | Undo .dat / .alr vs untouched rebuild | Check edit / undo | Undo: what the game reads vs game | Size .dat / .alr vs game |
|---|---|---|---|---|---|---|
| st01 | spawn | 10 B / identical | identical / identical | 0 / 0 | differs: placements (106 in lists [0], 29 not matched of 106 (rebuilt has 106)), object model roots (.alr) (MODEL ROOTS: 29 of 106 placements differ (hits/damage/debris values or piece count)) | +0.1% / +17.1% |
| st01 | collision | 150083 B / identical | identical / identical | 0 / 0 | differs: placements (106 in lists [0], 29 not matched of 106 (rebuilt has 106)), object model roots (.alr) (MODEL ROOTS: 29 of 106 placements differ (hits/damage/debris values or piece count)) | +0.2% / +17.1% |
| st01 | visual | identical / 481 B | identical / identical | 0 / 0 | differs: placements (106 in lists [0], 29 not matched of 106 (rebuilt has 106)), object model roots (.alr) (MODEL ROOTS: 29 of 106 placements differ (hits/damage/debris values or piece count)) | +0.1% / +17.1% |
| st01 | object | 2 B / identical | identical / identical | 0 / 0 | differs: placements (106 in lists [0], 29 not matched of 106 (rebuilt has 106)), object model roots (.alr) (MODEL ROOTS: 29 of 106 placements differ (hits/damage/debris values or piece count)) | +0.1% / +17.1% |
| st01 | effect | 2 B / identical | identical / identical | 0 / 0 | differs: placements (106 in lists [0], 29 not matched of 106 (rebuilt has 106)), object model roots (.alr) (MODEL ROOTS: 29 of 106 placements differ (hits/damage/debris values or piece count)) | +0.1% / +17.1% |
| st01 | lighting | 2 B / identical | identical / identical | 0 / 0 | differs: placements (106 in lists [0], 29 not matched of 106 (rebuilt has 106)), object model roots (.alr) (MODEL ROOTS: 29 of 106 placements differ (hits/damage/debris values or piece count)) | +0.1% / +17.1% |
| st01 | fog | 7 B / identical | identical / identical | 0 / 0 | differs: placements (106 in lists [0], 29 not matched of 106 (rebuilt has 106)), object model roots (.alr) (MODEL ROOTS: 29 of 106 placements differ (hits/damage/debris values or piece count)) | +0.1% / +17.1% |
| st01 | pointlight | identical / identical | identical / identical | 0 / 0 | differs: placements (106 in lists [0], 29 not matched of 106 (rebuilt has 106)), object model roots (.alr) (MODEL ROOTS: 29 of 106 placements differ (hits/damage/debris values or piece count)) | +0.1% / +17.1% |
| st01 | showcase | identical / 2684 B | identical / identical | 0 / 0 | differs: placements (106 in lists [0], 29 not matched of 106 (rebuilt has 106)), object model roots (.alr) (MODEL ROOTS: 29 of 106 placements differ (hits/damage/debris values or piece count)) | +0.1% / +17.1% |
| st02 | spawn | 4 B / identical | identical / identical | 0 / 0 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | +5.3% / +11.1% |
| st02 | collision | 399717 B / identical | identical / identical | 0 / 0 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | +5.3% / +11.1% |
| st02 | visual | identical / 54 B | identical / identical | 0 / 0 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | +5.3% / +11.1% |
| st02 | object | 4 B / identical | identical / identical | 0 / 0 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | +5.3% / +11.1% |
| st02 | effect | 2 B / identical | identical / identical | 0 / 0 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | +5.3% / +11.1% |
| st02 | lighting | 2 B / identical | identical / identical | 0 / 0 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | +5.3% / +11.1% |
| st02 | fog | 2 B / identical | identical / identical | 0 / 0 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | +5.3% / +11.1% |
| st02 | pointlight | 1 B / identical | identical / identical | 0 / 0 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | +5.3% / +11.1% |
| st02 | showcase | identical / 30537 B | identical / identical | 0 / 0 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | +5.3% / +11.1% |
| st03 | spawn | 4 B / identical | identical / identical | 0 / 0 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | -4.2% / +0.7% |
| st03 | collision | 49237 B / identical | identical / identical | 0 / 0 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | -4.2% / +0.7% |
| st03 | visual | identical / 105 B | identical / 6 B | 0 / 0 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | -4.2% / +0.7% |
| st03 | object | 2 B / 6 B | identical / 6 B | 0 / 0 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | -4.2% / +0.7% |
| st03 | effect | 2 B / 6 B | 1 B / 6 B | 0 / 0 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | -4.2% / +0.7% |
| st03 | lighting | 3 B / 6 B | 1 B / 6 B | 0 / 0 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | -4.2% / +0.7% |
| st03 | fog | 9 B / 6 B | 1 B / 6 B | 0 / 0 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | -4.2% / +0.7% |
| st03 | pointlight | 453 B / 6 B | 1 B / 6 B | 0 / 0 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | -4.2% / +0.7% |
| st03 | showcase | 1 B / 11278 B | 1 B / 6 B | 0 / 0 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | -4.2% / +0.7% |
| st04 | spawn | 4 B / identical | identical / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | -2.5% / +4.2% |
| st04 | collision | 65309 B / identical | identical / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | -2.5% / +4.2% |
| st04 | visual | identical / 390 B | identical / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | -2.5% / +4.2% |
| st04 | object | 6 B / identical | identical / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | -2.5% / +4.2% |
| st04 | effect | 2 B / identical | identical / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | -2.5% / +4.2% |
| st04 | lighting | 2 B / identical | identical / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | -2.5% / +4.2% |
| st04 | fog | 2 B / identical | identical / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | -2.5% / +4.2% |
| st04 | pointlight | 1 B / identical | identical / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | -2.5% / +4.2% |
| st04 | showcase | identical / 23201 B | identical / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | -2.5% / +4.2% |
| st05 | spawn | 4 B / identical | identical / identical | 0 / 0 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | +0.7% / +2.6% |
| st05 | collision | 94839 B / identical | identical / identical | 0 / 0 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | +0.9% / +2.6% |
| st05 | visual | identical / 41 B | identical / identical | 0 / 0 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | +0.7% / +2.6% |
| st05 | object | 38897 B / 3900 B | identical / identical | 0 / 0 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | +0.7% / +2.6% |
| st05 | effect | 1 B / identical | identical / identical | 0 / 0 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | +0.7% / +2.6% |
| st05 | lighting | 2 B / identical | identical / identical | 0 / 0 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | +0.7% / +2.6% |
| st05 | fog | 2 B / identical | 2 B / identical | 0 / 0 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | +0.7% / +2.6% |
| st05 | pointlight | 454 B / identical | 2 B / identical | 0 / 0 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | +0.7% / +2.6% |
| st05 | showcase | 2 B / 12846 B | 2 B / identical | 0 / 0 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | +0.7% / +2.6% |
| st06 | spawn | 11 B / identical | identical / identical | 0 / 0 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | +5.1% / -7.6% |
| st06 | collision | 154126 B / identical | identical / identical | 0 / 0 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | +5.2% / -7.6% |
| st06 | visual | identical / 35 B | identical / identical | 0 / 0 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | +5.1% / -7.6% |
| st06 | object | 4 B / identical | 2 B / identical | 0 / 0 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | +5.1% / -7.6% |
| st06 | effect | 4 B / identical | 2 B / identical | 0 / 0 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | +5.1% / -7.6% |
| st06 | lighting | 4 B / identical | 2 B / identical | 0 / 0 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | +5.1% / -7.6% |
| st06 | fog | 7 B / identical | 4 B / identical | 0 / 0 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | +5.1% / -7.6% |
| st06 | pointlight | 7 B / identical | 4 B / identical | 0 / 0 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | +5.1% / -7.6% |
| st06 | showcase | 4 B / 522 B | 4 B / identical | 0 / 0 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | +5.1% / -7.6% |
| st07 | spawn | 4 B / identical | identical / identical | 0 / 0 | same | +19.6% / +13.6% |
| st07 | collision | 121210 B / identical | identical / identical | 0 / 0 | same | +20.9% / +13.6% |
| st07 | visual | identical / 148 B | identical / identical | 0 / 0 | same | +19.6% / +13.6% |
| st07 | object | 1 B / identical | identical / identical | 0 / 0 | same | +19.6% / +13.6% |
| st07 | effect | 2 B / identical | identical / identical | 0 / 0 | same | +19.6% / +13.6% |
| st07 | lighting | 2 B / identical | identical / identical | 0 / 0 | same | +19.6% / +13.6% |
| st07 | fog | 3 B / identical | identical / identical | 0 / 0 | same | +19.6% / +13.6% |
| st07 | pointlight | identical / identical | identical / identical | 0 / 0 | same | +19.6% / +13.6% |
| st07 | showcase | identical / 6404 B | identical / identical | 0 / 0 | same | +19.6% / +13.6% |
| st08 | spawn | 6 B / identical | identical / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 16 of 49 placements differ (hits/damage/debris values or piece count)) | +7.5% / +18.4% |
| st08 | collision | 1757 B / identical | identical / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 16 of 49 placements differ (hits/damage/debris values or piece count)) | +7.5% / +18.4% |
| st08 | visual | identical / 814 B | identical / 36 B | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 16 of 49 placements differ (hits/damage/debris values or piece count)) | +7.5% / +18.4% |
| st08 | object | 1 B / 36 B | identical / 36 B | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 16 of 49 placements differ (hits/damage/debris values or piece count)) | +7.5% / +18.4% |
| st08 | effect | 2 B / 36 B | identical / 36 B | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 16 of 49 placements differ (hits/damage/debris values or piece count)) | +7.5% / +18.4% |
| st08 | lighting | 2 B / 36 B | identical / 36 B | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 16 of 49 placements differ (hits/damage/debris values or piece count)) | +7.5% / +18.4% |
| st08 | fog | 4 B / 36 B | identical / 36 B | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 16 of 49 placements differ (hits/damage/debris values or piece count)) | +7.5% / +18.4% |
| st08 | pointlight | identical / 36 B | identical / 36 B | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 16 of 49 placements differ (hits/damage/debris values or piece count)) | +7.5% / +18.4% |
| st08 | showcase | identical / 7957 B | identical / 36 B | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 16 of 49 placements differ (hits/damage/debris values or piece count)) | +7.5% / +18.4% |
| st09 | spawn | 4 B / identical | identical / identical | 0 / 0 | differs: collision (8377 triangles, 2 not matched), placements (54 in lists [0], 9 not matched of 54 (rebuilt has 54)), object model roots (.alr) (MODEL ROOTS: 9 of 54 placements differ (hits/damage/debris values or piece count)) | +14.0% / +15.4% |
| st09 | collision | 271427 B / identical | identical / identical | 0 / 0 | differs: collision (8377 triangles, 2 not matched), placements (54 in lists [0], 9 not matched of 54 (rebuilt has 54)), object model roots (.alr) (MODEL ROOTS: 9 of 54 placements differ (hits/damage/debris values or piece count)) | +14.9% / +15.4% |
| st09 | visual | identical / 74 B | identical / identical | 0 / 0 | differs: collision (8377 triangles, 2 not matched), placements (54 in lists [0], 9 not matched of 54 (rebuilt has 54)), object model roots (.alr) (MODEL ROOTS: 9 of 54 placements differ (hits/damage/debris values or piece count)) | +14.0% / +15.4% |
| st09 | object | 1 B / identical | identical / identical | 0 / 0 | differs: collision (8377 triangles, 2 not matched), placements (54 in lists [0], 9 not matched of 54 (rebuilt has 54)), object model roots (.alr) (MODEL ROOTS: 9 of 54 placements differ (hits/damage/debris values or piece count)) | +14.0% / +15.4% |
| st09 | effect | 2 B / identical | identical / identical | 0 / 0 | differs: collision (8377 triangles, 2 not matched), placements (54 in lists [0], 9 not matched of 54 (rebuilt has 54)), object model roots (.alr) (MODEL ROOTS: 9 of 54 placements differ (hits/damage/debris values or piece count)) | +14.0% / +15.4% |
| st09 | lighting | 1 B / identical | identical / identical | 0 / 0 | differs: collision (8377 triangles, 2 not matched), placements (54 in lists [0], 9 not matched of 54 (rebuilt has 54)), object model roots (.alr) (MODEL ROOTS: 9 of 54 placements differ (hits/damage/debris values or piece count)) | +14.0% / +15.4% |
| st09 | fog | 337 B / identical | identical / identical | 0 / 0 | differs: collision (8377 triangles, 2 not matched), placements (54 in lists [0], 9 not matched of 54 (rebuilt has 54)), object model roots (.alr) (MODEL ROOTS: 9 of 54 placements differ (hits/damage/debris values or piece count)) | +14.0% / +15.4% |
| st09 | pointlight | identical / identical | identical / identical | 0 / 0 | differs: collision (8377 triangles, 2 not matched), placements (54 in lists [0], 9 not matched of 54 (rebuilt has 54)), object model roots (.alr) (MODEL ROOTS: 9 of 54 placements differ (hits/damage/debris values or piece count)) | +14.0% / +15.4% |
| st09 | showcase | identical / 8478 B | identical / identical | 0 / 0 | differs: collision (8377 triangles, 2 not matched), placements (54 in lists [0], 9 not matched of 54 (rebuilt has 54)), object model roots (.alr) (MODEL ROOTS: 9 of 54 placements differ (hits/damage/debris values or piece count)) | +14.0% / +15.4% |
| st12 | spawn | 4 B / identical | identical / identical | 0 / 0 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | +5.3% / +9.5% |
| st12 | collision | 399648 B / identical | identical / identical | 0 / 0 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | +5.3% / +9.5% |
| st12 | visual | identical / 54 B | identical / identical | 0 / 0 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | +5.3% / +9.5% |
| st12 | object | 4 B / identical | identical / identical | 0 / 0 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | +5.3% / +9.5% |
| st12 | effect | 2 B / identical | identical / identical | 0 / 0 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | +5.3% / +9.5% |
| st12 | lighting | 2 B / identical | identical / identical | 0 / 0 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | +5.3% / +9.5% |
| st12 | fog | 2 B / identical | identical / identical | 0 / 0 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | +5.3% / +9.5% |
| st12 | pointlight | 1 B / identical | identical / identical | 0 / 0 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | +5.3% / +9.5% |
| st12 | showcase | identical / 30537 B | identical / identical | 0 / 0 | differs: placements (410 in lists [0, 2], 2 not matched of 410 (rebuilt has 410)), object model roots (.alr) (MODEL ROOTS: 50 of 410 placements differ (hits/damage/debris values or piece count)) | +5.3% / +9.5% |
| st13 | spawn | 4 B / identical | identical / identical | 0 / 0 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | -4.2% / +0.9% |
| st13 | collision | 49179 B / identical | identical / identical | 0 / 0 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | -4.2% / +0.9% |
| st13 | visual | identical / 105 B | identical / 6 B | 0 / 0 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | -4.2% / +0.9% |
| st13 | object | 2 B / 6 B | identical / 6 B | 0 / 0 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | -4.2% / +0.9% |
| st13 | effect | 2 B / 6 B | 1 B / 6 B | 0 / 0 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | -4.2% / +0.9% |
| st13 | lighting | 3 B / 6 B | 1 B / 6 B | 0 / 0 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | -4.2% / +0.9% |
| st13 | fog | 7 B / 6 B | 1 B / 6 B | 0 / 0 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | -4.2% / +0.9% |
| st13 | pointlight | 1 B / 6 B | 1 B / 6 B | 0 / 0 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | -4.2% / +0.9% |
| st13 | showcase | 1 B / 11231 B | 1 B / 6 B | 0 / 0 | differs: placements (326 in lists [0, 2], 67 not matched of 326 (rebuilt has 326)), object model roots (.alr) (MODEL ROOTS: 67 of 326 placements differ (hits/damage/debris values or piece count)) | -4.2% / +0.9% |
| st14 | spawn | 4 B / identical | identical / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | -2.9% / +6.1% |
| st14 | collision | 65261 B / identical | identical / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | -2.9% / +6.1% |
| st14 | visual | identical / 390 B | identical / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | -2.9% / +6.1% |
| st14 | object | 6 B / identical | identical / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | -2.9% / +6.1% |
| st14 | effect | 2 B / identical | identical / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | -2.9% / +6.1% |
| st14 | lighting | 2 B / identical | identical / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | -2.9% / +6.1% |
| st14 | fog | 3 B / identical | 6 B / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | -2.9% / +6.1% |
| st14 | pointlight | 6 B / identical | 6 B / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | -2.9% / +6.1% |
| st14 | showcase | 6 B / 23201 B | 6 B / identical | 0 / 0 | differs: object model roots (.alr) (MODEL ROOTS: 92 of 272 placements differ (hits/damage/debris values or piece count)) | -2.9% / +6.1% |
| st15 | spawn | 4 B / identical | identical / identical | 0 / 0 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | +0.8% / +2.8% |
| st15 | collision | 94876 B / identical | identical / identical | 0 / 0 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | +0.9% / +2.8% |
| st15 | visual | identical / 41 B | identical / identical | 0 / 0 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | +0.8% / +2.8% |
| st15 | object | 38889 B / 3900 B | identical / identical | 0 / 0 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | +0.7% / +2.8% |
| st15 | effect | 1 B / identical | identical / identical | 0 / 0 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | +0.8% / +2.8% |
| st15 | lighting | 2 B / identical | identical / identical | 0 / 0 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | +0.8% / +2.8% |
| st15 | fog | 5 B / identical | 2 B / identical | 0 / 0 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | +0.8% / +2.8% |
| st15 | pointlight | 449 B / identical | 2 B / identical | 0 / 0 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | +0.8% / +2.8% |
| st15 | showcase | 2 B / 12846 B | 2 B / identical | 0 / 0 | differs: placements (119 in lists [0, 2], 2 not matched of 119 (rebuilt has 119)), object model roots (.alr) (MODEL ROOTS: 24 of 119 placements differ (hits/damage/debris values or piece count)) | +0.8% / +2.8% |
| st16 | spawn | 11 B / identical | identical / identical | 0 / 0 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | +5.1% / -14.4% |
| st16 | collision | 154062 B / identical | identical / identical | 0 / 0 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | +5.2% / -14.4% |
| st16 | visual | identical / 35 B | identical / identical | 0 / 0 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | +5.1% / -14.4% |
| st16 | object | 4 B / identical | 2 B / identical | 0 / 0 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | +5.1% / -14.4% |
| st16 | effect | 4 B / identical | 2 B / identical | 0 / 0 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | +5.1% / -14.4% |
| st16 | lighting | 4 B / identical | 2 B / identical | 0 / 0 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | +5.1% / -14.4% |
| st16 | fog | 7 B / identical | 2 B / identical | 0 / 0 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | +5.1% / -14.4% |
| st16 | pointlight | 5 B / identical | 2 B / identical | 0 / 0 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | +5.1% / -14.4% |
| st16 | showcase | 2 B / 522 B | 2 B / identical | 0 / 0 | differs: placements (535 in lists [0, 2], 26 not matched of 535 (rebuilt has 535)), object model roots (.alr) (MODEL ROOTS: 28 of 535 placements differ (hits/damage/debris values or piece count)) | +5.1% / -14.4% |

**In the engine** (optional external check: a clean-room reimplementation, `--release --features testing`, the files
laid over their slot on the Xbox data, headless battle, 45 ticks, no HUD). Sheets per map at 4:3 (1440 x 1080) and
wide (2560 x 1080): original | rebuilt untouched | edited | undone | difference (rebuilt vs original, x4, with its
score), views spawn 1, spawn 2, overview, three corners: `<local proof folder>`
(outside this repository). Edited / undone columns are empty where the edit run did not reach the map.

| Map | mean abs. difference per channel, 4:3 (6 views: mean / max) | wide (mean) | pixels > 16, worst view |
|---|---|---|---|
| st01 | 12.87 / 32.34 | 10.54 | 49.0 % |
| st02 | 3.38 / 11.99 | 2.53 | 20.4 % |
| st03 | 14.38 / 22.29 | 11.94 | 50.0 % |
| st04 | 1.13 / 1.73 | 1.06 | 2.4 % |
| st05 | 3.35 / 5.96 | 5.23 | 16.0 % |
| st06 | 1.98 / 2.63 | 1.71 | 2.2 % |
| st07 | 1.06 / 2.12 | 0.89 | 4.8 % |
| st08 | 5.65 / 10.32 | 4.15 | 27.3 % |
| st09 | 0.48 / 1.00 | 0.30 | 0.1 % |
| st12 | 1.03 / 1.48 | 0.79 | 0.6 % |
| st13 | 14.49 / 23.02 | 14.49 | 54.6 % |
| st14 | 1.06 / 1.66 | 0.93 | 2.1 % |
| st15 | 5.46 / 8.89 | 10.76 | 20.5 % |
| st16 | 11.82 / 12.99 | 9.34 | 45.6 % |
| st17 | 2.18 / 3.45 | 1.82 | 6.7 % |
| st22 | 5.02 / 15.19 | 3.66 | 20.8 % |
| st23 | 7.07 / 14.73 | 4.62 | 30.8 % |
| st24 | 2.67 / 3.90 | 2.02 | 5.7 % |
| st25 | 3.35 / 5.21 | 6.82 | 17.7 % |
| st32 | 24.15 / 43.78 | 16.13 | 72.5 % |

What the sheets show: st04, st06, st07, st09, st12, st14, st17, st24 within a mean of 3 (texture re-encoding,
the add-on's sky instead of the game's dome); st02 / st22 / st05 / st15 / st25 the sky and lamp glares differ; the
dark wedge over Spiral Highway's road (1.3.0) is gone (fix in `8a8d481`). **Not equivalent yet:** the floors of
Lost / Light / Noble Palace (st03, st13, st23: the parallax / reflection shaders `sbpxrefpal`, `sdrefp`, `sbtsrefp`
come out much darker; cube-map slots were fixed after the run, `519b979`, but a re-export of st03 is still dark),
Edgar's Dream (st01: fog meshes), Sunset Refinery st16, and st32 (its `.dat` grows 41 KB -> 110 KB: the collision is
rebuilt from more triangles than the game's; not investigated).

**Operator review of these sheets (open, found after the run; not fixed this round):**

- st04 spawn pillar: hard seams where the original is smooth, and its shine is missing. Likely the normals (custom
  normals imported, but corners split by Blender's tangents / the per-corner normal encoding) and the material's
  highlight / reflection path (shine mask in vertex alpha, specular, reflection slot). Open.
- Normal maps and material data: audit of the material path end to end still to do (texture roles, reflection and
  cube maps, specular, shine mask, shader parameters). Open.
- st09 (town) darker overall, floor especially: the town's draws use three run-time lights each (light count 3 on
  101 stage draws), written as 0 lights: the most likely cause (FIELD_MAP.md "out of scope"). Not confirmed.
- st02 sky slightly darker: the game's sky dome is replaced by the add-on's sky model (sky settings). Open.
- st03 / st13 / st23 floors much darker (above). Open.

**Behaviour (from what the game reads, no engine run):** spawns, collision, effects, light script, MD00, SP00, blob
list and enter chunks are the same on every PC, Xbox and Ascension stage file (collision: 2 triangles of 8,377 not
matched on the town). Placements: the same on st04, st07, st08, st14, st17 and the area files; up to 67 of 326
differ elsewhere (st24's all, fixed after the run in `de50f4b`: verified on st24). Object model roots: 16-92
placements per map differ in the broken model's piece structure (the game's pieces with sub-joints are written as
one joint per piece) - whether a player can tell was not tested.


## Summary (fallback)

| | Add-on 1.3.0 | This branch |
|---|---|---|
| Untouched round trip, the 30 map files of the 2017 PC game (`st00`-`st09`, the town's 8 area files `st09_01`-`st09_08`, `st12`-`st17`, `st22`-`st26`, `st32`) | 0 byte-identical of the 22 tried; 2 fail (`st00` import, `st09` export); 18 of the 20 written `.alr` files carry a wrong vertex mask | **30 of 30 byte-identical** (`.dat` and `.alr`) |
| The same 30 files of the original Xbox release | not tried | **30 of 30 byte-identical**; its swizzled textures now import right |
| The community map Ascension 0.4 (made with the add-on) as a game original | not tried | byte-identical |
| One edit (spawn, collision, stage mesh, object moved / added / deleted, effect, lighting) on every battle map, export, re-import the export, take the edit back, export | whole file rebuilt; a collision edit alone added 63-330 KB and changed every collision entry; adding or deleting an object dropped the second object layout | only the edited entries change; see "Edit and undo" |
| Optional external check: also loads in another engine (a clean-room reimplementation; headless battle) | yes, with visible damage on several maps | yes; picture sheets per map (below) |

## Bugs found and fixed (first rounds)

1. **Nothing survived an unedited round trip** (commit `ba8ebe5`).
   *Symptom:* importing an original map and exporting it to its own slot rewrote every part: the `.dat` grew (st04
   479,232 -> 650,652 bytes; st02 566,128 -> 1,008,348), the `.alr` grew (st04 11.2 -> 13.6 MB; st08 12.5 -> 17.7 MB);
   placed objects of the second object layout were dropped (st04 272 -> 158 placements, st02 410 -> 216, st06 535 ->
   266), every object got a new name and new model roots while the old ones stayed in the file unused (st04 145 ->
   253 roots); the stage was rebuilt with the four shaders the add-on writes, so shaders it cannot author were
   replaced by `sd` (st01's 270 fog meshes `sdyfog` / `sbtsyfog`, st06's 163 `sbpx` and 3 `sc`, st25's 6 `sc`, `sbpx` and `sbpxrefsal` meshes: its glowing signs, st02's 16 `sv`),
   the shadow volumes were rebuilt (st02 / st22: a large dark wedge over the road in game), the sky was rebuilt from
   the sky settings; spawns, effects and collision came back with float noise (a yaw of pi written as -pi; 1-ulp
   moves). Pictures: `sheet_untouched_roundtrip*.png` (below).
   *Root cause:* the exporter always rebuilds every part from the scene; it has no way to know a part was not edited.
   *Fix:* `roundtrip.py`. The import records, per part, a digest of exactly what the exporter would read from the
   scene for it (the output of the export's own gather functions), with the SHA-1 of the game files. On export, a
   part whose digest is unchanged, exported over the same game files, keeps the game's own bytes. Parts: spawns,
   collision, effects, the stage, background and sky models (each separately), and objects. Finer still:
   - an edited stage or background keeps every game mesh whose Blender object was not edited (its own material,
     shader, vertex format and bytes; `pd_mesh` on the imported objects), and the shadow volumes when the shadow
     casters were not edited;
   - moved spawns, placed objects and effects are written into their own entries; entries not moved (within float
     rounding: 0.001 game units, angles compared as angles, turns compared as rotation matrices) keep their bytes;
   - only placements moved (same object types and models, same placements as imported): written in place, so the
     second object layout, object animations, names and model roots all stay;
   - an object type's model edited (same types and placements as imported): only that type is added as a new type
     (new model roots, a new definition appended to copies of the game's name, definition and sound tables) and its
     placements point at it; every other definition, model root and placement stays.
   Digests round floats to 1e-4 (matrix products leave noise when nothing was edited). The record is a scene custom
   property, so it survives saving the `.blend`. A scene not imported from the slot's own files is exported as before.

2. **Shadow meshes written with the wrong vertex layout** (commit `1bea760`).
   *Symptom:* every exported stage with character shadows had one vertex buffer whose attribute mask did not match
   its format: format 0x10 (12 bytes, position) or 0x07 (16 bytes, position + normal) with mask 0xCF (normal, UV,
   colour: 24 bytes). 18 of the 20 exported `.alr` files in the 1.3.0 round trip; also the community map Ascension
   (format 0x07). The 2017 PC game still draws them (its vertex declaration is per format), stricter readers reject
   the file.
   *Root cause:* new and carried-over meshes copy the vertex-buffer entry of an `sd` template; the mask was only set
   for formats 0x01, 0x03, 0x09, 0x0B and 0x1F.
   *Fix:* the table of the 19 vertex formats the game's files use (one stride and mask per format in every `.alr` of
   the Xbox and 2017 PC releases); unknown formats keep their own buffer's mask.

3. **`st00` could not be imported** (`IndexError` in `dat.collision`) (commit `ba8ebe5`).
   *Root cause:* `st00.dat` has a short 0x28-byte `ST00` header (the game never loads it) and the town's
   `st09_NN.dat` are `AR0x` area files; the readers assumed the 0x13C-byte battle-stage header. Exporting over such a
   file would also have written placement counts into its data (`clear_placements` at header 0x30..0x58).
   *Fix:* `dat.layout_kind()`; the import skips the tables those files do not have; the export refuses to write
   stage tables into them and keeps the file.

4. **`st09` (the town) could not be exported** ("base .alr has no sd format-0x01 mesh") (commit `ba8ebe5`).
   *Root cause:* new meshes copy unknown fields from an `sd` mesh of the replaced map; the town has none.
   *Fix (untouched parts):* an untouched round trip no longer builds meshes, so it no longer needs one. Still open
   when a mesh of the town itself is edited (see below).

5. **Character export changed the win/lose pose loops** (commit `4a6c4e7`).
   *Symptom:* importing `pc05a` and exporting it over itself with no edits changed `charaset.dat` and
   `charaset_en.dat`: record +0x40 went from 50 / 40 to 176 / 154.
   *Root cause:* +0x40 was taken for the six exmot clip lengths. It is, per clip, the length L of the end range
   the fighter keeps playing while the pose is held (the call that reads it plays the range (length - L, length);
   L = 0: the clip holds its last frame; from notes on the game's code for that call). In every record of
   the game it is far shorter than the clip (pc00a-pc10a: 30-74 for clips of 150-210 frames), and only the first
   two are set. Writing the clip length made the held range the whole clip.
   *Fix:* keep the value of the battle character the animations came from (else the target's own), never longer
   than the new clip.

6. **Jump pads lost their own power** (commit `ba8ebe5`).
   *Symptom:* in Sein (st08) three of the four jump pads have power 250 and one 200; after any export that wrote the
   placements they all had 200.
   *Root cause:* the pads share one model, so the import puts them in one type collection whose Jump power is the
   first pad's; the export writes the collection's power into every pad.
   *Fix:* a pad imported with another power than its collection's keeps its own (`pd_jump_power` on the object);
   the collection's setting still drives the others.

7. **A moved effect lost its area selector** (commit `ba8ebe5`).
   *Root cause:* imported effects are written with `effects_build.place()`, whose `layout_filter` (entry byte 1)
   defaults to 0. Byte 1 selects when the entry plays; it is 0 in every battle map, but 7-14 in the town (st09, one
   value per area), so a re-written town effect played in every area.
   *Fix:* an imported effect keeps its own byte 1.


8. **A collision edit rebuilt the whole collision table** (commits `a707fe5`, `06a8605`).
   *Symptom:* raising one collision mesh by 0.5 m on st01 appended a rebuilt block of all 3,009 triangles (+126 KB;
   every one of the 2,017 entries of the moved surface type, and the chunking of all the others, different from the
   game's); 63-330 KB on the other maps.
   *Root cause:* the export only knows "collision edited" and then runs `collision_build.build_block()` on the
   whole scene.
   *Fix:* `collision_build.patch()`. The scene's triangles are matched with the file's (per surface type in file
   order, as the import gives them back; by position when triangles were added or removed). Untouched triangles
   and records keep their bytes and order. A moved triangle keeps its place and attribute word; a vertex only moved
   triangles use is moved in the vertex list; a vertex shared with collision that stays is left, and the moved
   triangles get one appended. When nothing grows (no triangle added or removed, no shared vertex) everything is
   written in place and the file keeps its size (st02, st16, st22, st26, st32 in the table). The vertex list is the
   last record of a block packed between other tables, so a grown list cannot stay in place: the same records are
   then appended once as a block (header `0x94` and `0x138`), the game's own block left unused. Exporting on top of
   such a file, values back within 0.002 of the game's own block take its bytes, and when the block is the game's
   again `0x94` points back at it and the appended copy is cut off: the undo gives the game's file back.
9. **A moved stage mesh lost its game shader** (commit `06a8605`).
   *Symptom:* moving one stage or background mesh rebuilt it with the add-on's four shaders (st06's `sbpx` / `sc`,
   st01's fog meshes, st25's glowing signs became `sd`) and re-laid its root: +3.5 to +70 KB.
   *Fix:* when an imported object's vertices only moved (same faces, UVs, colours, materials, turn and scale as
   imported: a per-object "shape" digest recorded at import), its moved vertices are written into the game's own
   vertex buffer (node space) and the mesh record's centre, radius and box follow. Shader, material and every other
   byte stay; the `.alr` keeps its size. A vertex another mesh shares, a turned or scaled object, or any other
   kind of edit is rebuilt as before (see "Still open").
10. **Adding or deleting an object rebuilt every object and dropped the second object layout** (commits `06a8605`, `4f01398`).
   *Fix:* when every object type is as imported, only the placement list the objects came from is written again:
   its own entries in their order (deleted ones left out), then the added ones (each a copy of a same-type entry
   with its own position and turn). Written where the list is when it fits (deleting only shortens it), else
   appended with its `PS0x` tag; written back at its own place when it fits there again (the copy at the end of
   the file dropped). Names, definitions, models, sounds and the other placement list stay. A copy of an imported
   object (Shift+D carries the original's `pd_placement`) counts as added.
11. **Custom lighting appended a new light script and pointed every variant at it; seven maps refused it** (commits
    `a707fe5`, `06a8605`).
    *Fix:* each light script of the map is edited where it is when it keeps its length (only the colour and
    direction words change; each variant keeps its own script); an argument keeps its encoding when its value is
    unchanged or a whole number the script holds as a short integer (st04's direction has one). Maps whose only
    script is in another variant slot than 0 (st12-st15, st22-st25) failed with "the game original has no lighting
    script"; the first slot that has one is used.
12. **Re-importing an export and exporting again rebuilt everything** (commit `06a8605`).
    *Root cause:* the import's record holds the SHA-1 of the imported files; the export always builds on the game
    original (the backup), so a scene imported from an earlier export never matched and every part was rebuilt.
    *Fix:* the record also names the imported files; a scene imported from an earlier export of the same slot
    (still holding the bytes it was imported from) is exported on top of that file (`roundtrip.source()`).
13. **Moved values came back with float noise** (commit `06a8605`). Spawns, placements, collision vertices and mesh
    vertices are written as the file's value plus how far the value moved since the import (an import stores each
    value as a 32-bit float of value x scale); a spawn's yaw and orbs, a placement's turn are written only when they
    changed. So moving something back gives the file's value again (except where the move crossed a power of two:
    the export can only hold the moved value in 32 bits). The import keeps the scale as typed (an operator's float
    property holds 0.1 as 0.100000001...).
14. **The original Xbox release's uncompressed textures imported scrambled** (commit `a707fe5`). They are swizzled (the
    format byte lacks the 0x80 the 2017 release sets on its linear textures); `alr.texture_dds()` unswizzles them.
    28 of 28 such textures (st01, st04, st09, st25, st32) then equal the 2017 release's bytes; the compressed
    textures are the same bytes in both releases.
15. **An edited object model was added as a new type every time** (commit `61b107a`). When the model only had
    vertices moved (same faces, UVs, colours, materials: an "object_shapes" digest per model mesh), the moved
    vertices are written into the type's own intact root as for the stage (bug 9); definitions and placements
    stay, and taking the edit back gives the file back.

## Coverage: which files the add-on reads

- **Battle maps and the town hub** (`st01`-`st09`, `st12`-`st17`, `st22`-`st26`, `st32`): read and written (table
  below).
- **`st00`**: a short `ST00` header (0x28 bytes) and no stage tables; the game never loads it as a stage. The add-on
  imports its model file; the `.dat` is kept as it is.
- **The town's area files `st09_01`-`st09_08`** (the eight town areas; `.dat` 2.3-4.6 KB `AR0x` files, `.alr`
  4-10 MB area models): no collision, spawn, object or effect tables (the town's collision and triggers are in
  `st09.dat`). The add-on imports and exports their model file; untouched round trips are byte-identical, and a
  moved area mesh is written into its own vertices (table "Area files").
- **`stNNcam.alr`** (`st01cam`-`st08cam`, 8-33 KB, no `.dat`): ALR containers holding only animation records
  (types 10 and 7 in 18 roots, no meshes, no textures): the camera paths of the map's intro and results, not map
  data. The add-on does not read them, and an export never touches them, so a map exported over a slot keeps the
  slot's own camera paths. They are byte-identical in the Xbox, prototype and 2017 releases.
- **The original Xbox release** (`Map/` of the disc): the `.dat` files are byte-identical to the 2017 release's; the
  `.alr` files differ only in their uncompressed (B8G8R8A8) textures, which are swizzled. With bug 14 fixed the
  add-on reads them like the 2017 files; untouched round trips are byte-identical. Edits export valid files (table
  "Xbox"); new textures are written in the 2017 release's linear form (format byte with 0x80), which the original
  Xbox game was not tested with: the add-on targets the 2017 release.

## Untouched round trips (fallback: import, export, compare)

Headless Blender 5.1.2, the add-on from this branch. Import Game Original's call, then the Export operator's calls
with its defaults. "Check" = an independent reader written from separate format notes (`tools/check_stage.py`):
header words in range, section tags, placements and object definitions, collision chunks and indices, EF00 / CP00
/ MD00 sizes, the ALR header and resource buffer, texture table, every chunk chain, materials / vertex buffers /
draws in range, vertex stride and mask = the format's.

2017 PC release:

| File | Game files (.dat / .alr bytes) | .dat | .alr | Check | Note |
|---|---|---|---|---|---|
| st00 | 131,296 / 1,786,752 | identical | identical | 0 problems, 0 differences | st00.dat has no stage tables (collision, spawns, objects, effects) |
| st01 | 860,678 / 6,002,816 | identical | identical | 0 problems, 0 differences | Stage: 287 meshes, 22450 triangles |
| st02 | 566,128 / 9,823,488 | identical | identical | 0 problems, 0 differences | Stage: 25 meshes, 29044 triangles |
| st03 | 406,243 / 10,680,832 | identical | identical | 0 problems, 0 differences | Stage: 214 meshes, 46215 triangles |
| st04 | 479,232 / 11,186,304 | identical | identical | 0 problems, 0 differences | Stage: 27 meshes, 22148 triangles |
| st05 | 450,224 / 12,265,088 | identical | identical | 0 problems, 0 differences | Stage: 35 meshes, 42567 triangles |
| st06 | 360,509 / 11,244,160 | identical | identical | 0 problems, 0 differences | Stage: 634 meshes, 29411 triangles |
| st07 | 359,477 / 11,936,000 | identical | identical | 0 problems, 0 differences | Stage: 732 meshes, 102958 triangles |
| st08 | 479,544 / 12,521,728 | identical | identical | 0 problems, 0 differences | Stage: 187 meshes, 47979 triangles |
| st09 | 324,287 / 2,534,144 | identical | identical | 0 problems, 0 differences | Stage: 103 meshes, 16481 triangles |
| st09_01 | 2,390 / 10,320,896 | identical | identical | 0 problems, 0 differences | st09_01.dat has no stage tables (collision, spawns, objects, effects) |
| st09_02 | 4,319 / 7,897,088 | identical | identical | 0 problems, 0 differences | st09_02.dat has no stage tables (collision, spawns, objects, effects) |
| st09_03 | 4,638 / 8,555,008 | identical | identical | 1 problems, 0 differences | st09_03.dat has no stage tables (collision, spawns, objects, effects) |
| st09_04 | 2,355 / 4,347,008 | identical | identical | 0 problems, 0 differences | st09_04.dat has no stage tables (collision, spawns, objects, effects) |
| st09_05 | 2,723 / 10,072,064 | identical | identical | 0 problems, 0 differences | st09_05.dat has no stage tables (collision, spawns, objects, effects) |
| st09_06 | 2,670 / 8,508,928 | identical | identical | 0 problems, 0 differences | st09_06.dat has no stage tables (collision, spawns, objects, effects) |
| st09_07 | 3,730 / 9,368,832 | identical | identical | 0 problems, 0 differences | st09_07.dat has no stage tables (collision, spawns, objects, effects) |
| st09_08 | 2,346 / 8,606,976 | identical | identical | 0 problems, 0 differences | st09_08.dat has no stage tables (collision, spawns, objects, effects) |
| st12 | 566,419 / 10,184,192 | identical | identical | 0 problems, 0 differences | Stage: 25 meshes, 29044 triangles |
| st13 | 406,211 / 10,736,000 | identical | identical | 0 problems, 0 differences | Stage: 220 meshes, 46276 triangles |
| st14 | 412,405 / 10,810,496 | identical | identical | 0 problems, 0 differences | Stage: 27 meshes, 22148 triangles |
| st15 | 450,224 / 11,473,408 | identical | identical | 0 problems, 0 differences | Stage: 35 meshes, 42567 triangles |
| st16 | 360,151 / 12,046,208 | identical | identical | 0 problems, 0 differences | Stage: 634 meshes, 29411 triangles |
| st17 | 344,679 / 11,645,440 | identical | identical | 0 problems, 0 differences | Stage: 728 meshes, 99478 triangles |
| st22 | 565,801 / 10,025,600 | identical | identical | 0 problems, 0 differences | Stage: 25 meshes, 29044 triangles |
| st23 | 402,835 / 10,558,848 | identical | identical | 0 problems, 0 differences | Stage: 214 meshes, 46180 triangles |
| st24 | 320,427 / 9,225,984 | identical | identical | 0 problems, 0 differences | Stage: 27 meshes, 7864 triangles |
| st25 | 451,980 / 11,589,248 | identical | identical | 0 problems, 0 differences | Stage: 38 meshes, 42615 triangles |
| st26 | 363,210 / 12,246,144 | identical | identical | 0 problems, 0 differences | Stage: 688 meshes, 31211 triangles |
| st32 | 41,197 / 1,147,136 | identical | identical | 0 problems, 0 differences | Stage: 4 meshes, 296 triangles |

The one problem on `st09_03` is the reader's, not the file's: the game's own `st09_03.alr` has a format-30 vertex
buffer with mask 0x1000CF, where the reader's table (made from the battle maps) says 0x100CF.

Original Xbox release:

| File | Game files (.dat / .alr bytes) | .dat | .alr | Check | Note |
|---|---|---|---|---|---|
| st00 | 131,296 / 1,786,752 | identical | identical | 0 problems, 0 differences | st00.dat has no stage tables (collision, spawns, objects, effects) |
| st01 | 860,678 / 6,002,816 | identical | identical | 0 problems, 0 differences | Stage: 287 meshes, 22450 triangles |
| st02 | 566,128 / 9,823,488 | identical | identical | 0 problems, 0 differences | Stage: 25 meshes, 29044 triangles |
| st03 | 406,243 / 10,680,832 | identical | identical | 0 problems, 0 differences | Stage: 214 meshes, 46215 triangles |
| st04 | 479,232 / 11,186,304 | identical | identical | 0 problems, 0 differences | Stage: 27 meshes, 22148 triangles |
| st05 | 450,224 / 12,265,088 | identical | identical | 0 problems, 0 differences | Stage: 35 meshes, 42567 triangles |
| st06 | 360,509 / 11,244,160 | identical | identical | 0 problems, 0 differences | Stage: 634 meshes, 29411 triangles |
| st07 | 359,477 / 11,936,000 | identical | identical | 0 problems, 0 differences | Stage: 732 meshes, 102958 triangles |
| st08 | 479,544 / 12,521,728 | identical | identical | 0 problems, 0 differences | Stage: 187 meshes, 47979 triangles |
| st09 | 324,287 / 2,534,144 | identical | identical | 0 problems, 0 differences | Stage: 103 meshes, 16481 triangles |
| st09_01 | 2,390 / 10,320,896 | identical | identical | 0 problems, 0 differences | st09_01.dat has no stage tables (collision, spawns, objects, effects) |
| st09_02 | 4,319 / 7,897,088 | identical | identical | 0 problems, 0 differences | st09_02.dat has no stage tables (collision, spawns, objects, effects) |
| st09_03 | 4,638 / 8,555,008 | identical | identical | 1 problems, 0 differences | st09_03.dat has no stage tables (collision, spawns, objects, effects) |
| st09_04 | 2,355 / 4,347,008 | identical | identical | 0 problems, 0 differences | st09_04.dat has no stage tables (collision, spawns, objects, effects) |
| st09_05 | 2,723 / 10,072,064 | identical | identical | 0 problems, 0 differences | st09_05.dat has no stage tables (collision, spawns, objects, effects) |
| st09_06 | 2,670 / 8,508,928 | identical | identical | 0 problems, 0 differences | st09_06.dat has no stage tables (collision, spawns, objects, effects) |
| st09_07 | 3,730 / 9,368,832 | identical | identical | 0 problems, 0 differences | st09_07.dat has no stage tables (collision, spawns, objects, effects) |
| st09_08 | 2,346 / 8,606,976 | identical | identical | 0 problems, 0 differences | st09_08.dat has no stage tables (collision, spawns, objects, effects) |
| st12 | 566,419 / 10,184,192 | identical | identical | 0 problems, 0 differences | Stage: 25 meshes, 29044 triangles |
| st13 | 406,211 / 10,736,000 | identical | identical | 0 problems, 0 differences | Stage: 220 meshes, 46276 triangles |
| st14 | 412,405 / 10,810,496 | identical | identical | 0 problems, 0 differences | Stage: 27 meshes, 22148 triangles |
| st15 | 450,224 / 11,473,408 | identical | identical | 0 problems, 0 differences | Stage: 35 meshes, 42567 triangles |
| st16 | 360,151 / 12,046,208 | identical | identical | 0 problems, 0 differences | Stage: 634 meshes, 29411 triangles |
| st17 | 344,679 / 11,645,440 | identical | identical | 0 problems, 0 differences | Stage: 728 meshes, 99478 triangles |
| st22 | 565,801 / 10,025,600 | identical | identical | 0 problems, 0 differences | Stage: 25 meshes, 29044 triangles |
| st23 | 402,835 / 10,558,848 | identical | identical | 0 problems, 0 differences | Stage: 214 meshes, 46180 triangles |
| st24 | 320,427 / 9,225,984 | identical | identical | 0 problems, 0 differences | Stage: 27 meshes, 7864 triangles |
| st25 | 451,980 / 11,589,248 | identical | identical | 0 problems, 0 differences | Stage: 38 meshes, 42615 triangles |
| st26 | 363,210 / 12,246,144 | identical | identical | 0 problems, 0 differences | Stage: 688 meshes, 31211 triangles |
| st32 | 41,197 / 1,147,136 | identical | identical | 0 problems, 0 differences | Stage: 4 meshes, 296 triangles |

Ascension 0.4 (community map, its own `.dat` / `.alr` as the game original):

| File | Game files (.dat / .alr bytes) | .dat | .alr | Check | Note |
|---|---|---|---|---|---|
| st30 | 1,051,324 / 11,190,544 | identical | identical | 1 problems, 0 differences | Stage: 21 meshes, 8784 triangles |

Add-on 1.3.0 on the same files (from the first round, for comparison):

| Map | Game files (.dat / .alr bytes) | 1.3.0 export | Checked (1.3.0) | This branch | Checked |
|---|---|---|---|---|---|
| st00 | 131,296 / 1,786,752 | fails: index out of range | - | byte-identical | 0 problems, 0 content differences |
| st01 | 860,678 / 6,002,816 | 1,048,920 / 7,950,704 | 0 problems, 6 content differences | byte-identical | 0 problems, 0 content differences |
| st02 | 566,128 / 9,823,488 | 1,008,348 / 12,411,424 | 1 problem, 8 content differences | byte-identical | 0 problems, 0 content differences |
| st03 | 406,243 / 10,680,832 | 577,360 / 12,445,568 | 1 problem, 8 content differences | byte-identical | 0 problems, 0 content differences |
| st04 | 479,232 / 11,186,304 | 650,652 / 13,579,680 | 1 problem, 8 content differences | byte-identical | 0 problems, 0 content differences |
| st05 | 450,224 / 12,265,088 | 565,044 / 15,886,192 | 1 problem, 8 content differences | byte-identical | 0 problems, 0 content differences |
| st06 | 360,509 / 11,244,160 | 569,744 / 12,501,920 | 1 problem, 8 content differences | byte-identical | 0 problems, 0 content differences |
| st07 | 359,477 / 11,936,000 | 744,312 / 14,429,904 | 1 problem, 5 content differences | byte-identical | 0 problems, 0 content differences |
| st08 | 479,544 / 12,521,728 | 741,032 / 17,674,304 | 1 problem, 8 content differences | byte-identical | 0 problems, 0 content differences |
| st09 | 324,287 / 2,534,144 | fails: base .alr has no "sd" format-0x01 mesh to copy settings from | - | byte-identical | 0 problems, 0 content differences |
| st12 | 566,419 / 10,184,192 | 1,008,724 / 12,742,944 | 1 problem, 7 content differences | byte-identical | 0 problems, 0 content differences |
| st13 | 406,211 / 10,736,000 | 577,328 / 12,515,712 | 1 problem, 9 content differences | byte-identical | 0 problems, 0 content differences |
| st14 | 412,405 / 10,810,496 | 582,632 / 13,018,528 | 1 problem, 7 content differences | byte-identical | 0 problems, 0 content differences |
| st15 | 450,224 / 11,473,408 | 565,072 / 15,084,896 | 1 problem, 8 content differences | byte-identical | 0 problems, 0 content differences |
| st16 | 360,151 / 12,046,208 | 569,292 / 13,297,920 | 1 problem, 8 content differences | byte-identical | 0 problems, 0 content differences |
| st17 | 344,679 / 11,645,440 | 729,328 / 13,970,256 | 1 problem, 5 content differences | byte-identical | 0 problems, 0 content differences |
| st22 | 565,801 / 10,025,600 | 1,007,740 / 12,631,072 | 1 problem, 8 content differences | byte-identical | 0 problems, 0 content differences |
| st23 | 402,835 / 10,558,848 | 570,548 / 12,317,312 | 1 problem, 8 content differences | byte-identical | 0 problems, 0 content differences |
| st24 | 320,427 / 9,225,984 | 389,996 / 10,416,128 | 1 problem, 8 content differences | byte-identical | 0 problems, 0 content differences |
| st25 | 451,980 / 11,589,248 | 568,500 / 15,237,600 | 1 problem, 8 content differences | byte-identical | 0 problems, 0 content differences |
| st26 | 363,210 / 12,246,144 | 575,868 / 13,574,816 | 1 problem, 8 content differences | byte-identical | 0 problems, 0 content differences |
| st32 | 41,197 / 1,147,136 | 110,505 / 1,147,872 | 0 problems, 1 content differences | byte-identical | 0 problems, 0 content differences |


## Edit and undo (fallback and in-place writers)

For every battle map and edit kind: import the game original, make the edit, export (base: the game original),
start a new scene, import that export, take the edit back, export again, compare both exports with the game's
files. `spawn` = first spawn of layout 1 moved 1 m; `collision` = the first collision mesh (one surface type)
raised 0.5 m; `visual` = the first stage mesh moved 0.2 m; `object` = the first placed object moved 1 m;
`objectadd` = a copy of it added 3 m away (undo: the copy deleted); `objectdel` = the last placed object without
parts deleted (undo: a copy of a same-model object put where it was); `effect` = one effect moved 1 m; `lighting`
= custom lighting on, the stage light's colour changed (undo: the original colours); `showcase` (for the pictures)
= the biggest stage mesh raised 2 m and an object copied. "B differ" = bytes that differ from the game's file
(an appended block counts in full), then the size change. Check = problems found by the independent reader in the
edit export / the undo export. "Structural differences" = the independent reader's content summaries that differ
from the game's file after the undo.

175 (stage, edit) pairs: 102 undo exports byte-identical to the game files, 40 the same size with at most 32 bytes different (float rounding), 33 other:
- st02 showcase: undo .dat identical, .alr 1677 B differ, +0 B
- st03 showcase: undo .dat identical, .alr 474 B differ, +0 B
- st04 showcase: undo .dat identical, .alr 1767 B differ, +0 B
- st05 object: undo .dat 7488 B differ, +7472 B, .alr 9792672 B differ, +172672 B
- st05 objectdel: undo .dat 108 B differ, +0 B, .alr identical
- st05 showcase: undo .dat identical, .alr 3128 B differ, +0 B
- st06 effect: undo .dat 90 B differ, +0 B, .alr identical
- st07 showcase: undo .dat identical, .alr 159 B differ, +0 B
- st08 visual: undo .dat identical, .alr 41 B differ, +0 B
- st08 showcase: undo .dat identical, .alr 356 B differ, +0 B
- st09 collision: undo .dat 286419 B differ, +286413 B, .alr identical
- st09 objectdel: undo .dat 48 B differ, +0 B, .alr identical
- st09 showcase: undo .dat identical, .alr 540 B differ, +0 B
- st12 showcase: undo .dat identical, .alr 1677 B differ, +0 B
- st13 showcase: undo .dat identical, .alr 462 B differ, +0 B
- st14 objectdel: undo .dat 43 B differ, +0 B, .alr identical
- st14 showcase: undo .dat identical, .alr 1767 B differ, +0 B
- st15 object: undo .dat 7488 B differ, +7472 B, .alr 9322560 B differ, +172544 B
- st15 objectdel: undo .dat 309 B differ, +0 B, .alr identical
- st15 showcase: undo .dat identical, .alr 3128 B differ, +0 B
- st16 objectdel: undo .dat 65 B differ, +0 B, .alr identical
- st16 effect: undo .dat 92 B differ, +0 B, .alr identical
- st17 showcase: undo .dat identical, .alr 159 B differ, +0 B
- st22 showcase: undo .dat identical, .alr 1677 B differ, +0 B
- st23 showcase: undo .dat identical, .alr 462 B differ, +0 B
- st24 showcase: undo .dat identical, .alr 877 B differ, +0 B
- st25 object: undo .dat 7490 B differ, +7472 B, .alr 9365597 B differ, +173184 B
- st25 objectdel: undo .dat 309 B differ, +0 B, .alr identical
- st25 showcase: undo .dat identical, .alr 3152 B differ, +0 B
- st26 objectdel: undo .dat 65 B differ, +0 B, .alr identical
- st26 effect: undo .dat 193 B differ, +0 B, .alr identical
- st32 visual: undo .dat identical, .alr 66 B differ, +0 B
- st09 lighting: undo .dat 817 B differ, +813 B, .alr identical

| Stage | Edit | Edit export .dat | .alr | Undo export .dat (vs original) | .alr | Check (edit / undo) | Structural differences after undo | Cycles 2-1 (undo vs original) |
|---|---|---|---|---|---|---|---|---|
| st01 | spawn | 10 B differ, +0 B | identical | 1 B differ, +0 B | identical | 0 / 0 | none | - |
| st01 | collision | 140587 B differ, +140581 B | identical | identical | identical | 0 / 0 | none | - |
| st01 | visual | identical | 327 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st01 | object | 2 B differ, +0 B | identical | 2 B differ, +0 B | identical | 0 / 0 | none | - |
| st01 | objectadd | 3862 B differ, +3856 B | identical | identical | identical | 0 / 0 | none | - |
| st01 | objectdel | 1 B differ, +0 B | identical | 1 B differ, +0 B | identical | 0 / 0 | none | - |
| st01 | effect | 2 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st01 | showcase | 3862 B differ, +3856 B | 2586 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st02 | spawn | 4 B differ, +0 B | identical | 4 B differ, +0 B | identical | 0 / 0 | none | - |
| st02 | collision | 151 B differ, +0 B | identical | 28 B differ, +0 B | identical | 0 / 0 | none | - |
| st02 | visual | identical | 39 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st02 | object | 4 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st02 | objectadd | 7822 B differ, +7816 B | identical | identical | identical | 0 / 0 | none | - |
| st02 | objectdel | 1 B differ, +0 B | identical | 1 B differ, +0 B | identical | 0 / 0 | none | - |
| st02 | effect | 2 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st02 | showcase | 7822 B differ, +7816 B | 21584 B differ, +0 B | identical | 1677 B differ, +0 B | 0 / 0 | none | - |
| st03 | spawn | 4 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st03 | collision | 139943 B differ, +139937 B | identical | identical | identical | 0 / 0 | none | - |
| st03 | visual | identical | 73 B differ, +0 B | identical | 6 B differ, +0 B | 0 / 0 | none | - |
| st03 | object | 2 B differ, +0 B | identical | 2 B differ, +0 B | identical | 0 / 0 | none | - |
| st03 | objectadd | 6490 B differ, +6484 B | identical | identical | identical | 0 / 0 | none | - |
| st03 | objectdel | 1 B differ, +0 B | identical | 5 B differ, +0 B | identical | 0 / 0 | dat placements: 326 -> 326 entries (1 only in original, 1 only in new) | - |
| st03 | effect | 3 B differ, +0 B | identical | 2 B differ, +0 B | identical | 0 / 0 | dat effects: 45 -> 45 entries (1 only in original, 1 only in new) | - |
| st03 | showcase | 6490 B differ, +6484 B | 7342 B differ, +0 B | identical | 474 B differ, +0 B | 0 / 0 | none | - |
| st04 | spawn | 4 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st04 | collision | 114163 B differ, +114157 B | identical | identical | identical | 0 / 0 | none | - |
| st04 | visual | identical | 244 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st04 | object | 3 B differ, +0 B | identical | 1 B differ, +0 B | identical | 0 / 0 | none | - |
| st04 | objectadd | 5734 B differ, +5728 B | identical | identical | identical | 0 / 0 | none | - |
| st04 | objectdel | 1 B differ, +0 B | identical | 2 B differ, +0 B | identical | 0 / 0 | dat placements: 272 -> 272 entries (1 only in original, 1 only in new) | - |
| st04 | effect | 2 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st04 | showcase | 5734 B differ, +5728 B | 18166 B differ, +0 B | identical | 1767 B differ, +0 B | 0 / 0 | none | - |
| st05 | spawn | 4 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st05 | collision | 68451 B differ, +68445 B | identical | identical | identical | 0 / 0 | none | - |
| st05 | visual | identical | 27 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st05 | object | 3709 B differ, +3692 B | 9357944 B differ, +87936 B | 7488 B differ, +7472 B | 9792672 B differ, +172672 B | 0 / 0 | dat names: 32 -> 34 entries, 0 differ; dat placements: 119 -> 119 entries (5 only in original, 5 only in new); dat objects: 32 -> 34 entries, 0 differ; alr roots: 110 -> 116 | - |
| st05 | objectadd | 2278 B differ, +2272 B | identical | identical | identical | 0 / 0 | none | - |
| st05 | objectdel | 87 B differ, +0 B | identical | 108 B differ, +0 B | identical | 0 / 0 | dat placements: 119 -> 119 entries (1 only in original, 1 only in new) | - |
| st05 | effect | 1 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st05 | showcase | 2278 B differ, +2272 B | 30391 B differ, +0 B | identical | 3128 B differ, +0 B | 0 / 0 | none | - |
| st06 | spawn | 11 B differ, +0 B | identical | 1 B differ, +0 B | identical | 0 / 0 | none | - |
| st06 | collision | 56 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st06 | visual | identical | 96 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st06 | object | 2 B differ, +0 B | identical | 1 B differ, +0 B | identical | 0 / 0 | none | - |
| st06 | objectadd | 9622 B differ, +9616 B | identical | identical | identical | 0 / 0 | none | - |
| st06 | objectdel | c1 ERROR IndexError: list index out of range | | | | | | |
| st06 | effect | 92 B differ, +0 B | identical | 90 B differ, +0 B | identical | 0 / 0 | none | - |
| st06 | showcase | 9622 B differ, +9616 B | 7715 B differ, +0 B | identical | 22 B differ, +0 B | 0 / 0 | none | - |
| st07 | spawn | 4 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st07 | collision | 316527 B differ, +316521 B | identical | identical | identical | 0 / 0 | none | - |
| st07 | visual | identical | 72 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st07 | object | 1 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st07 | objectadd | 189 B differ, +184 B | identical | identical | identical | 0 / 0 | none | - |
| st07 | objectdel | 1 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st07 | effect | 2 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st07 | showcase | 189 B differ, +184 B | 5620 B differ, +0 B | identical | 159 B differ, +0 B | 0 / 0 | none | - |
| st08 | spawn | 6 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st08 | collision | 135 B differ, +0 B | identical | 5 B differ, +0 B | identical | 0 / 0 | dat collision: 3822 -> 3822 entries (4 only in original, 4 only in new) | - |
| st08 | visual | identical | 655 B differ, +0 B | identical | 41 B differ, +0 B | 0 / 0 | none | - |
| st08 | object | 1 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st08 | objectadd | 1810 B differ, +1804 B | identical | identical | identical | 0 / 0 | none | - |
| st08 | objectdel | 1 B differ, +0 B | identical | 5 B differ, +0 B | identical | 0 / 0 | dat placements: 49 -> 49 entries (1 only in original, 1 only in new) | - |
| st08 | effect | 2 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st08 | showcase | 1810 B differ, +1804 B | 5420 B differ, +0 B | identical | 356 B differ, +0 B | 0 / 0 | none | - |
| st09 | spawn | 4 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st09 | collision | 288207 B differ, +288201 B | identical | 286419 B differ, +286413 B | identical | 0 / 0 | none | - |
| st09 | visual | identical | 241 B differ, +0 B | identical | 15 B differ, +0 B | 0 / 0 | none | - |
| st09 | object | 1 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st09 | objectadd | 1990 B differ, +1984 B | identical | identical | identical | 0 / 0 | none | - |
| st09 | objectdel | 25 B differ, +0 B | identical | 48 B differ, +0 B | identical | 0 / 0 | dat placements: 54 -> 54 entries (1 only in original, 1 only in new) | - |
| st09 | effect | identical | identical | identical | identical | 0 / 0 | none | - |
| st09 | showcase | 1990 B differ, +1984 B | 19122 B differ, +0 B | identical | 540 B differ, +0 B | 0 / 0 | none | - |
| st12 | spawn | 4 B differ, +0 B | identical | 4 B differ, +0 B | identical | 0 / 0 | none | - |
| st12 | collision | 151 B differ, +0 B | identical | 28 B differ, +0 B | identical | 0 / 0 | none | - |
| st12 | visual | identical | 39 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st12 | object | 4 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st12 | objectadd | 7822 B differ, +7816 B | identical | identical | identical | 0 / 0 | none | - |
| st12 | objectdel | 1 B differ, +0 B | identical | 1 B differ, +0 B | identical | 0 / 0 | none | - |
| st12 | effect | 2 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st12 | showcase | 7822 B differ, +7816 B | 21584 B differ, +0 B | identical | 1677 B differ, +0 B | 0 / 0 | none | - |
| st13 | spawn | 4 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st13 | collision | 139943 B differ, +139937 B | identical | identical | identical | 0 / 0 | none | - |
| st13 | visual | identical | 73 B differ, +0 B | identical | 6 B differ, +0 B | 0 / 0 | none | - |
| st13 | object | 2 B differ, +0 B | identical | 2 B differ, +0 B | identical | 0 / 0 | none | - |
| st13 | objectadd | 6490 B differ, +6484 B | identical | identical | identical | 0 / 0 | none | - |
| st13 | objectdel | 1 B differ, +0 B | identical | 5 B differ, +0 B | identical | 0 / 0 | dat placements: 326 -> 326 entries (1 only in original, 1 only in new) | - |
| st13 | effect | 3 B differ, +0 B | identical | 2 B differ, +0 B | identical | 0 / 0 | dat effects: 45 -> 45 entries (1 only in original, 1 only in new) | - |
| st13 | showcase | 6490 B differ, +6484 B | 7300 B differ, +0 B | identical | 462 B differ, +0 B | 0 / 0 | none | - |
| st14 | spawn | 4 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st14 | collision | 114163 B differ, +114157 B | identical | identical | identical | 0 / 0 | none | - |
| st14 | visual | identical | 244 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st14 | object | 3 B differ, +0 B | identical | 1 B differ, +0 B | identical | 0 / 0 | none | - |
| st14 | objectadd | 5734 B differ, +5728 B | identical | identical | identical | 0 / 0 | none | - |
| st14 | objectdel | 28 B differ, +0 B | identical | 43 B differ, +0 B | identical | 0 / 0 | none | - |
| st14 | effect | 2 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st14 | showcase | 5734 B differ, +5728 B | 18166 B differ, +0 B | identical | 1767 B differ, +0 B | 0 / 0 | none | - |
| st15 | spawn | 4 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st15 | collision | 68451 B differ, +68445 B | identical | identical | identical | 0 / 0 | none | - |
| st15 | visual | identical | 27 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st15 | object | 3709 B differ, +3692 B | 8863958 B differ, +83712 B | 7488 B differ, +7472 B | 9322560 B differ, +172544 B | 0 / 0 | dat names: 32 -> 34 entries, 0 differ; dat placements: 119 -> 119 entries (5 only in original, 5 only in new); dat objects: 32 -> 34 entries, 0 differ; alr roots: 109 -> 115 | - |
| st15 | objectadd | 2278 B differ, +2272 B | identical | identical | identical | 0 / 0 | none | - |
| st15 | objectdel | 286 B differ, +0 B | identical | 309 B differ, +0 B | identical | 0 / 0 | none | - |
| st15 | effect | 1 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st15 | showcase | 2278 B differ, +2272 B | 30391 B differ, +0 B | identical | 3128 B differ, +0 B | 0 / 0 | none | - |
| st16 | spawn | 11 B differ, +0 B | identical | 1 B differ, +0 B | identical | 0 / 0 | none | - |
| st16 | collision | 56 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st16 | visual | identical | 96 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st16 | object | 2 B differ, +0 B | identical | 1 B differ, +0 B | identical | 0 / 0 | none | - |
| st16 | objectadd | 9622 B differ, +9616 B | identical | identical | identical | 0 / 0 | none | - |
| st16 | objectdel | 42 B differ, +0 B | identical | 65 B differ, +0 B | identical | 0 / 0 | none | - |
| st16 | effect | 94 B differ, +0 B | identical | 92 B differ, +0 B | identical | 0 / 0 | none | - |
| st16 | showcase | 9622 B differ, +9616 B | 7715 B differ, +0 B | identical | 22 B differ, +0 B | 0 / 0 | none | - |
| st17 | spawn | 4 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st17 | collision | 316527 B differ, +316521 B | identical | identical | identical | 0 / 0 | none | - |
| st17 | visual | identical | 72 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st17 | object | 1 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st17 | objectadd | 190 B differ, +184 B | identical | identical | identical | 0 / 0 | none | - |
| st17 | objectdel | 1 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st17 | effect | 2 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st17 | showcase | 190 B differ, +184 B | 5620 B differ, +0 B | identical | 159 B differ, +0 B | 0 / 0 | none | - |
| st22 | spawn | 4 B differ, +0 B | identical | 4 B differ, +0 B | identical | 0 / 0 | none | - |
| st22 | collision | 151 B differ, +0 B | identical | 28 B differ, +0 B | identical | 0 / 0 | none | - |
| st22 | visual | identical | 39 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st22 | object | 4 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st22 | objectadd | 7822 B differ, +7816 B | identical | identical | identical | 0 / 0 | none | - |
| st22 | objectdel | 1 B differ, +0 B | identical | 1 B differ, +0 B | identical | 0 / 0 | none | - |
| st22 | effect | 2 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st22 | showcase | 7822 B differ, +7816 B | 21584 B differ, +0 B | identical | 1677 B differ, +0 B | 0 / 0 | none | - |
| st23 | spawn | 4 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st23 | collision | 139943 B differ, +139937 B | identical | identical | identical | 0 / 0 | none | - |
| st23 | visual | identical | 7 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st23 | object | 2 B differ, +0 B | identical | 2 B differ, +0 B | identical | 0 / 0 | none | - |
| st23 | objectadd | 6490 B differ, +6484 B | identical | identical | identical | 0 / 0 | none | - |
| st23 | objectdel | 1 B differ, +0 B | identical | 5 B differ, +0 B | identical | 0 / 0 | dat placements: 326 -> 326 entries (1 only in original, 1 only in new) | - |
| st23 | effect | 3 B differ, +0 B | identical | 2 B differ, +0 B | identical | 0 / 0 | dat effects: 14 -> 14 entries (1 only in original, 1 only in new) | - |
| st23 | showcase | 6490 B differ, +6484 B | 7263 B differ, +0 B | identical | 462 B differ, +0 B | 0 / 0 | none | - |
| st24 | spawn | 4 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st24 | collision | 40059 B differ, +40053 B | identical | identical | identical | 0 / 0 | none | - |
| st24 | visual | identical | 13 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st24 | object | 1 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st24 | objectadd | 2170 B differ, +2164 B | identical | identical | identical | 0 / 0 | none | - |
| st24 | objectdel | 15 B differ, +0 B | identical | 30 B differ, +0 B | identical | 0 / 0 | none | - |
| st24 | effect | 2 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st24 | showcase | 2170 B differ, +2164 B | 5887 B differ, +0 B | identical | 877 B differ, +0 B | 0 / 0 | none | - |
| st25 | spawn | 4 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st25 | collision | 68451 B differ, +68445 B | identical | identical | identical | 0 / 0 | none | - |
| st25 | visual | identical | 39 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st25 | object | 3709 B differ, +3692 B | 8884602 B differ, +84096 B | 7490 B differ, +7472 B | 9365597 B differ, +173184 B | 0 / 0 | dat names: 32 -> 34 entries, 0 differ; dat placements: 119 -> 119 entries (5 only in original, 5 only in new); dat objects: 32 -> 34 entries, 0 differ; alr roots: 111 -> 117 | - |
| st25 | objectadd | 2278 B differ, +2272 B | identical | identical | identical | 0 / 0 | none | - |
| st25 | objectdel | 286 B differ, +0 B | identical | 309 B differ, +0 B | identical | 0 / 0 | none | - |
| st25 | effect | 1 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st25 | showcase | 2278 B differ, +2272 B | 30595 B differ, +0 B | identical | 3152 B differ, +0 B | 0 / 0 | none | - |
| st26 | spawn | 11 B differ, +0 B | identical | 1 B differ, +0 B | identical | 0 / 0 | none | - |
| st26 | collision | 56 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st26 | visual | identical | 96 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st26 | object | 2 B differ, +0 B | identical | 1 B differ, +0 B | identical | 0 / 0 | none | - |
| st26 | objectadd | 9622 B differ, +9616 B | identical | identical | identical | 0 / 0 | none | - |
| st26 | objectdel | 42 B differ, +0 B | identical | 65 B differ, +0 B | identical | 0 / 0 | none | - |
| st26 | effect | 195 B differ, +0 B | identical | 193 B differ, +0 B | identical | 0 / 0 | none | - |
| st26 | showcase | 9622 B differ, +9616 B | 7715 B differ, +0 B | identical | 22 B differ, +0 B | 0 / 0 | none | - |
| st32 | spawn | 11 B differ, +0 B | identical | 1 B differ, +0 B | identical | 0 / 0 | none | - |
| st32 | collision | 2418 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st32 | visual | identical | 248 B differ, +0 B | identical | 66 B differ, +0 B | 0 / 0 | none | - |
| st32 | object | c1 ERROR IndexError: list index out of range | | | | | | |
| st32 | objectadd | c1 ERROR IndexError: list index out of range | | | | | | |
| st32 | objectdel | c1 ERROR IndexError: list index out of range | | | | | | |
| st32 | effect | c1 ERROR StopIteration | | | | | | |
| st32 | showcase | identical | 290 B differ, +0 B | identical | identical | 0 / 0 | none | - |

Lighting (run again after the variant-slot fix):

| Stage | Edit | Edit export .dat | .alr | Undo export .dat (vs original) | .alr | Check (edit / undo) | Structural differences after undo | Cycles 2-1 (undo vs original) |
|---|---|---|---|---|---|---|---|---|
| st01 | lighting | 3 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st02 | lighting | 3 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st03 | lighting | 3 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st04 | lighting | 3 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st05 | lighting | 3 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st06 | lighting | 3 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st07 | lighting | 3 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st08 | lighting | 2 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st09 | lighting | 817 B differ, +813 B | identical | 817 B differ, +813 B | identical | 0 / 0 | none | - |
| st12 | lighting | c1 ERROR TypeError: 'NoneType' object is not subscriptable | | | | | | |
| st13 | lighting | c1 ERROR TypeError: 'NoneType' object is not subscriptable | | | | | | |
| st14 | lighting | c1 ERROR TypeError: 'NoneType' object is not subscriptable | | | | | | |
| st15 | lighting | c1 ERROR TypeError: 'NoneType' object is not subscriptable | | | | | | |
| st16 | lighting | 3 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st17 | lighting | 3 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st22 | lighting | c1 ERROR TypeError: 'NoneType' object is not subscriptable | | | | | | |
| st23 | lighting | c1 ERROR TypeError: 'NoneType' object is not subscriptable | | | | | | |
| st24 | lighting | c1 ERROR TypeError: 'NoneType' object is not subscriptable | | | | | | |
| st25 | lighting | c1 ERROR TypeError: 'NoneType' object is not subscriptable | | | | | | |
| st26 | lighting | 3 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st32 | lighting | c1 ERROR TypeError: 'NoneType' object is not subscriptable | | | | | | |

Reading the table:
- The undo exports that are not byte-identical differ only in values the edit moved, by one float32 step (the
  export holds a moved value in 32 bits; where `value + move` lies in another power of two than `value`, the
  lowest bit is lost and cannot come back). `objectdel`'s undo differs in the re-created entry (a new object put
  where the deleted one was: same values within one float step; the entry's spare word is its template's).
- `collision` grows the file when the moved mesh shares vertices with collision that stays (the block is appended
  once: the bytes of the copy count as different, but every record in it except the moved ones is the game's);
  the undo of such an edit gives the game's file back exactly.
- `objectadd` appends the placement list (4-8 KB: its entries plus the copy); the undo puts it back in place.

### Three cycles (fallback)

Cycles 2 and 3 start from the previous cycle's undo export (imported as a map file) and compare their undo export
with the game's files. 25 of 34 undo exports of cycles 2 and 3 byte-identical to the game files.

| Stage | Edit | Edit export .dat | .alr | Undo export .dat (vs original) | .alr | Check (edit / undo) | Structural differences after undo | Cycles 2-3 (undo vs original) |
|---|---|---|---|---|---|---|---|---|
| st04 | spawn | 4 B differ, +0 B | identical | identical | identical | 0 / 0 | none | c2 identical / identical; c3 identical / identical |
| st04 | collision | 114163 B differ, +114157 B | identical | identical | identical | 0 / 0 | none | c2 identical / identical; c3 identical / identical |
| st04 | visual | identical | 244 B differ, +0 B | identical | identical | 0 / 0 | none | c2 identical / identical; c3 identical / identical |
| st04 | object | 3 B differ, +0 B | identical | 1 B differ, +0 B | identical | 0 / 0 | none | c2 identical / identical; c3 1 B differ, +0 B / identical |
| st04 | objectadd | 5734 B differ, +5728 B | identical | identical | identical | 0 / 0 | none | c2 identical / identical; c3 identical / identical |
| st04 | objectdel | 28 B differ, +0 B | identical | 43 B differ, +0 B | identical | 0 / 0 | none | c2 43 B differ, +0 B / identical; c3 43 B differ, +0 B / identical |
| st04 | effect | 2 B differ, +0 B | identical | identical | identical | 0 / 0 | none | c2 identical / identical; c3 identical / identical |
| st04 | lighting | 3 B differ, +0 B | identical | identical | identical | 0 / 0 | none | c2 identical / identical; c3 identical / identical |
| st04 | objectmodel | identical | 3 B differ, +0 B | identical | identical | 0 / 0 | none | c2 identical / identical; c3 identical / identical |
| st25 | spawn | 4 B differ, +0 B | identical | identical | identical | 0 / 0 | none | c2 identical / identical; c3 identical / identical |
| st25 | collision | 68451 B differ, +68445 B | identical | identical | identical | 0 / 0 | none | c2 identical / identical; c3 identical / identical |
| st25 | visual | identical | 39 B differ, +0 B | identical | identical | 0 / 0 | none | c2 identical / identical; c3 identical / identical |
| st25 | object | 3709 B differ, +3692 B | 8884602 B differ, +84096 B | 7490 B differ, +7472 B | 9365597 B differ, +173184 B | 0 / 0 | dat names: 32 -> 34 entries, 0 differ; dat placements: 119 -> 119 entries (5 only in original, 5 only in new); dat objects: 32 -> 34 entries, 0 differ; alr roots: 111 -> 117 | c2 15314 B differ, +15296 B / 10004478 B differ, +351104 B; c3 23490 B differ, +23472 B / 10382651 B differ, +524160 B |
| st25 | objectadd | 2278 B differ, +2272 B | identical | identical | identical | 0 / 0 | none | c2 identical / identical; c3 identical / identical |
| st25 | objectdel | 286 B differ, +0 B | identical | 309 B differ, +0 B | identical | 0 / 0 | none | c2 309 B differ, +0 B / identical; c3 309 B differ, +0 B / identical |
| st25 | effect | 1 B differ, +0 B | identical | identical | identical | 0 / 0 | none | c2 identical / identical; c3 identical / identical |
| st25 | lighting | c1 ERROR TypeError: 'NoneType' object is not subscriptable | | | | | | |
| st25 | objectmodel | identical | 12 B differ, +0 B | identical | 1 B differ, +0 B | 0 / 0 | none | c2 identical / 1 B differ, +0 B; c3 identical / 1 B differ, +0 B |

`objectmodel` = one vertex of the first placed object's model (its type's mesh) moved 0.3 m.

### Area files and `st00` (fallback, model only)

| Stage | Edit | Edit export .dat | .alr | Undo export .dat (vs original) | .alr | Check (edit / undo) | Structural differences after undo | Cycles 2-1 (undo vs original) |
|---|---|---|---|---|---|---|---|---|
| st00 | visual | identical | 657 B differ, +0 B | identical | 8 B differ, +0 B | 0 / 0 | none | - |
| st09_01 | visual | identical | 15 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st09_02 | visual | identical | 21 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st09_03 | visual | identical | 7 B differ, +0 B | identical | identical | 1 / 1 | none | - |
| st09_04 | visual | identical | 104 B differ, +0 B | identical | 1 B differ, +0 B | 0 / 0 | none | - |
| st09_05 | visual | identical | 22 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st09_06 | visual | identical | 14 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st09_07 | visual | identical | 9 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st09_08 | visual | identical | 19 B differ, +0 B | identical | identical | 0 / 0 | none | - |

### Xbox (fallback)

| Stage | Edit | Edit export .dat | .alr | Undo export .dat (vs original) | .alr | Check (edit / undo) | Structural differences after undo | Cycles 2-1 (undo vs original) |
|---|---|---|---|---|---|---|---|---|
| st04 | spawn | 4 B differ, +0 B | identical | identical | identical | 0 / 0 | none | - |
| st04 | collision | 114163 B differ, +114157 B | identical | identical | identical | 0 / 0 | none | - |
| st04 | visual | identical | 244 B differ, +0 B | identical | identical | 0 / 0 | none | - |
| st04 | objectadd | 5734 B differ, +5728 B | identical | identical | identical | 0 / 0 | none | - |
| st04 | showcase | 5734 B differ, +5728 B | 18166 B differ, +0 B | identical | 1767 B differ, +0 B | 0 / 0 | none | - |

## Pictures (fallback; optional external check)

Every pair was laid over its slot as a community mod in a clean-room reimplementation of the game (the PC
loader's `Assets/Data/Map` layout, over the Xbox data) and drawn from fixed cameras in a headless battle, 45 ticks
in, without the HUD: `spawn1` (the battle camera at player 1's start), `spawn2` (above player 2's start, looking
where it faces), `overview` (high over the middle of the map) and three high corners. Per map one sheet at 4:3
(1440 x 1080, the 4:3 area of a 2560 x 1080 window) and one at 2560 x 1080 (the widescreen look's 16:9 picture as
that window shows it), columns: original | untouched round trip | `showcase` edit | edit taken back. A column whose
files are byte-identical to the original is marked so and shows the original's picture. The sheets are kept
outside this repository (`sheet_<map>_4x3.png`, `sheet_<map>_wide.png`).

Sheets for st01-st09, st12-st17, st22-st26 and st32 (42 files, 6 views each). What they show: the original and the untouched round trip are the same files (marked so) on every map; the edited column shows the raised stage mesh where a view sees it (st04's overview and spawn view, st25's spawn view and corners, st01, st12, st22); the undone column matches the original in every view (on st01 and st32 its files are the original's). st09 (the town hub) draws black in a battle (the engine draws the town's areas from `st09_01`-`st09_08`, not as a battle stage), so its sheet only shows that all four columns agree. The engine's battle picture in the widescreen look is its 4:3 picture inside the 16:9 frame (bars at the sides), so the 2560 x 1080 sheets show the same 4:3 picture framed.

## Other checks

- `tests/collision_patch_test.py` (no Blender, every map): 147 PASS lines, `RESULT: 0 failure(s)`; a moved surface type taken back gives the file back byte for byte on 17 of 21 maps, 1-5 bytes of float rounding on st02, st08, st12, st22 (in place there).
- `tests/blender_roundtrip_all.py`: st04, st07, st32: 28 PASS, `RESULT: 0 failure(s)` (st04's reshaped object model written into its own meshes; st07's added as one new type).
- `tests/alr_rebuild.py` (22 maps): `RESULT: 0 failure(s)`. `tests/maplight_test.py`: 20 of 20 scripts rebuilt
  identical.
- Save and reopen (first round): st04 imported, saved as a `.blend`, opened in a new Blender process and exported
  with no edits: byte-identical.
- A map built from scratch (`examples/build_example_map.py`): the `.dat` is identical to 1.3.0's (first round). A
  scene that was not imported exports as before.
- Not run: `tests/objects_test.py` (needs a map made by the example); `tests/blender_roundtrip.py` keeps the same
  two failures as on 1.3.0 (expectations older than the mirror axis mapping).

## Still open (fallback)

Seen in the tables (not fixed):
- **Moving `st05_flykan` (st05, st15; st25 in the first round)**: its object type's digest changes although only the
  placement moved, so the type is added as a new type (+3.7 KB `.dat`, +84-88 KB `.alr`) and the undo adds another
  one. Cause not found yet (something of that type is read in world space).
- **st06 / st16 moved effect**: the moved effect's whole 0x5C-byte entry is rewritten (92 bytes) and the undo
  leaves 90 bytes different: the entry is written from the scene's effect settings, not only its position.
- **st09 collision**: the moved mesh shares vertices, the block is appended (+288 KB), and the undo does not find
  its way back to the game's block (+286 KB left; valid). The block-level test (`collision_patch_test.py`) gives
  st09 back; the scene's triangles of that surface type do not match the file one for one there (not resolved).
- **st07's object model**: falls back to a new type (not investigated).
- **st09 lighting**: the town's light colour is held as a short integer in its script (its red is 0); the edited colour
  needs a float, so the script grows and is appended (+813 bytes, also after the undo).
- st32 has no placed objects and no effects (those rows have no result); `objectdel` on st06 ran with an older
  harness that picked an object whose model no other object has (no result).

- **Object types:** an object model edited beyond moving vertices (UVs, faces, materials), a model-less type
  (jump pads), or a model sharing a vertex with another mesh is added as a new type (its placements repointed), so
  taking such an edit back does not give the game's file back. A copied object whose model differs from every
  imported type, or a renamed type collection, still rebuilds every object the 1.3.0 way.
- **Meshes edited beyond moving vertices** (UVs, faces, materials, a turned or scaled object, a vertex another mesh
  shares) are still rebuilt with the add-on's four shaders (`sbpx`, `sc`, `sv`, `sdyfog`, `sbtsyfog`, `lbts`
  ... become `sd`). Normals of moved vertices keep the game's values (a strongly reshaped mesh keeps its old
  shading).
- **Grown collision** (a moved mesh sharing vertices with collision that stays, triangles added or removed) is
  appended as a copy of the block (the game's block stays in the file unused): +36 to +312 KB. A vertex list can
  only grow in place by moving every table after it.
- **Float rounding:** a value moved across a power of two and moved back comes back within one float32 step
  (table); the showcase undo (+20 units on a whole mesh) shows the most: up to a few thousand bytes of the `.alr`.
- **Effects** added or deleted rewrite the effect table as 1.3.0 did (only moved effects are written in place).
- **`st09` (the town):** editing a mesh of the town beyond moving its vertices, or an object model, still fails ("no
  sd format-0x01 mesh": the writer copies unknown fields from an `sd` mesh of the replaced map, and the town has
  none); `st00`, `st09` and `st32` are not in the export's map list (the add-on targets battle maps). `st32` has no
  light script (custom lighting is refused there, as before).
- **Characters:** an unedited export of a character over itself is valid but not identical (model rebuilt, exmot
  clips re-encoded, the four colour variants get variant 0's model and textures). The charaset record is now kept
  (bug 5).
- **A map without stage shadow meshes** (st25) gets the add-on's minimal shadow box when its stage is rebuilt.
- **Digests** compare floats to 1e-4 game units; an edit smaller than that is not seen as an edit.
- The harness ran in Blender 5.1.2 (the manifest asks for 5.3); nothing version-specific is used.

## How to run the checks

Built from the scene (default, fallback off):

```
blender -b --factory-startup --python tests/blender_rebuild_one.py -- <repository> <Assets/Data folder> stNN <out_dir> untouched
blender -b --factory-startup --python tests/blender_rebuild_one.py -- <repository> <Assets/Data folder> stNN <out_dir> edits
python tools/check_stage.py <game .dat> <game .alr> <out_dir>/stNN_u1.dat <out_dir>/stNN_u1.alr
python tools/stage_semantics.py <repository> <game .dat> <out_dir>/stNN_u1.dat
python tests/rebuild_offline_test.py <Assets/Data folder>
```

The fallback (copy-back on), in this repository (needs only your own game files):

```
blender -b --factory-startup --python tests/blender_roundtrip_all.py -- <Assets/Data folder> <out_dir> [stNN ...]
python tests/collision_patch_test.py <Assets/Data/Map folder> [stNN ...]
python tools/check_stage.py <original.dat> <original.alr> <exported.dat> <exported.alr>
python tests/alr_rebuild.py <Assets/Data/Map folder>
```

`blender_roundtrip_all.py` round-trips every map in `Map/` (identical bytes expected), then on st04 and st07: one
spawn moved (only its 0x50-byte entry may change), one placed object moved (only its 0x24-byte placement), one
effect moved (only its 0x5C-byte entry), one stage mesh moved (written into its own vertices: the `.alr` keeps its
size, the `.dat` stays identical), one collision mesh raised (every triangle kept, valid collision, `.alr`
identical), one object copied (one more placement, no new type, `.alr` identical), one object type's model reshaped
(written into its own meshes: the .dat stays identical, the .alr keeps its size).

The fuller harness used for the tables (edit and undo cycles in one Blender process per map, the independent
reader, the engine pictures) lives outside this repository.

## Draft pull-request description

**Export builds the map from what is in Blender; the copy-back of the original file is an option, off by default**

Importing one of the game's maps and exporting it rebuilt the files from the scene, but the scene did not hold
everything the files hold: the second object layout, game shaders other than the four the add-on writes, the shadow
volumes, the light script beyond two colours, the effects (kept as hex copies). An earlier version of this branch
answered that by copying unedited parts of the original file back; that copy-back stays as an option ("Preserve
unedited parts from the original file", off by default), and the default export now builds both files from the scene:

- `FIELD_MAP.md`: every field of the stage `.dat` and `.alr`, its meaning and its Blender source (or "computed",
  or a listed gap).
- Light script as Blender data: four sun lights and worlds (one per light set: stage, characters, far 1, far 2;
  fog in the world's mist settings), twelve point lights, two scene properties; the export writes the 22 calls
  from them (the game's 20 scripts come out byte-identical from their values).
- Effects as named fields on the empties (class, when, id, mode, parameters, values; full rotation and scale).
- Every placement list (0, 2, 3) imported and written; a placement in several lists is one object (`pd_layouts`).
- Materials keep the game's shader and settings (29 shaders written from them, each in its own vertex format);
  the game's normals imported as custom normals; textures encoded from the Blender images under their own numbers.
- Shadow volumes keep every face (back-to-back pairs were dropped: the dark wedge over Spiral Highway's road).
- The `.dat` is rebuilt as sections: a replaced section is cut out, nothing is appended twice (`pdstage/datfile.py`).
- The model writer no longer copies fields from an `sd` mesh of the replaced map (the town could not be exported).
- Objects without collision stay without; a debris root keeps its own value.
- Fixes from the earlier rounds still apply (shadow vertex masks, `st00` / area files, Xbox textures, jump pads,
  charaset exmot; see "Bugs found and fixed").

Checks: `tools/check_stage.py` (structure), `tools/stage_semantics.py` (what the game reads from the `.dat`, game
file vs export), `tests/blender_rebuild_one.py` (untouched, edit / undo, three cycles, fallback off),
`tests/rebuild_offline_test.py` (no Blender). Results and the remaining losses: ROUNDTRIP_FIXES.md, "Built from the
scene (default)".
