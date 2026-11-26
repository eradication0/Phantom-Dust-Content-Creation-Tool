# p5: independent verification of FIELD_MAP.md (stage `.dat` and `.alr`)

Worker p5, 2026-11-25. Research only (no export code changed). Every verdict below was re-derived here, not copied
from FIELD_MAP.md or our docs. Evidence types:

- **X-code**: Xbox `retail.xbe` IDB (IDA 9.3, my own copy `<local proof folder>`), decompiled or
  disassembled at the address given.
- **PC-code**: 2017 `PDUWP.exe` IDB (my copy `.../ida/pc.i64`).
- **Scan**: a full-binary disassembly dump (`<local proof folder>,pc}.asm.txt`, 610k / 697k
  instructions, `p5tools/ida_dump.py`) searched with scripts (`p5tools`: `tri2.py`-style pattern searches, quoted).
- **Census**: xemu run of the real Xbox game with GDB read watchpoints (Z3) on the fields of the loaded
  `Map/st05.dat` / `st05.alr`, armed before the stage files were read, through the load and 420 battle polls with
  movement (`p5tools/p5_watch.py`, run `<local proof folder>` + `battle.log`). 2280 watches,
  0 refused. A watch hit gives the exact accessed address and the eip after the reading instruction.
- **Data**: survey of all 22 Xbox and 22 PC `Map/stNN.dat` (+ `.alr`), `p5tools/stagefile.py`.
- **Disc**: modified copy of the Xbox disc image run in xemu (p5-experiments.md).

Verdicts: **confirmed** (re-derived, agrees), **corrected** (re-derived, FIELD_MAP is wrong or incomplete: the fix is
stated), **unproven** (not re-derived by p5; no claim either way).

## Census controls (why "0 hits" means "not read")

In the same run, fields known to be read were hit, so the mechanism sees loads and per-frame reads:

| Control | Hits | Readers (eip after the load) |
|---|---|---|
| triangle `i0` (+0x00) of all 537 triangles near the spawns | 537 of 537 read | `0xB9722` (Stage_BuildCollisionGrid, load) on all; `0xBD5E4` (169) / `0xBD884` (157) = the hit-record builders `sub_BD540` / `sub_BD7F0` during the battle |
| mesh chunk +0x34 (count) | read | `0xB96DE`, `0xB9B44` (grid build) |
| material +0x0C (flags) | read at load and every frame | `0x14D98D` (draw attach), `0x15142F` (Chunk2_DrawSubmit), `0x14DA58` |
| header +0x94 | read | `0xDF921` (StageObjects_LoadDefs) |

## Stage `.dat` header (0x13C)

Header readers found (census, st05, load; addresses = eip after the read): `+0x04` `0xDF6FA`, `+0x08` (list 1, -1)
`0xDF6C2`, `+0x30` `0xDF70D`, `+0x34` (count 1, -1) `0xDF6E2`, `+0x5C` `0xDF68D`, `+0x60` `0xDF691`, `+0x90` `0xDF78E`,
`+0x94` `0xDF921`, `+0x98` `0xDFA21`, `+0x9C` `0xE0DC6`/`0xE106E`, `+0xA0` `0xBE383`/`0xBE4CF`, `+0xA4` `0xB87C8`,
`+0xD0` `0xE0544`, `+0xF4` `0xBE509`, `+0xFC` `0xE0519`. Not read at all in the run: `+0x00` magic, `+0x0C..0x2C`,
`+0x38..0x58` (other variants), `+0x64..0x8C`, `+0xA8..0xCC`, `+0xD4..0xF0`, `+0xF8` (no object broke), `+0x100..0x138`.

