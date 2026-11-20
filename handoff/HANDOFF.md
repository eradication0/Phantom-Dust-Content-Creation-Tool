# Handoff: Phantom Dust Blender Add-On

Everything a new Claude session needs to continue this project on a fresh PC, with no other context. Read this
first, then [FORMATS.md](../FORMATS.md) (byte-level formats) and [README.md](../README.md) (user guide).

Written 2026-11-16, at commit `2aa5735` + this file. Release `v1.0.0` is published on GitHub.

---

## 1. What the project is

A **Blender 5.3 extension** ("Phantom Dust Stage", id `phantom_dust_stage`) that turns content made in Blender
into the files **Phantom Dust (2017 Windows / UWP release, `PDUWP.exe`)** reads.

- Repository: `https://github.com/eradication0/Phantom-Dust-Content-Creation-Tool` (branch `main`, GPL-3.0-or-later).
- Owner: GitHub user **eradication0** (Nuion). The owner plays the game and tests every change in game; Claude prepares
  files, reads the game's code, and writes the add-on.
- **Order of work (owner's plan):** 1) maps (done, v1.0.0), 2) character models, 3) skill animations and
  projectiles.
- **Map scope decisions (owner):**
  - Primary focus: **brand-new maps built from scratch in Blender**. Editing existing maps (import, change,
    export) is a secondary goal.
  - No intro camera (online play doesn't use it; maps won't be used in story mode).
  - Keep the game's own debris-speed limits; no code plugin/loader. Data-only changes.
  - Role tags go on **collections**, not objects.
- The repo contains **no game files** (see `.gitignore`). The owner supplies their own copy.

## 2. Status

### Done and confirmed in game

| Feature | Where |
|---|---|
| Stage model with own textures and baked vertex lighting | `.alr` writer |
| Collision with surface types | `.dat` collision block |
| Spawns and orbs, several layouts | `.dat` `CP00` |
| Character shadows on exported stages | tiny shadow-volume box |
| Props and breakables: hits to break, debris damage, debris stays/vanishes | `.dat` objects + `.alr` roots |
| Jump pads (jump power) | object category 4, type 16 |
| Effects: steam, sparks, smoke (copied from the game's own maps) | `.dat` `EF00` |
| Own sky and background | `.alr` roots 2 and 1 |
| Game lighting: stage + character light/ambient colours, sun direction | `.dat` `mapLight` script |
| Falling out of the map: the game respawns the player (no kill floor needed) | tested |
| Workflow: New Map Setup (incl. a jump pad), Bake Lighting, Install into game with backup, Restore | add-on |

### In 1.1.0, not yet confirmed in game (2026-11-18)

- **PD Stage Shader** (`pd_material.py`): node group with only the game's stage-shader settings (Diffuse, Normal Map,
  Reflection Map, Specular Color, Shininess, Shine Mask, Reflection Strength, Baked Light), Material Properties panel,
  Paint Shine Mask. Exports pick `sd` / `sbts` / `sdrefs` / `sbtsrefs`; normal maps write vertex format 3 with
  Blender's tangents. Import builds these materials with the game's own values.
- Fix for the washed-out sunlit walls reported by the user: v1.0 copied the game original's `sd` material, which has
  a broad grey highlight (`+0x34` = `7f7f7f14`), onto every vertex (alpha 255). Materials are now built from
  templates with the highlight from the material (default none). Test files: `st03_test_A_no_highlight.alr`,
  `st03_test_B_red_sharp_highlight.alr` (only `+0x34` changed).
- `tests/blender_material.py` (not yet run: written without Blender available).
- Confirmed in game 2026-11-18: the highlight bytes (`+0x34` B, G, R, power) caused the glow; red shows red; a flat
  face shines evenly (per-vertex highlight), so Shininess picks face angles, not spot size.


### Found impossible / not supported

- **Fog**: the PC version ignores the map script's fog (no render-state case for it; tested in game).
- **Debris speed/distance**: fixed in game code from mass; can't be set from data.
- **Effects glow and water drops** depend on their home map's textures; effect models, sounds and crash
  bursts reference map-specific resources. Only steam, sparks and smoke are offered.

### Open work (backlog, roughly in priority order)

1. **Stage-cast shadows** (stage shadow volumes). Today the writer emits a 1-unit closed box 1000 units below
   the stage as the `sshadowch` mesh, so characters cast shadows but the stage casts none. A full copy of the
   stage as the shadow mesh looked dark/patchy. Needs real shadow-volume geometry (closed, extruded silhouettes);
   study st04's `sshadowch` mesh (heights 50-160, a third coincides with visible triangles).
2. **Importing a map's placed objects** as editable Blender items (currently import brings stage/background/
   sky models, collision and spawns, but not the `.dat`'s placed objects).
3. **Stage variants**: per-layout placement tables (`PS00`/`PS01`...) and the effect layout filter; the add-on
   writes one variant (slot 0) only. Effect kind 20 = "stage parameters" (the variant set, picked at random per
   match; owner's knowledge).
4. **Better materials**: highlight, normal maps and reflections done in 1.1.0 (test in game). Left: animated cloud
   sky (`svc`, `sbtscloud3`), the `0x0D` `0x40` flag (cut-out?), material bytes `0x40`-`0x4B`.
5. More spawn layouts than the game original has.
6. AI navigation (`com\stNN\comdataN.cad`): the user wants bots on custom maps (they walk into walls). Layout
   partly read (FORMATS.md); paused 2026-11-18 until the loader is decompiled (route table at `0xB5A4`).
7. Then: **character models**, then **skill animations/projectiles** (nothing started).

Shader reverse engineering: the game's `*.cso` shaders keep their constant names; `tools/dump_cso.py` disassembles
them in plain Python (see FORMATS.md "Stage materials").

Small known gaps: objects can only turn about Z with scale 1;
UVs are clamped to 8 repeats per triangle (int16/4096 storage); textures written uncompressed (`0x86`).

## 3. Setting up a new PC

### Software

| Tool | Version used | Notes |
|---|---|---|
| Blender | 5.3 | Extensions system (`blender_manifest.toml`). Path used before: `F:\SteamLibrary\steamapps\common\Blender\blender.exe` (Steam) |
| Python | 3.10+ | Windows launcher `py`. Run scripts with `py -I` (isolated) |
| Git | any | Line-ending warnings (LF->CRLF) on commit are harmless |
| Ghidra | 12.1.4 | Only for reverse engineering. Needs JDK 21 (Temurin `jdk-21.0.12.1+1` was used) |
| GitHub CLI `gh` | optional | Was NOT installed on the old PC; releases were made by the owner in the browser |
| Pillow | optional | Only `tools/render_stage.py` |

### The game files

- The game is the **UWP build dumped to a plain folder** (the owner has it). What matters is its
  `Assets\Data` folder (contains `Map\st04.dat`, `Map\st04.alr`, `setup\`, `com\`, ...). The exe sits next to
  `Assets`.
- Build identity (verify on the new PC so addresses below apply):
  - `PDUWP.exe`: 5,220,864 bytes, SHA-256 `9BA7411B2820D8442E27D721CFF02BAF0229FCBF09BD690457AE7EB5B66FDC76`
  - `Map\st04.dat` (original): 479,232 bytes, SHA-256 `98DD64F1A3B9081C63625AE6768E68C00F30097706825C38D4EEF8044697D31F`
  - `Map\st04.alr` (original): 11,186,304 bytes, SHA-256 `D3277E9EE8E18B6AB1F5820D6C7BD61DAF291C92124D6EDEEE57B6D9D2E81468`
  - `Map\st09.dat` (effect presets): 324,287 bytes, SHA-256 `F7FCA66B87CC575164080F28DDD25775094EB59E63FAE65D86DD2F2F5F23A90B`
- **Keep a pristine copy of the game's `Assets\Data\Map`** somewhere outside the game folder before testing.
  Tests and exports must start from original files.
- The add-on's own install feature backs up to `Assets\Data\Map\pd_addon_backup\` and always reads base files
  from there when present (`exporter.original_path`).

### Repository and add-on

```
git clone https://github.com/eradication0/Phantom-Dust-Content-Creation-Tool
cd Phantom-Dust-Blender-Add-On
py -I tools/build_addon.py                      # -> dist/phantom_dust_stage-<version>.zip
blender --command extension validate dist/phantom_dust_stage-<version>.zip
```

Install in Blender: Edit > Preferences > Get Extensions > menu (top right) > Install from Disk > the zip. Then
Preferences > Add-ons > Phantom Dust Stage > **Game data folder** = the game's `Assets\Data`.

Tests (all must pass before committing; `<Data>` = a folder with original game files):

```
blender -b --factory-startup --python tests/blender_workflow.py  -- <Data> <work_dir>
blender -b --factory-startup --python tests/blender_roundtrip.py -- <Data> <out_dir>
blender -b --factory-startup --python tests/blender_visuals.py   -- <Data> <out_dir>
blender -b --factory-startup --python tests/blender_material.py  -- <Data> <out_dir>
py -I tests/alr_rebuild.py   <Data>\Map
py -I tests/maplight_test.py <Data>\Map
py -I tests/objects_test.py  <map.dat> <map.alr> <out_dir>
```

`blender_workflow.py` copies st04/st09 into `<work_dir>` and never touches the real game folder.
To test with a throwaway Blender profile (not the owner's install), set `BLENDER_USER_RESOURCES` to an empty
folder, then `blender --command extension install-file -r user_default -e <zip>`.

### Ghidra (only for new reverse engineering)

1. Install JDK 21 and Ghidra 12.1.4. Set `JAVA_HOME` to the JDK.
2. Create a project and import + analyse the exe once (slow, ~10+ min):
   ```
   <ghidra>\support\analyzeHeadless.bat <projects_dir> PhantomDust -import <game>\PDUWP.exe
   ```
3. Run scripts headless against the analysed program (read-only, no re-analysis):
   ```
   <ghidra>\support\analyzeHeadless.bat <projects_dir> PhantomDust -process PDUWP.exe -noanalysis -readOnly ^
       -scriptPath <repo>\handoff\ghidra -postScript DumpFuncs.java <out.txt> "140199b00+140199970" 1
   ```
   The `.bat` launcher splits arguments on commas: scripts use `+` or `~` as list separators.
   Ghidra caches compiled scripts: after editing a script, give it a new file name or it may run the old one.
4. Scripts in `handoff/ghidra/` (first comment line of each documents its arguments):
   `DumpFuncs` (decompile addresses + callees to a depth), `DecompileAt`, `DecompileRange` (all functions in an
   address range), `DecompileContaining`, `DecompileNew`, `XrefsTo` (functions referencing data addresses),
   `RefsTo`, `DumpCallers`, `FindStrRefs` (find ASCII/UTF-16 text anywhere and decompile users),
   `DumpRefs`, `GrepRefFuncs`, `FindOffsetOps`, `DumpAsm`, `DumpQwords`, `DumpClass` (methods of named
   vftable classes), `MapFactory` / `MapFlatTable` (walk constructor tables and name the classes).

Image base `0x140000000`. Function names below are Ghidra defaults (`FUN_<address>`).

## 4. Collaboration conventions (owner's preferences)

- **Commit and push only when the owner says "Commit and push"** (or similar). Branch `main`; commit messages
  end with a `Co-Authored-By: Claude ...` line. Never release/tag without being asked.
- The owner tests in game and reports with screenshots. Every in-game test: **back up the game files first,
  install the test files, say exactly what to look for, restore the originals afterwards.** Keep a pristine
  backup; once on the old PC an original was overwritten before backing up and had to be recovered from another
  game copy.
- Use distinct, unmistakable test values (e.g. bright, different colours per variable) so one screenshot
  answers which setting does what.
- Plain language in replies; the owner is a modder, comfortable with Blender and hex, not a programmer by
  trade. Keep README and FORMATS.md current with every confirmed finding ("confirmed" only after an in-game
  test; "read from code" otherwise).
- Don't add features the owner ruled out (intro camera, a code loader for debris speed).

## 5. Architecture

```
addon/phantom_dust_stage/        the Blender extension (zip root = this folder)
  blender_manifest.toml          id, version (1.0.0), blender_version_min 5.3.0, permissions (<= 64 chars each)
  __init__.py                    preferences, Import/Export operators, Collection panel, Lighting panel,
                                 all bpy properties (Collection.pd_*, Scene.pd_*), register()
  scene_tools.py                 New Map Setup, Bake Lighting, Restore Game Original, 3D View sidebar panel
  convert.py                     game <-> Blender coordinates, map list, ROLES, surface parsing
  importer.py, visuals.py        import collision/spawns, and .alr models with textures (PNG-packed)
  exporter.py                    export_models (.alr), export_scene (.dat), lighting, install/restore/backup
  visuals_export.py              Blender meshes -> model meshes; texture handling (Textures class)
  pd_material.py                 PD Stage Shader node group, material panel, export settings (read)
  objects_export.py              Objects collections -> object types, models, colliders, placements
  effects_export.py              Effects collections -> EF00 entries from presets
  _lib.py                        `from .pdstage import ...` (the pdstage package ships inside the add-on)
  pdstage/                       plain-Python readers/writers, no Blender needed
    dat.py                       .dat header, spawns (CP00), collision, placements, effects, clears
    collision_build.py           collision block writer, append, enclosing sphere
    alr.py                       .alr reader: header, textures (DDS export), meshes, vertices, colours, nodes
    alr_build.py                 .alr rebuild/writer (replace roots, add models, textures, shadow mesh)
    objects_build.py             NM00/OB00/PS00 writer, PRESETS, read_objects
    effects_build.py             EF00 writer, KINDS, PRESETS
    maplight.py                  mapLight SSB script parse/build/describe/edit
    cad.py                       st01-only navigation format (on hold)
pdstage/__init__.py              shim: `__path__` points into addon/phantom_dust_stage/pdstage so
                                 `from pdstage import dat` works from the repo root (tools, tests)
tools/                           dump/inspect tools, build_addon.py, test_patch.py
handoff/                         this document and the Ghidra helper scripts (handoff/ghidra/)
tests/                           see section 3
examples/build_example_map.py  builds a full example scene from code and exports it
```

**Packaging gotcha (fixed in `7c2f6fd`):** pdstage used to live at the repo root and was bundled into the
zip by `build_addon.py`. Installing GitHub's auto "Source code (zip)" then gave `No module named 'pdstage'`.
Now pdstage lives inside the add-on folder; never move it back out.

### Scene model in Blender (what users build)

- **Scale**: 1 Blender metre = 10 game units (`DEFAULT_SCALE = 0.1` Blender units per game unit).
- **Coordinates**: game is y-up and left-handed. `blender = (x, z, y) * scale`; `game = (x, z, y) / scale` (a
  mirror; it was `(x, -z, y)` until 2026-11-18, which mirrored every map: see FORMATS.md). The mirror reverses
  winding: every conversion uses `convert.flip_winding`. Game yaw = -Blender rotation z.
- **Spawn facing**: game faces `(sin yaw, 0, cos yaw)`; the spawn empty's +Y is the facing:
  `rotation_euler.z = -yaw`.
- Collections with `pd_role` (Collection Properties > Phantom Dust):
  - `VISUALS`: stage meshes. Children named `Sky...`/`Background...` replace roots 2/1 when "Replace background
    and sky" is on. Texture = image in the material (Base Color chain, else any Image Texture). Lighting =
    colour attribute `PD_Light` (else active colour attribute, else white). Image names matching a game original
    texture (`.001`-style suffix dropped, lowercased, `[^0-9a-z_]`->`_`, first 12 chars) reuse it.
  - `COLLIDERS`: every mesh in it and its children; `pd_surface` hex text, inherited (default `08`).
  - `SPAWNS`: child collections = layouts; spawn = empty with exactly 3 child empties (orbs). Each layout needs
    exactly the game original's spawns per layout; fewer layouts are repeated to fill the slots.
  - `OBJECTS`: child collection per object type: `pd_preset`, `pd_hits`, `pd_damage`, `pd_debris_stays`,
    `pd_jump_power`, `pd_surface`. Meshes directly in it = placements (must share one mesh; scale 1; Z rotation
    only). Optional children `Broken...` (each mesh = one piece), `Debris...`, `Collider...` (default: bounding
    box). Child names matched by lowercase prefix.
  - `EFFECTS`: child collection per effect type with `pd_effect` (STEAM/SPARKS/SMOKE); every object in it = one
    placement (location, Z turn, scale multiplies the effect's own scale).
- Scene properties: `pd_game_original` (default st04), `pd_scale`, `pd_imported` (import sets it; turns Clean
  slate off by default), lighting: `pd_light_custom`, `pd_sun` (Sun light object), `pd_stage_light`,
  `pd_stage_ambient`, `pd_char_light`, `pd_char_ambient` (COLOR_GAMMA, defaults = Panorama Earthquake's).
- Export options: game_original, game_data, scale, background_and_sky, remove_objects ("Clean slate"), shadows,
  install_to_game. Exporting directly into the game's Map folder is refused (use install).

### Export pipeline (exporter.py)

1. `export_models`: read the base `.alr` (from backup if installed before), gather Visuals (+ sky/background) and
   object models, `alr_build.rebuild(base, replace={slot: meshes}, textures=new, add_models=..., shadows_for=(0,))`.
   Object models are appended as new roots; their indices feed the `.dat` object table.
2. `export_scene`: read the base `.dat`; write spawns in place; append new collision block and repoint `0x94`;
   clean slate (`clear_placements`, `clear_effects`); `objects_build.add_objects`; effects via
   `effects_build.set_effects`; lighting via `apply_lighting` (maplight). Everything new is **appended at the end
   of the file with header offsets repointed and `0x138` = file size** (confirmed safe; nothing else moves).
3. Optional install: back up originals once into `Map\pd_addon_backup`, copy outputs over `Map\stNN.*`.

## 6. File formats: summary (details in FORMATS.md)

Map files (paths under `Assets\Data`): `Map\stNN.dat` (gameplay data), `Map\stNN.alr` (visual models and
textures), `Map\stNNcam.alr` (intro camera, unused here), `com\stNN\comdataN.cad` (AI nav, on hold).
Battle maps: st01-st08 and st12-st17, st22-st26 (variants of the same places are separate files);
st09 = Sein; st00 / st09_0x are story stages with a different `.dat` header. Names come from
`setup\stageset\stageset_en.dat` (list in `convert.GAME_ORIGINALS`). Custom maps **replace** an existing map slot
(the game only loads its own); the default and best-tested slot is **st04, Panorama Earthquake** (floor height
64 game units = 6.4 m).

### `stNN.dat` header (u32 offsets, `FFFFFFFF` = none; magic `ST00`)

| Offset | Meaning |
|---|---|
| `0x04 + 4i` (i 0..10) | placement table (`PS00`/`PS01`) per layout slot; a match uses slot layout+1, falls back to 0 |
| `0x30 + 4i` | placement counts per slot |
| `0x5C` / `0x60` | `NM00` object names / object count |
| `0x64`..`0x84` | `OC00..OC02`, `OE00..OE02`, `OA00..OA02` (per-state collision/effects/animation) |
| `0x90` | `OB00` object table (0x38-byte entries) |
| `0x94` | stage collision |
| `0x98` | `EF00` effects |
| `0x9C` | `SP00` (unknown) |
| `0xA0`..`0xBC` | `MD00`, `CP00` spawn layouts (4-6 per map) |
| `0xD0 + 4v` | `mapLight` lighting script for variant v (fallback `0xD0`) |
| `0xF4` | light animation block |
| `0x138` | file size |

- **CP00 spawn entry (0x50)**: `f32 pos[3], f32 yaw, u32 0x80100003, f32 orb[3][3], u32 FFFFFFFF, u32 128,3,24,0,
  u32 flags`. Header word `(size << 16) | count`.
- **Collision record**: `u8 surface, u8 kind (8 vertex list / 3 triangle chunk), u8 0x03, u8 0xFF, u32 size,
  u32 0`; chain ends with a `0xFF` byte. Chunk: centre (smallest enclosing sphere), radius, bbox, u16 count,
  u32 vertex-list index, then 20-byte triangles `u16 a,b,c, u16 0, f32 normal[3]`. The game builds its grid at
  load. Surface types: `08` floors/walls, `07` slopes/stairs (others unknown).
- **Objects**: `OB00` entry = `u32 root[3]` (`.alr` roots: intact, broken, debris) + 9 offsets (`[3..5]` OA
  animation, `[6..8]` OC collision chain in object-local space, `[9..11]` OE effect block) + 2 u32.
  Placement entry (0x24) = `s32 object, u8 category, u8 type, u8 extra6, u8 extra7, u32 0, f32 pos[3],
  f32 rot[3]`. Class by `[category][type]` via factory table `0x1402dc4f0`. Presets (`objects_build.PRESETS`):
  SOLID (1,4), BREAK_SCATTER (2,1), BREAK_ROLL (2,2), CRUMBLE (2,3), BREAK_TOUCH (2,18), WALL (2,7),
  WALL_CRUMBLE (2,8), CEILING (2,12), PILLAR (2,48), JUMP_PAD (4,16). Jump strength = `extra6` (100-250;
  200 ~ twice a 6 m wall).
- **Object node values** (floats at node bytes `0x30-0x3F`, four per node): intact root value[2] = hits to
  break (min 1); broken/debris root value[1] = damage on contact; debris root value[0] = 2 vanishes, 0 stays;
  broken pieces each on their own node with `(3,0,0,0)`, root node flags 0, piece flags 4.
- **Debris physics** (code): speed = sqrt(1200 / max(mass, 200)), capped 1.5 units/frame. Not data-driven.
- **EF00 entry (0x5C)**: `u8 kind, u8 layout filter, u8 FF, u8 0, f32 pos[3], f32 rot[3] (rad), f32 scale[3],
  13 kind-specific values`; table = `EF00, u16 count, u16 bytes, entries`. Kind table `0x1402dc520`
  (`FUN_1401ef940`). Portable presets: STEAM = st09 entry 3, SPARKS = st09 entry 7, SMOKE = st04 entry 21.
- **mapLight script** (SSB): header 0x20 bytes, u32 code words, function table `{base-40 name x2, start word}`.
  Words: `(v<<16)|0x0E` push int; `(lo16<<16)|0x0F` + 32 bits push float/colour; `(id<<16)|(argc<<8)|0x01`
  native call; `5` return. Natives: `2000` light (ambient axis, direction (travel; y<0 = from above),
  light colour, second colour, ambient colour, set), `2002` fog (ignored on PC), `2005` point light, `2001`,
  `2003` (scale 0.7-1.1). Light sets (0x58 bytes at `0x1403e8a40`): **0 = stage + objects + effects,
  1 = characters**, 2/3 = far models. Colours packed `0x00RRGGBB` (red/blue order confirmed).

### `.alr` (models and textures)

- Chunk container: `0x11` header (u32 magic, header size, version `0x52`, resource-buffer offset `0x0C`,
  root count `0x10`, resource size `0x14`, root offsets from `0x20`), `0x15` texture table (0x1C-byte entries,
  names = two u32 base-40 words: chars `\0 0-9 a-z _`), chunk chains per root (`[u32 type][u32 size]`, end at
  type 0), zero padding to `0x1000`, then the resource buffer (vertex/index/texture data; offsets relative to
  it). Textures are **linear** (not swizzled) BC1/BC3/BGRA with mips.
- Chunk types: `0x01` materials (0x4C entries; shader name, vertex format, texture indices), `0x03` nodes (64
  bytes: transform composed T*Rz*Ry*Rx*S then parents; 4 floats at `0x30` read by objects), `0x16` vertex
  buffers (0x1C entries), `0x02` meshes (header 0x68: `+0x08` centre, `+0x14` radius, `+0x18/+0x24` bbox,
  `+0x40` u16 material, node, vbuf, primitive (5 list / 6 strip); indices at `+0x68`), `0x0E`/`0x05` animation.
- Roots in a stage `.alr`: 0 = stage, 1 = background, 2 = sky; objects are further small local-space roots.
- **Vertex format 0x01** (shader `sd`, 0x18 bytes): f32 pos[3]; packed normal u32 at `0x0C` (11/11/10 bits
  signed: x*1023, y*1023, z*511); UV int16 pair /4096 at `0x10`; BGRA vertex colour at `0x14` = **baked
  lighting**, multiplied with the texture (white everywhere = far too bright; keep real baked colours).
- Writer (`alr_build.rebuild`): copies unknown material/vbuf/mesh fields from an existing `sd` mesh of the base
  file; new textures `0x86` BGRA power-of-two (max 1024) with full mips and 12-char names; rebuilding with no
  changes is byte-identical for all 22 maps.
- **Shadow mesh**: shader `sshadowch` (vertex format `0x07`: position + packed normal) holds shadow volumes.
  Without it characters cast no shadow. The writer adds a 1-unit closed box 1000 units below the stage.
- Shaders seen: `sd` (simple), `sbts`/`sbtsrefs` (bump/reflection), `sc`, `svc` + `sbtscloud3` (sky),
  `sshadowch`/`sshadowc`. Fog shader variants exist in the exe (`SDYFOG`, `SBTSYFOG`, ...) but fog is unused.

## 7. Reverse-engineering reference (PDUWP.exe, base 0x140000000)

| Address | What |
|---|---|
| `FUN_140203720` | stage `.dat` loader: header, object table |
| `FUN_140203dc0` | creates placed objects |
| `0x1402dc4f0` | object factory table `[category] -> constructors[type]` (walk with `MapFactory.java`) |
| `FUN_1401d3d70`, `FUN_1401d2c20`, `FUN_1401d3040`, `FUN_1401d4070` | collision load / grid / tree |
| `pdStageObjAHitCrash`, `pdStageObjARoll`, `FUN_1401ec350`, `FUN_1401ec800` | breakable hit/break/debris physics |
| `0x1402dc520`, `FUN_1401ef940` | effect kind -> class table |
| `FUN_140199b00` | runs the `mapLight` script (header `0xD0 + 4*variant`, fallback `maplight%d.ssb` files) |
| `FUN_1402ab840` | SSB script runner |
| `0x1403e8a40` | four light sets, 0x58 bytes each |
| `FUN_140199670` | builds the D3D-style lights from a set; `FUN_140199970(set)` selects a set while drawing |
| `FUN_140199360` | pushes fog render states (0x5C enable, 0x5D mode, 0x5E/0x5F start/end, 0x60 density, 0x8A colour) |
| `FUN_140020660` | render-state setter: **no cases for the fog states** (why fog does nothing on PC) |
| `FUN_1401c87f0` | draws far models with light sets 3 and 2 |

External references:
- Phantom Dust wiki, "Modding / File Formats / ALR" page (ALR chunk layout).
- Torphedo's **Esper-RE** (GitHub): `src/formats/alr.h`, `st00.h` (object table/placement names),
  `ssb.h` / `esper_ssb.hexpat` (SSB script format).
- **desert-breeze-dust** by ZacheerKour (GitHub, original Xbox release): `.alr` container layout.

How findings were confirmed: change one thing in a copy of st04, install, owner plays it. Examples: orbs stacked
on orb 1; spawns raised 250 (players dropped from the sky); yaw + pi (orbs behind); collision lowered 15 (players
sank); 3 hits to break; jump power 200; red/green light colours per set; fog colours (no effect). See the
"How it was confirmed" notes in FORMATS.md and `tools/test_patch.py`.

## 8. Releasing

1. Bump `version` in `addon/phantom_dust_stage/blender_manifest.toml`.
2. `py -I tools/build_addon.py`, then `blender --command extension validate dist/<zip>` (manifest strings such
   as `tagline` and `[permissions] files` must be <= 64 characters).
3. Run all tests. Commit, tag `vX.Y.Z` (annotated), push branch and tag (only when the owner asks).
4. Create the GitHub release for the tag and **attach the built zip** (`gh release create vX.Y.Z dist/<zip>`
   if `gh` is installed and authenticated; otherwise the owner does it in the browser). Remind users to install
   the attached zip, not GitHub's "Source code (zip)" (both work since `7c2f6fd`, but the attached one is the
   clean package).

Release notes for 1.0.0 (for reference): install steps; feature list (stage, collision, spawns/orbs,
shadows, breakables, jump pads, steam/sparks/smoke, sky/background, lighting); workflow (New Map Setup ->
build -> Bake Lighting -> Export with Install); not yet supported (stage-cast shadows, normal maps, variants;
fog impossible); everyone in an online match needs the same map installed; no game files included.

## 9. Gotchas learned the hard way

- Packed DDS images don't survive saving/reopening a .blend: imported textures are converted and packed as PNG.
- Double-sided faces in imports were merged by Blender; zero-area triangles must be dropped on export.
- Huge ground triangles overflow UV storage (int16/4096 = max ~8 repeats): split big planes into a grid.
- An all-white `PD_Light` makes the stage look far too bright; bake real lighting.
- The shadow mesh must be a closed volume; a copy of the stage as shadow mesh breaks the look.
- In scripts, an operator that `report({'ERROR'})`s raises `RuntimeError`; catch it in tests.
- Blender `--command extension validate` catches manifest problems the UI only shows at install time.
- Ghidra headless: `.bat` splits args on commas; edited scripts may be cached (rename them).
- Never export straight over the game files; base files must always be the originals (the add-on enforces this
  with its backup folder; manual tests must do the same).
- The owner's game folder may hold other mods' files (e.g. `_netmod`); only touch `Assets\Data\Map`.
