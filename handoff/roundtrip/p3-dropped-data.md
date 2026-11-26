# p3: data the CCT rebuild drops (draw lights, stage joints, effect chunks 0x13/0x14, sky dome)

Worker p3, plugin round 2026-11-25. Format: claim -> evidence -> confidence. IDA = the Xbox retail XBE database
(copy at <local proof folder>); addresses are Xbox unless marked PC. Surveys: scripts and JSON under
<local proof folder> and /data (all 32 stage `.alr` of the 2017 PC files; Xbox cross-check below).

## 0. Chunk dispatch (needed for everything below)

- `chunk_run_play` 0x14CF10 calls `[0x2A41A4 + 8 * id]`: the table at 0x2A41A0 holds per chunk id a pair
  (attach handler, per-frame handler). Decoded pairs: 0x01 (0x14D170, 0x14D280), 0x02 (0x14D940, 0x1513F0 draw submit),
  0x03 (0x14DD20, 0x14DE40 pose), **0x09 (none, 0x14D290 = light list)**, 0x0A (none, 0x150C70 camera), 0x12
  (0x14DBC0, 0x1516C0 instance), 0x13 (0x14C4F0, none), 0x14 (0x14DC20, 0x14DCD0), 0x15 (0x14D090, none), 0x16
  (0x14D700, 0x14D760). **IDA, high.** Chunk 0x09 was not in alr.md.

## (a) Per-draw lights (draw 0x02 +0x28 count, +0x2C indices; instance 0x12 +0x10 count, +0x11 indices)

1. **What reads them.** Draw submit 0x151310: `if (dword_2E44F4 & 0x100) LightSet_FromDrawList(packet[5], draw+0x28)`
   (0x14DAC0). For each index i < count: light object = `0x2E65D0 + 112 * index`; by the light's type (+104): 1 ->
   set[1] (directional), 2 -> set[2] then set[3] (first two point lights), 5 -> set[0] (ambient); other types
   ignored. Instances use the same routine with a 1-byte offset (0x14DB40). The lit pixel shaders bind set[0..2]
   (`PixelLit_PerDraw` 0x1588B0: `Bind_AxisC10(set[0])`, `Bind_SunAndPointC4C7(set[1], set[2])`). **IDA, high.**
2. **Only the town uses them.** Flag 0x100 of `dword_2E44F4` is set only by `sub_89CB0(1)` (with 0x400), called from
   `Stage_PlayEnterChunks` 0xE03B0 only when `stage % 10 == 9` (the town); `sub_89CB0(0)` (every battle) clears it.
   Survey: every draw of every battle stage has count 0; non-zero counts only in `st09.alr` (101 draws + 196
   instances) and the area files `st09_01..08.alr` (4,000+ draws). Writing 0 is therefore exact for battle maps and
   a loss only for the town. **IDA + survey, high.**
3. **Where the lights come from: chunk 0x09 light lists in the town `.dat` files.** Per-frame handler 0x14D290:
   `u32 count` at chunk+8, records of 40 bytes from chunk+12: +0 colour (B,G,R,A; /255), +4 type (1 directional,
   2/3 point, 5 ambient), +5 index, +6 flags (bit 1: put the light at `index`; else the next free slot from
   `dword_2E04E4`; bit 3 -> light+108 |= 2; bit 4 -> light+108 = 4), +8 f32[3] (light+32, direction), +20 f32
   (light+100, power), +24 f32[3] (light+48, position), +36 f32 (light+96, type 1 only; types 2/3 store 1.0).
   Streams: `st09.dat` header 0xFC played with base slot 32 (`dword_2E04E4 = 32`, 0xE05D2) -> slots 32..55 and the
   explicit ambient slot 63; then `Stage_PlayVariantChunks` 0xE0610 clears the 256-entry table's types and plays the
   area's stream (area `.dat` +0x18, else `st09.dat` 0xFC + 4 * area) with base 0 -> slots 0..28. The map-light script
   environments live at slots 64 + 8 * set (`select_light_environment` 0x89A40). Dump: data/lightlists_pc.json.
   **IDA + data, high.** (FIELD_MAP's "enter chunk stream: the town's light list" is this chunk.)
4. **Light flags.** In the data, every light a draw lists has record flag bit 3 (light+108 bit 1); lights with bit 4
   (light+108 = 4: power 6,000-900,000, placed high) are never listed by a draw. The run-time picker for moving
   things, `sub_14FF50` (called by 0x1500D0), takes the two type-2 lights with the largest `power / distance^2`
   whose `+108 & mask` is 0. So bit 3 = "lights the static stage draws (baked into their lists)", bit 4 = "a
   character light" (picked at run time). **IDA + data, high for the picker; the meaning of bit 3 from data.**
5. **Can the lists be computed?** No proven rule. Tested over all 4,376 town draws/instances with their bounding
   spheres posed by the joints (tools/drawlights_rule.py): "top-k by power / d^2 among bit-3 lights" (the run-time
   picker's own score, k = the draw's count) matches the set on 2,203 / 4,376 (50%); distance, range-gap, and
   power/gap^2 variants 13-42%. Failures are systematic, not noise: e.g. st09_02 draws near lights 0 and 11 list 5 and
   12. But **the list is constant per joint**: on every town file, every joint's draws share one list (0 joints with
   two lists out of 2,932). The lists were assigned per authored object (light linking in the authoring tool), not
   derived by a distance rule. **Survey, high.** Representation: Blender light linking (each light's receiver
   collection holds the objects it lights), exported as the draw's list.