| FIELD_MAP row | Verdict | Evidence |
|---|---|---|
| `+0x000` magic `ST00` constant | confirmed (constant); note: **not read** by the loader | Census: no read of +0x00. Data: all 21 battle/town files |
| `+0x004` u32[11] lists, `+0x030` counts; list 0 default, list `1+variant` used | confirmed | X-code `StageObjects_LoadDefs` `0xDF630`: list `hdr[4*(v+1)+4]`, count `hdr[4*(v+12)+4]` (u16), v = `byte_39EA16`; if the list is -1 it falls back to `+0x04`/`+0x30`. Census: +0x08 then +0x04 read |
| `+0x05C` NM00, `+0x060` name count | confirmed; `+0x60` is the **definition count** (u16 used) | X-code `0xDF630`: `word_39EA08 = hdr+0x60`, used as the OB00 count |
| `+0x064..0x084` OC/OE/OA tags | confirmed as "not read" | Census: none read. X-code: no `g_StageDat` access to these offsets (all 35 xrefs of `g_StageDat` 0x39E8A0 checked) |
| `+0x088`, `+0x08C` -1, no reader | confirmed | Data: -1 in all 21 ST00 files (Xbox and PC). Census: not read. X-code: no indexed access reaches them |
| `+0x0C0..0x0CC` -1, no reader | **corrected**: start-point group slots 7..10 (`+0xA4 + 4k`, -1 = no group) | X-code `Stage_SelectStartGroup` `0xB87B0`: `hdr[4*(k+40)+4]`, k = `byte_39E855` (player slot / 4 in `Fighter_PlaceAtStartPoint`, also set by the capsule setups `0x6466B`, `0x64828`). -1 everywhere (data); unreached in practice by battle slots 0..7 |
| `+0x0DC..0x0F0` -1, no reader | **corrected**: light-script slots k = 3..8 (`+0xD0 + 4k`) | X-code `Stage_PlayEnterChunks` `0xE03B0` (asm `0xE0537..0xE0559`): `hdr[0xD0 + 4*(scene/10)]`, -1 -> `+0xD0`; `Stage_PlayVariantChunks` `0xE0610` (town): `hdr[0xD0 + 4*area]`. `+0xDC` is read for st3x (k = 3) and town areas 3..8. -1 = use slot 0 |
| `+0x100..0x134` -1, no reader | **corrected**: enter-chunk slots k = 1..14 (`+0xFC + 4k`) | X-code `0xE0503..0xE0533`: `hdr[0xFC + 4*(scene/10)]`, -1 -> `+0xFC`, played by `sub_8A0C0` -> `chunk_run_play` on **every** stage entry; town: `hdr[0xFC + 4*area]` (`0xE07D6`). `+0x100..0x108` are read on st1x..st3x. -1 = use slot 0 |
| `+0x090` OB00, `+0x094` collision, `+0x098` EF00, `+0x09C` SP00, `+0x0A0` MD00 | confirmed | X-code `0xDF630` (v0[36], v0[37], v0[38]), `Stage_ParseSp00` `0xE0DB0`, `Stage_BindMd00` `0xBE360`; census readers above |
| `+0x0A4..0x0BC` CP00 groups (up to six) | **corrected** (count): 7 slots `+0xA4..+0xBC` (st05 uses 0xA4, 0xA8, 0xAC, 0xB8, 0xBC); group = player slot / 4, record = (slot % 4) % count | X-code `Fighter_PlaceAtStartPoint` `0x118830`, `Battle_StartPointForPlayer` `0x46C40`; fallback `+0xA4` in `Stage_ClearStartGroup` `0xB8830` |
| `+0x0D0 + 4k` light script; slot k = stage tens digit | confirmed (battle maps); town: k = area | X-code `Stage_PlayEnterChunks` (k = `dword_2CA4B8 / 10`; census on st05: +0xFC then +0xD0 read, k = 0), `sub_DDD00`/`sub_DDE10` use `+0xD8` (slot 2) for the town's alternate light |
| `+0x0F4` blob list | confirmed | X-code `Stage_ResolveMd00Models` `0xBE3D0` (`*(g+244)`, walks `size+4` records), census `0xBE509` |
| `+0x0F8` sound table, 16-byte row per definition | confirmed | X-code `StageObject_GetSoundId` `0xD9AA0` (`row = def*8 words`), `StageObject_QueueSound` `0xD9AE0` (word < 0 = none) |
| `+0x0FC + 4k` enter chunk stream | confirmed; played on every stage start, not only the town | X-code `0xE0503..0xE0569` -> `sub_8A0C0` `0x8A0C0` -> `chunk_run_play` |
| `+0x138` file size | confirmed "not read" | Census: no read |
| section tags | unproven | |

