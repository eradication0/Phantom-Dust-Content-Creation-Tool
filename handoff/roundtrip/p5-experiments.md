# p5: Xbox experiments (xemu) on stage fields

Worker p5, 2026-11-25. Real Xbox retail game in the operator's xemu 0.7.118 (read-only use of their install and BIOS;
per-run qcow2 overlay deleted, operator files checked unchanged after every run: "operator files changed []"),
one xemu at a time, window on DISPLAY3 never focused, silent. Route: `oracle/xemu/battle.py` (title -> debug battle
selector -> st05, EnemyTest), driven through my wrapper `<local work folder>` (branch r-p5).
Logs and frames: `<local proof folder>`, `<local proof folder>`.

## A. Read-watchpoint census (who reads which field)

Not a picture comparison: GDB read watchpoints (Z3) on the loaded `st05.dat` / `st05.alr` (addresses = heap base
`[0x3992A8]` + 0xE70000 / + 0x200000; they matched `g_StageDat` 0x39E8A0 / `g_StageModel` 0x39E89C), armed at the
first selector poll, i.e. **before the stage files were read**, kept through the stage load and 420 battle polls with
stick movement. Run `w2` (`runs/w2/watch.json`): 2280 watches, 0 refused.

| Watched | Count | Read? | Readers (eip after the load) |
|---|---|---|---|
| every header dword 0x00..0x138 | 79 | 15 read | listed in p5-field-verification.md (all in the loaders `0xDF630`, `0xE03B0`, `0xBE360/0xBE3D0`, `0xE0DB0/0xE0F30`, `0xB87B0`) |
| triangle +0x06 (st05: 52), triangles of the 211 chunks near the spawns | 537 | **no** | - |
| control: triangle +0x00 of the same 537 triangles | 537 | yes, all 537 | `0xB9722` load (grid), `0xBD5E4`/`0xBD884` in battle (hit records) |
| mesh chunk +0x36 group | 211 | **no** | - |
| mesh chunk +0x08 reserved | 211 | **no** | - |
| control: chunk +0x34 count (3 chunks) | 3 | yes | `0xB96DE`, `0xB9B44` |
| pool chunk kind byte (35) | 1 | yes, as the list end test and the 18/19/31 test only | `0xB952E`, `0xB9B6C`, `0xBA258..0xBA429` |
| collision terminator bytes +2..+11 | 1 (10 bytes) | **no** | - |
| material +0x30 and +0x38, all 347 materials of st05.alr | 694 | **no** | - |
| control: material +0x0C flags (1 material) | 1 | yes, at load and per frame | `0x14D98D`, `0x15142F`, `0x14DA58` |

Run `w1` (armed after the load, runtime only, 1090 watches) agrees: the only hits were the material-flags control.

## B. Modified disc runs

The p5 copy of the disc image `<local proof folder>` (a byte copy of the operator's xiso),
patched in place with `p5tools/discpatch.py` (same size, undo log; the copy was reverted after every run and
verified byte-identical to the Xbox game files' `Map/st05.dat` / `.alr` at the end). Patch sets:
`<local proof folder>`. One field group per run.

**Comparison method.** Free-camera runs are not repeatable (the debug selector shuffles starts: base1 and base2 of
the same disc gave different views, 77-83 % pixels changed, `sheets/det.png`). So the comparison runs use the game's
preview camera at five fixed poses (`p5tools/poses_st05.txt`: overview, two corners, spawn 0, low wall; foe held),
captured after battle poll +60. Noise floor = two runs of the unmodified copy (`pbase1` vs `pbase2`): 1.9 / 3.0 /
7.3 / 9.8 / 11.0 % of the viewport changes, all on animated things (sky clouds, aura particles, capsules, HUD
skill labels). Sheets (frame | diff x8 | changed pixels, mean abs diff): `<local proof folder>`.

| Run | Change (st05) | Changed px per pose (overview, ne, sw, spawn0, low wall) | Result |
|---|---|---|---|
| pbase2 | none (noise) | 5131, 8198, 19695, 26307, 29743 | noise floor |
| pe1 | triangle +0x06: 52 -> 0 on all 1195 triangles | 2743, 4871, 4599, 21679, 2188 | **no difference** (inside the noise; all diffs on sky/particles/capsules) |
| pe2 | chunk +0x36: 0x030B <-> 0x0034 on all 509 mesh chunks | 2139, 10357, 40859, 41961, 64291 | **no difference** in stage geometry, textures, shadows; the larger counts are sky-cloud phase (diff images: only the sky and particles) |
| pe3 | pool kind 35 -> 33 | 3308, 11088, 48864, 48437, 68542 | **no difference** (same: sky and particles only) |
| pe4 | material +0x30 = 0xFF00FFFF, +0x38 = 0xFFFFFFFF on all 347 materials | 4240, 11689, 40234, 33018, 60377 | **no difference** (no magenta anywhere; sky/particles/HUD only) |
| pe5 | header fields that are -1 (0x88, 0x8C, 0xC0..0xCC, 0xDC..0xF0, 0x100..0x134) = 0x12345678 | 4816, 12677, 51662, 42525, 72054 | **no difference** on st05 (k = 0: those slots are not reached; on st1x..st3x / the town the 0xDC / 0x100+ slots ARE read, see p5-field-verification.md, so a non -1 value there would be used) |
| pe6a (positive control, s48 claim) | `2001` colour word 0 -> 0x00FF (blue) | 15094, 27780, 39056, 42484, 58827 | **visible**: every stage shadow and the character shadows turn blue in all five poses (`sheets/pose_shadow.png`; free camera `sheets/e6a_pair_200.png`). Proves the disc patching reaches the game, and that 2001's last-pushed argument is the shadow colour |
| e6b (free camera) | `2003` float 0.9 -> 3.0 | (different view, not scored) | **visible**: the glare/bloom is far stronger, the picture washes out to white (`sheets/e6_free.png`), consistent with the level being the bright-pass weight |

Not done: the same experiments in our engine (the testing engine ignores these fields by construction: our parsers
keep them verbatim and nothing reads them); the requests file had no requests from other workers when I read it.

## Conclusions

- Triangle +0x06, chunk +0x36, chunk +0x08, the pool kind (35 vs 33), the terminator tail and material +0x30/+0x38
  are never read by the Xbox game (census, with read controls) and changing them makes no visible difference
  (disc runs). An exporter may write constants (0, 0x030B, 0, 35, `FF FF CC CC 0 CCCCCCCC`, 0xFF000000, 0) without
  any in-game difference. PC: static scan only (triangle/group); material words on PC unproven.
- `2001` = shadow colour and `2003` = glare level are confirmed both by code and visibly in the game.