## (b) Stage joints, names and flags

1. **Bit 11 (0x800) hides a joint's draws** (draw 0x151310, instance 0x1516C0 and 0x1515E0 test
   `byte(joint record + 37) & 8`; the joint array `dword_2DD450` is the 0x03 chunk itself, so this is the file's u16
   flags at record +36). **No stage file sets it**: all 15,191 joints of the 32 stage `.alr` files have flags in
   {0x0, 0x2, 0x4, 0x10, 0x20, 0x40, 0x100, 0x200 and their unions}, max 0x204. **IDA + survey, high.**
2. **Who sets bit 11 at run time:** `sub_7C4C0` (effect launch points): in an actor's model resources it finds joints
   named `shotNN` (base-40 prefix 0xB3D8C5xx), stores each joint's matrix as launch point NN-1 and sets bit 11 so the
   marker is not drawn; `sub_4D380` (boss 00) does the same for `C_00..C_04`. These are character/boss models, **not
   stage files**: no stage joint is named `shotNN` (all names in the 32 files: `base` x187, `c` x15, `v` x3,
   `00_10`..`04_20` on st02 roots 96/97, `arm_a`, `arm_b1..c3` on st09_02 root 2). FIELD_MAP's "hidden shot markers"
   on the stage do not exist. **IDA + survey, high.**
3. **Bit 9 (0x200) = camera-facing joint.** Pose 0x14DE40: `if (byte(record+37) & 2)` the joint's rotation rows are
   replaced by the view matrix's transposed rotation (billboard). Only in st00 effect roots (vkcolanim, vkcap*,
   vkblink draws), never in a stage root 0..2. **IDA, high.**
4. **Bit 8 (0x100) = named joint looked up by name**: the SHOT00/SHOT01 loader (Xbox 0x4C4B0 / PC 0x140131000) tests
   `node+52 & 0x100` (community proof pc_readers_3 W3.1). In stage files only on named joints (st02 roots 96/97,
   st08 roots 69-71, st09_02 root 2 `arm_a`). **IDA (community notes) + survey, medium.**
5. **Bits 2, 4, 5, 6 are summaries of the joint itself** (survey of all 15,191 joints, 15,171 exact, the 20 others
   are -0.0 / sub-1e-4 values my rounding hid): 0x04 = the joint has draws, 0x10 = translation not zero, 0x20 =
   rotation not zero, 0x40 = scale not one. No reader found (the pose code always builds the full matrix). Computable
   on export. **Survey, high (rule); no reader, medium.** Bit 1 (0x2): 12 joints (st06/16/26 one object root), no
   reader found.
6. **Stage roots 0..2 have no animation tracks (0x05) and no billboard joints**, so flattening the stage joints into
   the vertices (what CCT does) draws the same picture. What is lost is only structure (names, hierarchy) and the
   town's per-joint light lists (a). **Survey, high.**

## (c) Effect chunks 0x13 (parameters) and 0x14 (effect functions)

1. 0x13 attach (0x14C4F0) stores the chunk pointer in `dword_2DD4CC`; the next draw's attach (0x14D940) moves it to
   draw+0x54 (`+84`, runtime) and clears it; `sub_14D9D0` puts it into the draw packet's [4]. The shader class's draw
   method reads it. **IDA, high.**
2. **Some classes draw nothing without it:** `vkLIGHT_Draw` 0x108DE0 and `vkCRTMONITOR_Draw` 0x1088A0 return at once
   when packet[4] is NULL. vkCRTMONITOR's words (float, from the payload start): [0] frame offset, [1] columns, [2]
   rows, [4] second offset, [5] columns, [6] rows, [8] blink level, [9] blink rate (sprite-sheet animation of a
   screen). `SBTSCLOUD3_Draw` 0x164900 does not read it. **IDA, high.**