## Placement entry (0x24)

| Row | Verdict | Evidence |
|---|---|---|
| `+0x00` i32 object | **corrected (width)**: read as **u16** (+0x02 never read) | X-code `StageObjects_CreatePlacements` `0xDFC40`: `v17 = *v12` (u16), `g_StageObjRuntimeDefs + 72 * *v12` |
| list membership | confirmed | same, lists from `dword_39EA18` |
| `+0x04` table, `+0x05` class | confirmed | factory `g_StageObjFactoryTables[+4][+5]`; classes 0x41..0x44 are duplicated (two floors) on maps whose number ends in 1 (`dword_2CA4B8 % 10 == 1`, y +/-300) |
| `+0x06` -> method +160, `+0x07` -> method +168 | confirmed (calls); meaning per class unproven | same function, vtable calls +160/+168 |
| `+0x08` not read | confirmed | same function: only +0x00, +0x04..+0x07, +0x0C..+0x23 read |
| `+0x0C` pos, `+0x18` rot | confirmed | 6 floats from +0x0C to method +172; +0x18 also to +180 |

## OB00 definitions (0x38), names, sound rows

| Row | Verdict | Evidence |
|---|---|---|
| `+0x00` s32[3] models (ALR roots) | confirmed | `0xDF630`: `Alr_GetResource(g_StageModel, def[0..2])` |
| `+0x0C` animations | confirmed by elimination (stored via method +132 to object +0x4C) | vtable `0x28DD08` +132 = `0xD96E0` |
| `+0x18` collision | confirmed | +140 = `0xD9700` stores to object +0x58; `StageObject_Activate` `0xD9490` calls `Collision_MakeCollider` on object +88 (= +0x58) |
| `+0x24` effects | confirmed | +148 = `0xD9780` stores to object +0x74; `StageObject_Activate` passes `this[this[15] + 29]` (+0x74) to `sub_D0560` (effect spawn) |
| `+0x30` u32[2] not read | confirmed | `0xDF630` reads `def[0..11]` only |
| sound row word 4 = pieces' life in seconds | confirmed | `StageObject_LifeFromSoundTable` `0xC8090`: `30 * word[4]` ticks, < 0 -> `90 * param` |
| names, root node values | unproven | |

## Stage collision

