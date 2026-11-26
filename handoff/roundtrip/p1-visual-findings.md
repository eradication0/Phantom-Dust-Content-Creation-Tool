# p1: the operator's five visual findings on rebuilt maps (claim -> evidence -> confidence)

Branch `r-p1` in <local work folder> (commits 4da8dd3, 742d2f1, 2a15495, 51be66d + the town proof). Scripts and pictures:
<local proof folder> (`scripts/`, `r_st04/`, `r_st02/`, `town/`, `sheets/`). "s48" = <local proof folder> (the
rebuild the operator looked at); "p1" = the rebuild from r-p1; all fallback off.

## 1. Panorama spawn pillar: hard seams -> object models lost the game's vertex normals

- Claim: the spawn pillars are object models (roots 31-35, 67-71: sbtsrefs `st04_c_has1/has2` + `ref_n` +
  `ref_hashira`, with sbts `con3/elv/obj2`), not stage meshes. `visuals.build_mesh` (used for every object model)
  never set the game's normals, so the export wrote Blender face normals.
- Evidence (bytes): root 31 vs rebuilt 191, matched by (position, UV): normal angle median 22.5 deg (has1/has2: the
  game's octagon normals sit 22.5 deg off the faces = smooth shading), 56 deg (elv), 64 deg (obj2). After the fix:
  0.0 / 0.0 / 0.0 (`scripts/cornerdiff.py`-style check in the transcript).
- Evidence (engine, spawn 1, 4:3): pillar crop (x 60-200) mean abs diff vs original: s48 7.04, after normals 1.47;
  whole frame 1.55 -> 1.23. `r_st04/crop_pillar.png` (original | s48 | fixed).
- Confidence: high.

## 2. The pillar's reflection/shine missing -> same cause (normals), plus the tangent frame

- SBTSREFS (PC `SBTSREFS_vs.cso`, disassembled with tools/dxbc_disasm.py): the reflection lookup coordinates are
  built from `N * 2(N.E) - E` with the vertex NORMAL (v1), the tangent-space light/half vectors from TANGENT (v4),
  BINORMAL (v5), NORMAL as `(-L.T, -L.B, L.N)`; the pixel shader multiplies the env texture by the colour alpha and
  the normal map. Flat normals = one reflection per face; after the normals fix the shine is back (crop above).
- Material records are identical (shader, flags, roles, specular ffffff/02, textures by name); textures re-encoded
  within 0.1-1.6 of 255 per channel (`scripts/texdiff.py`). Colour alpha (shine mask) identical (all 255 here).
- Confidence: high for the pillar.

## 3. Normal maps "lost" -> wrong tangent handedness (all sbts-family shaders), fixed

- Claim: the game's tangent frame is B along the UV map's V (B ~ -dP/dv in file space) and T = N x B always; the
  game stores no handedness. The export wrote Blender's +U tangent, which is -(N x B) on mirrored UVs.
- Evidence (bytes, `scripts/tbn_rule.py`): every tangent-framed vertex of st01-st09 (PC) and st04/st09 (Xbox):
  `T.(N x B) > 0.9` for 99.5%, `T.(B x N) > 0.9` for 0; B ~ -dP/dv on 97% of triangles while T ~ +dP/du on 54% and
  -dP/du on 37% (the mirrored ones). s48 st04: 16,921 vertices with T = B x N; sbts materials had 30-52% of their
  vertices with the tangent flipped (`scripts/cornerdiff.py`).
- Evidence (code): SBTS / SBTSREFS / SBTSCLOUD3 vertex shaders use T and B only as rows of the light/half-vector
  transform (above); a flipped T flips the bump's x and the highlight lookup (SBTS pixel shader samples the specular
  table t3 at (N_map . H_ts)).
- Fix: T = N x B, B = Blender bitangent orthonormalised; one frame per vertex (corner binormals summed). st04 after:
  T = N x B on 100%, flips 0-5% (residue from the game's own averaging), vertex count 30,829 (game 31,652; s48
  40,906). Engine: st04 spawn 1 whole-frame 1.55 -> 1.47 with the tangent fix alone (most st04 surfaces are lit
  weakly; the pillar was the visible case and was item 1).
- Audit of the material path (st04, st02 roots 0-2): shader, flags (+0x0C), filter, blend, texture roles, textures,
  shader parameters (+0x3C) and specular colour come back equal; differences seen: specular power 0x14 written where
  the game has 0 with colour 0 (no effect: colour 0 = no highlight), `sc st04_red` specular colour 7f7f7f -> 0
  (shader sc has no specular term), cube maps still the game file's (FIELD_MAP gap). Confidence: high (tangent),
  medium (that nothing else in the material path differs visibly: checked st04 and st02 only).

## 4. Town much darker -> per-draw light lists written as 0 (fixed)

- Claim: draws carry a light list (payload +0x28 count, +0x2C light-object numbers); the town's draws use it
  (st09: 101 draws x 3 lights, e.g. (34, 35, 63); st09_01-08: 2 lights on almost every area draw). The export wrote
  0, so every such draw fell back to its environment's light set, which in the town is black (st09's stage light
  is (0, 0, 0)).