3. **Where they are** (survey, 2017 PC): before vkpsprite (583), vkblink2 (474), sbts/sd on st08 objects (195),
   scrash2 (114), vkblink (100), vklight (96), vkcolanim, vkcrtmonitor, vklightline, ... draws. In battle stage roots
   0..2 only before the st01 and st08 sky draws (9 each, sbtscloud3/svc), **all 32 words zero** there and not read by
   those classes: dropping them changes nothing in a battle stage's own model. In town area roots 2..3 (vkcrtmonitor,
   vklight, vkblink, vkskyvision) and object roots (vklight on st05/06/16/25/26 objects, vkwater, vkstncl00, ...) they
   matter (vkLIGHT would vanish). 0x14: a single chunk in all stage files (st08 root 89, `vkemitter`).
   **Survey + IDA, high.**

## (d) Sky dome

1. Battle stages: root 2 holds the sky (2-4 draws, shaders sbtscloud3 + svc / sc / scal / svcal); town area files
   use roots 2..3 for props instead; st09 and st32 have an empty root 2. No 0x05 tracks, no billboard joints, no
   0x13 that is read (above). **Survey, high.**
2. CCT imports roots 0 and 1 only and replaces root 2 by its own sky model (`sky.apply_preset` sets
   `pd_sky_custom`), so the game's dome is not Blender data. Fixed on r-p3 (below).

## PC cross-check

- PC `sub_140199CE0` = Xbox 0x89CB0 (SWBOS/SSHADOW/SSHADOWCH swap, `word_14057F380 |= 0x500` only for argument 1).
- PC draw submit `sub_140295260` = Xbox 0x151310: skips a draw whose joint has `(u16 at joint+52) & 0x800`; with
  `word_14057F380 & 0x100` calls `sub_140295120(packet light set, draw+48)`. The 0x13 parameter pointer is stored
  as a relative offset at draw+100 on PC (`a1 + 100 + *(int*)(a1+100)`). **IDA, high.**

## Results on r-p3 (CCT worktree <local work folder>, commits 1422b76, b874865, 1c8bda3, f3dcdf4)

Representation (all real Blender data, no stored bytes):
- **Sky**: battle stage root 2 imported into Visuals > Sky as meshes with the game's materials (`sbtscloud3` keeps
  its vertex colour RGB and alpha, which fade the clouds), exported back as root 2; `pd_sky_custom` stays off (the
  add-on's own sky is still one click away).
- **Joints**: one empty per joint (hierarchy, local transform, `pd_joint_name` for named joints, `pd_joint_lookup`
  / `pd_faces_camera` / `pd_hidden` for bits 8 / 9 / 11), each draw's mesh parented to its joint (without moving).
  Export: the skeleton from the empties, vertices in the joint's space, bits 0x04/0x10/0x20/0x40 computed; an
  identity root joint is put first when joint 0 is not one (world-space meshes and the shadow volumes go there).
- **Draw instances** (0x12, st08/st09, 250): linked duplicates on their own joint (with their own light list),
  written as draws.
- **Town lights**: `Town_Lights` collection, one Blender light per light-list record (point: location, colour,
  energy = power; `pd_town_light`, `pd_light_slot`, `pd_lights_stage`, `pd_lights_characters`); the town's ambient
  (type 5, slot 63) a light with `pd_town_light = 'ambient'`. Each draw's list = Blender **light linking** (the
  light's receiver collection holds the meshes). Export: the 0x09 stream of `st09.dat` (0xFC) / the area file
  (+0x18, file size word +0x3C) from the lights, and each draw's +0x28/+0x2C from the links, in light-list order.
  The import numbers the lights in list order (records are explicit-index; no other reader of the numbers among
  the 12 xrefs of the light table), so list order = number order.
- **0x13/0x14**: not represented (no visible effect in battle roots 0..2: the only ones there are all-zero blocks
  before the st01/st08 sky draws, and SBTSCLOUD3 does not read them). Still lost: the vk* object/area-prop params
  (vkLIGHT / vkCRTMONITOR draws vanish without them) - those draws are already rewritten with a fallback shader by
  CCT, a separate gap.

Engine proof (prebuilt <local work folder>; sheets under <local proof folder>):
- Town, real game flow (story start in area 4, `tools/town_sheet.py`): `eng/town4v/sheet_town_st09_04.png`.
  Mean abs diff vs original: r-p3 + p1's material commits (742d2f1, b39a985 cherry-picked into a verify branch)
  **4.22**; the same file with the light lists dropped **31.33**; the original with its lists dropped 27.86;
  base CCT 32.47. Isolation: `.dat` light stream alone (rebuilt .dat + original .alr) **0.00**. Without p1's
  material fix, r-p3 alone is 38.0 (the town's dbts materials lose their normal map slot and highlight in CCT:
  `eng/town4/`), i.e. the light lists work but need p1's materials to look right.
- Town walk mode (`play --stage st09_04`) does not light draws by their lists (engine path without light objects):
  base and r-p3 identical there; use the game flow.
- Sky (upward views sky_a / sky_b, 4:3, mean abs diff vs original):
  st03 `eng/st03sky2`: base CCT (add-on sky) 19.3 / 18.3 -> r-p3 **1.1 / 1.1** (wide 0.8-1.1);
  st08 `eng/st08sky`: first r-p3 batch 13.6 / 16.6 -> **0.96 / 1.17**; st01 `eng/st01sky` 7.0 / 8.0 -> **2.3 / 1.3**;
  st07 `eng/st07sky2` 21.1 / 8.0 -> 6.3 / 3.3; st04 `eng/st04sky` 0.22 / 1.1.
  Three causes found and fixed after the first batch (commits 1c8bda3, f3dcdf4):
  1. **normal-map alpha** (the coordinator's item, here on sbtscloud3): the scroll writer forced both cloud normal
     maps' alpha to 127 and wrote them as new copies (on st07 the copies even took the template texture's cube-map
     flag). The game's cloud normal maps have alpha 30..255 (part of the cloud's alpha). Now kept, written under
     their own numbers. This, not the tangents, was most of the cloud difference (grafting game tangents alone had
     moved st07 only 21.1 -> 16.5).
  2. st01/st08's cloud colour `cloud_color3` is R5G6B5 (format 0x85): the importer could not decode 16-bit formats
     and wrote a plain grey `pd_c959595` instead; `alr.texture_dds` now expands 0x02/0x04/0x05 to BGRA.
  3. the dome's svc/sc/scal/svcal and cloud highlight (+0x34) were lost (e.g. st04 svc 7f7f7f14 -> 0, cloud
     3c3c3c0f -> 7f7f7f14); now game materials with their highlight. Left: power byte 0x14 where the colour is 0
     (no highlight either way).
  Field check after the fixes (rb/m): st01/st03/st04/st08 root 2 same shaders and triangle counts, geometry within
  0.1 unit, materials/textures/vertex colours equal except that power byte.