| Row | Verdict | Evidence |
|---|---|---|
| chunk `+0x00` kind = surface | confirmed (reader set unchanged); see pool below | X-code `Collision_MakeCollider` `0xBA270`, grid `0xB9200` (kind node per cell) |
| `+0x01` shape 3/8 | confirmed | `0xB9630` (`v2[1] == 3`), `0xBA270` (`v6[1] == 8` = pool) |
| `+0x02` flags (3), `+0x03` part | confirmed as constant 3 / 0xFF in the stage list (data: 14,212 mesh chunks, both platforms); flags bit 0 selects the chunks of the broad-phase collider (`MakeCollider(1, ...)` in `0xDF630`), grid class from bits 0/1 (`0xB9630`) | X-code |
| `+0x04` size, `+0x08` reserved 0 | confirmed: +0x08 **never read** | Census: 211 chunks watched at +0x08, 0 hits; data: 0 in all 14,212 chunks |
| mesh `+0x0C` sphere, `+0x1C` box | unproven by census (not watched); static: the grid build recomputes bounds from the vertices (`0xB9630`) |
| `+0x34` count, `+0x38` pool index | confirmed | `0xB9630`, `0xBA270` (pool index -> pointer `v20+56`) |
| **`+0x36` u16 group (0x030B / 0x0034)** | **confirmed: no reader** (Xbox, load and runtime) | Census: 211 chunks watched, 0 hits (while +0x34 of the same structure was read). Scan: no 16-bit or dword load of chunk+0x36 / body+0x2A in the collision code (`0xB9000..0xBF800`, `0xD6000..0xD9000`, `0x11D000..0x120000`). Disc pe2 (0x030B <-> 0x0034 on all 509 chunks of st05): no difference |
| triangle `i0 i1 i2`, normal | confirmed | readers `0xB9722` (grid), `sub_BD540`/`sub_BD7F0` (hit records: `v14-1, v14, v14+1` indices, normal from `v14+3` words = tri+8), `PieceBody_CollideStageTriangles` `0xD6A3A..` |
| **triangle `+0x06` (0 / 52)** | **confirmed: no reader** (Xbox load + runtime; PC static) | Census: +0x06 of 537 triangles watched (all 537 had their `i0` read), 0 hits. Scan (both binaries): every function reading 3 consecutive u16 from one base (the triangle pattern) was listed; the collision ones (Xbox `0xB9630`, `0xBEE10`, `0xCFBA0`, `0xD65B0`, `0xD68D0`, `0xD89A0`, `0xBD540`, `0xBD7F0`, `0xBEFA0`; PC `0x1401D2620`, `0x1401D3040`, `0x1401D4AB0`, `0x1401D5A10`, `0x1401D7C80`, `0x1401D7FD0`, `0x1401D9A30`, `0x1401D9C50`, `0x1401EF130`, `0x1402506C0`) never load the 4th word. The game's own generated box collider (`sub_BB440` `0xBB440`, 12 triangles) does not even write it. Disc pe1 (52 -> 0 on all st05 triangles): no difference. Data: 52 on every triangle of st05/15/25 (1195 each) and st24 (694), identical on PC; it looks like an exporter group id (0x34 also occurs as a `+0x36` group value) |
| **pool kind byte (35 / 33)** | **confirmed: no meaning**; only constraint: must not be 0xFF | Census: the pool's byte 0 is read 8 times, all as the list walk's end test (`0xB952E` `sub_B93E0`, `0xB9B6C` grid, `0xBA258..0xBA429` MakeCollider) and MakeCollider's `== 18 / 19 / 31` test (which only picks the bits OR-ed into the flags byte; the pool is then masked out with bit 31, `0xBA3C0`). 35 and 33 take the same path. The game's own generated box collider writes pool kind **35** (`sub_BB440`: `*(v6) = 35; v6[1] = 8`). Data: 35 on 15 maps, 33 on st02/04/12/14/22/24 (both platforms) |
| terminator `FF FF CC CC 0 CCCCCCCC` | **corrected**: only the first byte (0xFF) is read | Census: bytes +2..+11 watched, 0 hits; every walk tests byte 0 only |
| chunking | unproven (by design not meaningful to the game beyond broad-phase cells) | |

## EF00 effect list

| Row | Verdict | Evidence |
|---|---|---|
| count u16 at +4, records at +8, 0x5C each | confirmed | `0xDF630` (`g_StageEffectCount = u16 +4`, records `+8`), `Stage_SpawnEffectList` `0xD0370` (stride 92) |
| `+0x00` class | confirmed | `EffectRecord_Spawn` `0xD02E0`: `EffectClassFactoryTable[+0]` |
| `+0x01` when | confirmed | `0xD0370`: spawned when `+1 == kind` (or kind -1) |
| `+0x02` id | confirmed | `EffectList_SpawnKind` `0xD0720` compares `+2` |
| `+0x03` mode | unproven | |
| `+0x04` pos, `+0x10` rot, `+0x1C` scale | confirmed; rot in radians (x 5215.189 = 32768/2pi to angle units) | `0xD02E0`, `EffectRecord_SetAngleUnits` `0xD07E0` |
| `+0x28` u8[12], `+0x34` f32[10] | confirmed as the two parameter blocks (pointers +0x28, +0x34 stored) | `0xD02E0` (`v5[27] = a1+10`, `v5[28] = a1+13`); per-class meaning unproven |

## CP00 start points

