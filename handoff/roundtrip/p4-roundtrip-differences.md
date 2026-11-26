# p4: the rebuild's remaining measured differences (s48) - causes, evidence, fixes

Worker p4, 2026-11-25. Branch `r-p4` in <local work folder> (on `roundtrip-fixes` ca67fee). Outputs <local proof folder>
Harness: s48's `rb_one.py` (headless Blender 5.1, fallback off, `compress_textures='ALL'`), engine
<local work folder> Scripts: <local proof folder> (matdiff2, secsizes, colstats,
grid_hyp*, colmember, colsize_all, placediff, placeset, defdiff, objcol*, alrsizes, sheet3, closeups).

## 1. Dark floors (st03 / st13 / st23)

**Claim.** The import gave only the add-on's eight stage shaders (`sd sbts sdrefs sbtsrefs` and their `al` variants,
`visuals.STAGE_SHADERS`, from 1.2.0) the game's maps. Every other game shader the export writes from game settings
(`alr_build.SHADER_FORMAT`: `sbtsrefp`, `sdrefp`, `sbpxrefpal`, `sbpx`, `sv`, ...) got a plain diffuse-only material,
and `tag_game_material` skips slots whose role is 1/2/4 (expected on the material's maps). So the export wrote:
normal slot (role 2) and reflection slot (role 4) = 0xFFFF, specular word +0x34 = 0 (was 0x144C4C4C), vertex alpha =
255 (was 0..215, the shine mask). Confidence: high.

**Evidence.** Field diff of st03 root 0 (`an/st03_refp_s48.txt`): all 14 `sbtsrefp` materials: textures [0,1,8,0] ->
[0,FFFF,FFFF,0], +0x34 4c4c4c14 -> 00000014, mean vertex alpha 0-133 -> 255; `sdrefp` [15,5] -> [15,FFFF],
+0x34 858585 -> 0. The engine binds a refp material's textures per slot (`phantom-shading/src/stage/textures.rs`,
`binder.rs` parallax path `0x157290`, SBPXREFPAL stages `0x166610`): with no normal / reflection texture the floor
goes dark. After the fix (`an/st03_all_fix1.txt`) the refp materials equal the game's apart from the index byte;
vertex alpha kept.

**Fix.** `bce5b16` (visuals.py `keeps_game_maps`). Engine, 6 views x 2 aspects
(`proof/plugin-p4/sheets_floor/sheet_st03|13|23_4x3|wide.png`), mean abs diff per channel (4:3, 6 views):

| map | s48 mean / max | now mean / max |
|---|---|---|
| st03 | 14.38 / 22.29 | 2.65 / 6.67 |
| st13 | 14.49 / 23.02 | 3.50 / 11.30 |
| st23 | 7.07 / 14.73 | 0.94 / 1.17 |