- Battle stage pictures (`eng/st03`): base CCT and r-p3 both lose the sunlit floor (score ~8-22 in both columns):
  pre-existing, not from these items (overview drops 18.1 -> 13.4 with the game's dome).

## Field comparison, all 28 stage files (2017 PC), first batch (commit 1422b76; sky material fixes came after)

Table: <local proof folder> (tools/compare_dropped.py, tools/summary.py; outputs rb/all).
- **Town draw lights**: every matched draw/instance has the original's light set on all 9 town files (st09: 299 of
  299 incl. the 196 instances; areas 71-873 draws each); same order everywhere except 2 draws of st09_01 and 2 of
  st09_07 (the 2 lists out of list order noted in (a)5). The light list records (colour, type, flags, power,
  position) are the same on all 9 files. Unmatched draws (0-22 per file) are draws whose rebuilt points straddle a
  0.1 rounding step, plus the rebuilt shadow volume.
- **Joints** (roots 0..2): count, names, flags and world matrices the same on the town files and battle roots 1/2;
  "flags" on battle root 0 = the joint that held the game's shadow volumes loses bit 0x04 (the rebuilt volume sits
  on joint 0) and, on st09, the instance-only joints gain 0x04 (instances written as draws). An identity root is
  added where joint 0 is not one (st02/05/07/15/17/23/25 sky, st08 root 1, st09). Bits 0x04/0x10/0x20/0x40 have no
  reader found.
- **Cycle 3 vs cycle 1**: stable on 26 files; st09_04 and st09_08 drift by about 0.002 rad on a few joints rotated
  close to 90 degrees about Y (Euler from Blender's float matrix near gimbal lock). Cycle 1 vs original is exact on
  both.

## Still open

- 0x13 parameters for vk* shaders (object models, town area roots 2+): not represented; vkLIGHT/vkCRTMONITOR draw
  nothing without them, but CCT already rewrites those draws with a fallback shader (separate gap).
- 0x14 effect function (one chunk, st08 root 89 `vkemitter`), animation tracks 0x05, area roots 3+: not done.
- Town walk mode of the engine (`play --stage st09_NN`) ignores draw light lists; the game flow uses them.
- The town's dbts materials lose their normal map and highlight in CCT: p1's b39a985 fixes it (verified together:
  4.22 score, branch p3-verify in <local proof folder>, not for merging).
- Xbox experiment request R-p3-1 (xemu-requests.md): draw light lists dropped / first light swapped in area 4.
- Battle stage sunlit floors darker in every CCT rebuild (base and r-p3 alike): not from these items.