| Row | Verdict | Evidence |
|---|---|---|
| `+0x04` u8 count | confirmed | `0xB87B0`: `byte_39E854 = *(grp+4)`, records at `grp+8` |
| record 0x50: `+0x00` pos, `+0x0C` facing | confirmed (facing in radians) | `Fighter_PlaceAtStartPoint`: `*(rec+0xC) * 5215.189`; `sub_682F0` takes the record |
| `+0x10` const, `+0x14` capsule points, `+0x38` | unproven | |

## MD00, blob list, SP00

| Row | Verdict | Evidence |
|---|---|---|
| MD00 `+4` block-0 size, `+8` block-1 size, pairs after `+16 + sizes` | confirmed (layout) | `Stage_BindMd00` `0xBE360` |
| pairs (model root, blob) | confirmed; blob = index into the `+0xF4` list | `Stage_ResolveMd00Models` `0xBE3D0` |
| SP00 | unproven (readers `Stage_ParseSp00` `0xE0DB0`, `Stage_LoadSp00Animations` `0xE0F30` located only) | |

## Light script (`mapLight`)

Script VM argument order (needed for every row): a native gets its arguments as an array whose element 0 is the
**last** pushed value. Proof: fog handler 2:2 (`0xE1890`) uses `a[0]` as the set index, `a[1]&15` as the mode,
`a[2]` as the colour, `a[3]` start, `a[4]` end; the scripts push `(end, start, colour, mode, set)`
(`pdstage/maplight.py`, survey of the 20 scripts). Syscall table group 2: `0x2CA660` (2:0 `0xE1820`, 2:1 `0xE1870`,
2:2 `0xE1890`, 2:3 `0xE18D0`, 2:4 `0xE18F0`, 2:5 `0xE1920`, 2:6 `0xE1980` reset).

| Row | Verdict | Evidence |
|---|---|---|
| runner, header `0xD0+4k`, fallback `0xD0`, then `maplight%d.ssb` | confirmed | `Stage_RunMapLightScript` `0x89B60` |
| `2002` fog: mode, start, end/density, colour | confirmed | 2:2 `0xE1890` -> env `+0x4C` = `mode<<24 | colour&0xFFFFFF`, `+0x50` start, `+0x54` end; `LightEnv_ApplyFogAndGlare` `0x89440` (mode byte +79, 0 = off, 3 = linear) |
| **`2001` = shadow colour** (s48) | **confirmed** (Xbox and PC), with two details | 2:1 `0xE1870`: `a[0]` (the colour, pushed last) -> `dword_2C4AE8`, copied to `dword_2DD4B0` by `light_environments_reset` `0x89AD0` (called at the end of every light-script run); `sub_151E60` draws the full-screen rectangle in `dword_2DD4B0 | 0xFF000000` over the stencilled shadow pixels with blend `0x7601` = source x **destination alpha** + destination x (1 - destination alpha) (factor table `0x2A40A8`: 6 -> 0x304, 7 -> 0x305). `a[1]` (the first pushed word, 0 in every script) goes to `dword_2C4AEC`, which **has no reader**. PC: 2:1 `0x1402068A0` -> `dword_1403E8BA8` -> shadow colour `0x14057F3BC` (`sub_140199A30`); `dword_1403E8BAC` no reader. Disc pe6a (colour 0 -> 0x0000FF): every stage and character shadow turns blue |
| **`2003` = glare level** (s48) | **confirmed** (Xbox and PC); correction: the colour has **no reader at all** | 2:3 `0xE18D0`: `a[0]` (second pushed, the "colour", 0 on 18 maps) -> `dword_2C4AE0` -> `g_glare_colour` `0x3168B4`, which is only ever written (`0x89576`, `PostTargets_Init` `0x158F90`); `a[1]` (the float, first pushed) -> `dword_2C4AE4` -> `g_glare_level_target` (`0x89440`). `Glare_EaseLevels` `0x89290` eases `g_glare_level_eased` 10 % per frame toward it (FIELD_MAP said `0x89440`: that only copies the target); stage entry sets both to 0.5 (`sub_8A0C0`). The level is the bright-pass weight: `Glare_BrightPass` `0x15A1B0` sets pixel constant c1 = level x (0.3, 0.6, 0.1) (or level/255 x colour when a colour is passed; the single-screen chain `0x15C8D0` passes 0). PC: 2:3 `0x140206900`: `a[0]` -> `0x1403E8BA0` -> `0x14054C2E8` (written only), `a[1]` -> `0x1403E8BA4` -> target `0x140527CC0`, read by `Glare_Chain` `0x1402886FB`. Disc e6b (0.9 -> 3.0): glare far stronger |
| SSB header `+0x18` id unread | unproven | |
| `2000`, `2005` | unproven by p5 (handlers located: 2:4 `0xE18F0`, 2:5 `0xE1920` write env +0x0C/+0x2C/+0x30/+0x34/+0x44 and +0x10/+0x38..+0x48) | |