What is left in those sheets: the sky at the map edge (the add-on's sky model instead of the game's dome: the
overview's bright wedges on st13; known open item) and small patches on glass rails. Not mine.
Left over: `sv` materials with a black specular colour and power 0 come back with power 20 (Blender's Shininess
socket min 1); black specular has no light, so no visible effect.

## 2. .dat size swings (st32 +168%, others -4%..+20%)

**Claim A (st32).** st32 has 0 object definitions and its header 0x90 word points at 0x168, the start of its
collision. `datfile.refs` counted that word, so the game's collision section stayed "alive" in the rebuilt file
next to the new collision (36,676 dead bytes). Fixed in `0671cc5` (`refs` ignores 0x90 when the count is 0; `_delete`
still moves it). Confidence: high (section table `secsizes.py`: `h94/objects 36676 -> objects 36676 + h94 69305`).

**Claim B (all maps).** The collision builder chunked by 60-unit cells with at most 8 triangles; the game's own
chunking is different and the per-chunk overhead (52 bytes) made the swings (collision `h94` was the largest
changing section everywhere: st07 +70 KB, st03 -26 KB, st02 +19 KB). Measured game rule (scripts `grid_hyp*.py`,
`colmember.py`, `objcol2.py`), confidence high:
- stage list: the triangles' bounding box cut into 16 x 16 x 16 equal cells, one chunk per (cell, surface kind) by
  triangle centroid, file order x then y then z; no size cap (up to 205 triangles). st32: 256/256 chunks exact;
  rebuilt from the game's triangles, 90.0% of all game chunks (7,072 / 7,860 over 12 maps) come out triangle for
  triangle, and the block size is within -0.2..+0.6% of the game's on every retail stage (st05/15/25/32 equal size);
- object list: one chunk per surface kind (612 lists, 674 chunks, never two chunks of one kind, up to 308
  triangles).
Why it doesn't change play: each chunk is one broad-phase object (sphere + box) of the character query; the
triangle grid (`Stage_BuildCollisionGrid` 0xB9630, cells 30x20x30) is per triangle (research/notes/player-physics.md).
Same triangles, same vertices (welding drops the game's 8 duplicate vertices on st06/16/26: no data lost).

**Fix.** `0671cc5`. Rebuilt .dat vs game: st32 +168.2% -> -0.0%, st07 +19.6% -> +0.1%, st09 +14.0% -> -0.2%,
st02 +5.3% -> -0.3%, st06 +5.1% -> -0.4%, st16 +5.1% -> -0.4%, st03 -4.2% -> +0.1%, st24 -1.3% -> +0.0%, st01
+0.1% -> -0.1%. Remaining few hundred bytes: object definition sections moved (same content), a sound table of
0xFFFF rows written where the game file has none (st01/st07/st09: semantics of "no table" vs "all 0xFFFF" not
proven; s48's checker treats them as the same).

**.alr swings.** Texture policy: every texture written as DXT1/DXT5 with a full mip chain. Game textures with one
mip level (st01 `e3_02_dxt5_1` 512x512, st06 `pl012`/`pl006`/`pl003`, `backbmp`, `e3a_flash01`, ...) got 9-10 levels
(+33%), plain-colour textures (format 0x06: glows, sea, sky pictures) got block-compressed (-75..-87%). Fix
`9366ef7`: imported images carry `pd_mip_levels` and `pd_texture_storage` (how the game stores the texture); the
export keeps the level count and writes a one-level plain texture plain (plain textures with several levels stay
block-compressed: the add-on's note says plain-with-mips drew rainbow streaks; not re-tested).
.alr now vs game: st01 +17.1% -> +12.2%, st16 -14.4% -> -0.2%, st26 -14.5% -> -0.6%, st06 -7.6% -> -2.9%, st24
+1.6% -> -0.1%, st03 +0.7% -> -0.3%. What is left is vertex data: corners split on export (st01 84,886 game
vertices -> 106,044; after `9366ef7` objects keep the game's normals, which removed part of it; tangents per corner
are the likely rest, not measured), and st08/st09's draw instances (0x12, 196 on st09) are written as full
geometry (st09 .alr +15%, 21,761 -> 38,854 vertices). Bloat, no lost data; open.

## 1b. st16 / st26 much darker overall, st01

**Claim.** st16/st26 store their normal maps (pl0xxn, backbmp) as DXT5 with alpha 0 everywhere. `visuals_export.compress`
took "alpha only 0/255" for a 1-bit cut-out and wrote DXT1 with every texel transparent - DXT1 stores those black.
Evidence: swap test (`scripts/swap16.py`, spawn 2): game .dat + rebuilt .alr mean 13.74, rebuilt .dat + game .alr
1.87; decoded texels pl001n mean RGB (127, 125, 252) -> (0, 0, 0). Fix `4c6cc0e` (no cut-out when nothing is opaque; a
game DXT3/DXT5 texture stays DXT5). Engine 4:3 mean (6 views): st16 11.82 -> 4.03 (`proof/plugin-p4/sheets_dxt/`);
what is left there is the cloud sky (add-on sky model). st01: 12.87 -> 2.66 with all fixes
(`proof/plugin-p4/sheets_final/sheet_st01_*.png`; s48's "fog meshes" were sdyfog/sbtsyfog materials without their
game maps, the same cause as item 1). st06 1.98 -> 1.51.

## 3. Placements and object models

**Claim A: per-placement behaviour class lost.** The class (+0x04 table, +0x05 class) is per placement in the game:
st03/13/23 chairs 2-3 (collapse in place) and 2-18 (shatter when touched), glass rails 2-3/2-18, gifts 2-1/2-17/2-18,
st01 walls 2-66/2-73, st09 triggers 4-1/4-3/4-7 (survey over all retail stages). The import took the first
placement's class for all placements of a definition: 67 st03 placements changed behaviour (a chair that should
shatter on touch collapsed instead). A player can tell. Fixed: `pd_class` on a placement whose class differs.

**Claim B: definitions merged.** The export makes one definition per mesh geometry; the import kept sounds / root
values on the first placement only. st06 oilcanA/oilcanB (same model, break sound 17 vs 23, other root values: hits)
became one definition with oilcanA's values. Fixed: on every placement, part of the export's grouping key. Defs that
are equal in everything still merge (st09's 8 lamp defs -> 1: only the names differ; nothing the game reads).

**Claim C: collider surface kinds lost.** Import kept the most common kind per collider; model-less objects wrote the
collection's kind (08). st06/st07 jump pads 01 -> 08 (steps get sound), st24 entrance 0x10 (restricted wall/trigger)
-> 08, st09 doors/triggers 01/06 -> 08, st09 isupub 06+12 -> 08. Fixed: one collider per kind; model-less object's
main kind on the placement.

**Claim D2: same model, other colliders.** st05 kanbanM1/kanbanM2 share a model but not their collider: merged
(collider 12 -> 16 triangles). Fixed `9366ef7` (such a definition gets its own type collection on import).

**Claim D3: object meshes had no normals.** `visuals.build_mesh` (object models) imported no vertex normals; the
export wrote Blender's face normals (other shading, every corner split: st01 object vertices 44,689 -> 62,778).
Fixed `9366ef7` (custom normals from the game's).

**Claim D: st02 car collider 308 -> 232 triangles.** 74 repeated triangles + 2 back faces merged by Blender. Fixed
(`_tris_mesh` gives repeated faces their own corners).

Evidence for A-D: `placeset.py` (placements as the game reads them: list, class, extra, position, turn, collider
triangles per kind, sounds 1-2): not matched s48 -> now: st01 41 -> 0, st02 2 -> 0, st03 89 -> 0, st06 31 -> 0,
st07 4 -> 0, st09 26 -> 0, st24 59 -> 0. Commit `da5972a`.

**Claim E (open, evidence): object shadow volumes dropped.** The "broken-piece joint structure differs" count of s48
is mostly this: object models carry shadow meshes (`sshadow`, `sshadowc`, `sshadowch`) on their own joint (intact:
joint 1 under the root, 43 meshes on 5 maps; broken: a sub-joint of each piece, 105; debris: 13). `build_mesh` skips
`sshadow*`, so the joints holding only a shadow vanish (intact 2 -> 1 joints, broken pieces lose their sub-joint,
mesh counts -1 per piece). Engine close-up (`proof/plugin-p4/closeups/closeups_st06.png`): the container's
shadow region on the floor is the only clear difference (mean 3.24, 10% of pixels > 16 at a container). A player can
tell (objects lose their shadows). Not fixed: needs a shadow part kind on objects (import per joint, export as an
sshadowch/sshadowc raw mesh on the same joint through `alr_build.build_model`'s raw path, vertex format of
sshadowch/sshadow to be measured). Debris roots with pieces are also flattened into one mesh (n=2 -> 1).

**Claim F (open, unproven):** broken roots with meshes on the root joint and no pieces (st24/st04 stairs `kaidan*`,
fences) come back as one piece (n=1 -> 2). Their class 2-1 lists intact + debris states only in the add-on's preset
table (no code evidence collected), so the broken model may never be used. Needs an engine break test or an Xbox
experiment; not done.

Not done: an engine battle where objects are broken (no headless switch for breaking objects in the testing engine
found; gym object tours exist, `research/notes/gym.md`). xemu request not filed.