- Evidence (bytes, `scripts/drawlights.py`): original st09 {3 lights: 101, 2: 2}, s48 {0: 103}; areas: st09_03 orig
  {2: 382, 1: 99, 3: 11, ...} vs s48 all 0. p1: distributions identical; per draw (material, lights, box centre)
  510 of 514 equal on st09_03.
- Evidence (code): our engine notes (phantom-formats mesh.rs): draw handler 0x1513F0 hands the list to 0x14DAC0
  (point lights in order, then directional and hemisphere); the engine falls back to the environment slot when the
  list is empty (phantom-shading stage/draws.rs). Not re-checked in IDA this round (all four idalib workers busy).
- Evidence (engine): town area renders original | s48 | p1 in `town/` (see the sheet; numbers in the report).
- Fix: import keeps the list as `pd_draw_lights` on the mesh object (run-time light numbers: genuine game data, no
  raw bytes); the writer puts it into the draw. Each Blender object is still its own draw set, so lists never mix.
- Open: the hub st09 (the operator's café view) renders black in the engine's battle mode even for the original
  (the engine does not run the town light list there), so the café view itself is proven by bytes, not by a render.

### 4b. The rest of the town's darkness: the material path (found by the audit, fixed)

Light lists alone moved the eight town areas little (area 1 20.6 -> 18.5). A material audit (`scripts/audit.py`:
every original material key = shader, slot textures by role, highlight colour, roles; which are missing from the
rebuild) found four more export losses, all fixed on r-p1:

- `dbts` (the town's normal-mapped shader, no vertex colour) was imported as a plain material: normal-map slot
  written empty, highlight colour 7f7f7f -> 0. Now every game shader with a role-2/role-4 slot or a highlight colour
  becomes a PD Stage Shader material (`visuals.pd_maps`).
- `lbts` / `lbtsrefs` (the light-mapped floors) were written as `sbts` without the light map: the second UV map
  (vertex format 0x1F) was never imported. Now `PD_LightUV` + the light map image are imported and the material is
  written with the game's own settings (roles 0x0261 or 0x0255, flags, blend, lbtsrefs' cube map).
- 16-bit textures (B5G6R5, B4G4R4A4; st0900_10n / 12n / 13n) were skipped on import (`alr.texture_dds` returned
  None): their dbts normal slots came out empty. Now expanded to BGRA8.
- Light maps holding the light in RGB with alpha 0 (s_shadow, t_shadow, DXT5) were re-encoded as DXT1 with 1-bit
  alpha, whose transparent texel is black: the light map turned black (area 2). `dxt.binary_alpha` now requires the
  transparent texels to be black.
- `dbtsal`, `dbtsrefsal`, `dbtsrefsvc` (and vkcap02, vkcapm2a, vkendofwld) added to SHADER_FORMAT from a survey of
  every PC .alr (formats 0x25 / 0x03 / 0x09); they fell back to the add-on's sbtsrefs.
- Object models now keep their draws' light lists too (`pd_draw_lights` on the mesh data).

Result (engine, town areas 1-8, `town6/sheet_town.png`, mean abs diff vs original): s48 20.6 / 23.3 / 11.1 / 22.6
/ 17.6 / 17.5 / 8.5 / 16.1 -> p1 1.61 / 0.82 / 0.69 / 1.24 / 1.69 / 0.81 / 0.41 / 0.75; luminance back to the
original's (e.g. area 1 13.9 -> 34.7, original 34.5). Audit after: every original material present in the rebuild
on st02, st09, st09_01/03/04/06/07; left: vkcrtmonitor (effect shader, format 0x21, st09_02/05/08), st09_08's
sshadow, one st04 cloud layer (its colour texture `cloud_color` differs; not investigated).

## 5. Highway sky darker -> the add-on's gradient dome replaced the game's painted dome (fixed)

- Claim: the import turned root 2 into the Phantom Dust Sky settings (four colour stops sampled from the dome) and
  the export wrote the add-on's `svc` gradient dome instead of st02's `sc` dome with the `sky2` picture; the
  darker sky also lowers the glare (the whole frame changes, road included).
- Evidence (engine, st02 spawn 1, 4:3, mean abs diff vs original): s48 11.99; p1 before the sky fix 10.72; the same
  rebuild with only the sky model kept as the game's (experiment, `scripts/rb1x.py`) 1.40 -> the sky is the cause.
- Fix: the sky model is imported as Blender data (Visuals > Sky: one empty per joint with `pd_sky_joint`,
  `pd_joint_flags`, parented as the joints; each draw a mesh on its joint in joint space) and written from it.
  Result built from the scene: 1.43. Joints come back as the game's (st02: 4 joints, flags 0x34/0x10, the sun
  marker at (-864, 1006, 4505)). Cloud shell vertex alpha now kept (SBTSCLOUD3_vs passes COLOR.w to the pixel alpha;
  the game's shell fades 0 at the horizon -> 255 -> 178; the scroll path forced 255).
- Open: cloud tangent frames differ by ~12 deg median (Blender's from the UVs vs the game's); the add-on's own sky
  settings still work when the user turns them on (they replace the model, as before).