## Stage `.alr`

| Row | Verdict | Evidence |
|---|---|---|
| material chunk attach | confirmed: resolves textures (+0x18 roles/indices -> +0x20..+0x2C) and the shader (+0x00 -> +0x08); touches nothing else | X-code `sub_14D170` (chunk table `0x2A40E8`, id 1 attach), `sub_14D280` (per-frame: selects the list `dword_2DD448`) |
| `+0x0C` flags, `+0x11` filter, `+0x14` blend | confirmed | `sub_157780` `0x157780` (flags 0x4000 aniso from +0x11 bits 0-1, LOD bias bits 2-4, 0x10 blend via `sub_14BDE0` from +0x14, 0x200, 0x80 cull); census: flags read at `0x14D98D`, `0x15142F`, `0x14DA58` |
| `+0x34` specular colour and power | confirmed: byte +0x34 blue, +0x35 green, +0x36 red, +0x37 power, used only when flags bit 2 | `sub_156FE0` / `sub_157070` |
| **`+0x30` colour, `+0x38` word** | **confirmed: no reader on the Xbox** (load and render) | Census: +0x30 and +0x38 of **all 347 materials** of st05.alr watched from before the file was read through 420 rendered battle polls: 0 hits (the flags word of the same records was read at load and every frame). Static: the attach (`0x14D170`) and per-frame (`0x14D280`) handlers and the material state routine `0x157780` do not touch them. Disc pe4 (all +0x30 = 0xFF00FFFF, +0x38 = 0xFFFFFFFF): no difference. PC: unproven (no runtime census possible) |
| `+0x3C..+0x4B` shader parameters | unproven by p5 | |
| draws, skeleton, 0x12, 0x13/0x14, animation, shadow volumes, sky, textures | unproven by p5 | |

## Summary of verdicts

Rows judged: 62. Confirmed 45, corrected 8, unproven 9 groups of rows (each listed above as unproven).

Corrections:
1. Header `+0xDC..0xF0`: light-script slots (k = 3..8), read for st3x and town areas; -1 = use slot 0.
2. Header `+0x100..0x134`: enter-chunk slots (k = 1..14), read on st1x..st3x and town areas; -1 = use slot 0.
3. Header `+0xC0..0xCC`: start-point group slots 7..10 (-1 = none). Only `+0x88`/`+0x8C` are truly unread.
4. CP00 groups: 7 slots (`+0xA4..+0xBC`), not six.
5. Enter chunk stream: played on every stage entry (slot = tens digit), not only the town.
6. Placement `+0x00`: u16 (the high half is never read).
7. `2003` glare colour: no reader on either platform (FIELD_MAP: "only the split-screen chain may use it"); glare
   easing is `0x89290`, not `0x89440`; `2001`'s first word has no reader.
8. Collision terminator: only byte 0 (0xFF) is read; the rest is free.

Export consequences: writing -1 into the slot fields is right (it means "use slot 0"); a map number in the 10s..30s
with its light script in slot 0 still works through the fallback. Triangle `+0x06`, chunk `+0x36`, chunk `+0x08`,
the pool kind (any value but 0xFF; 35 as the game's own builder), material `+0x30`/`+0x38` and the terminator tail
can be written as constants without any in-game difference (census + disc runs, p5-experiments.md).
