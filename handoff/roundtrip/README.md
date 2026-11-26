# Phantom Dust Stage add-on: round-trip fixes

Changes to the Phantom Dust Content Creation Tool's Blender add-on ("Phantom Dust Stage"), made on top of release
**1.3.0** (commit `d42caa7`). The goal: import a stage (`Map/stNN.dat` + `stNN.alr`) into Blender and export it again
so that the result is built entirely from the Blender scene (no bytes copied from the original file) and a player
cannot tell it apart in game. Every original map was tested this way.

## What is in this zip

| Path | What |
|---|---|
| `addon/phantom_dust_stage-1.3.0-roundtrip.zip` | the add-on with all changes, ready to install in Blender (Edit > Preferences > Add-ons > Install from Disk) |
| `changes.patch` | every change as one diff against 1.3.0 (`git apply changes.patch` in a checkout of `d42caa7`) |
| `changes-stat.txt` | the files the patch touches, with line counts |
| `changed-files/` | the full current version of every changed or new file, at its path in the repository |
| `deleted-files.txt` | files removed relative to 1.3.0 (empty if none) |
| `notes/ROUNDTRIP_FIXES.md` | **start here**: what was wrong, how it was fixed, and the measured results per map |
| `notes/FIELD_MAP.md` | every stage-file field, what it means in game, how it is represented in Blender, and how it was proven |
| `notes/p1-...` to `notes/ps-...` | the detailed research notes behind the fixes (one file per topic, see below) |

The version number inside the add-on was left at 1.3.0; set it as you like.

## Headline results (export built from the scene, copy-back fallback off)

- All 37 stage files tested (29 PC including the town areas, 7 Xbox, the Ascension 0.4 community map) come back
  field-for-field equal to the original apart from a few small listed items, and stay stable over three
  import/export cycles.
- In-engine renders of all 20 battle maps differ from the original by a mean of 0.27-2.2 per channel (0-255), the
  town by 0.27-1.81, Ascension by 0.11.
- Fixed along the way, among others: dark floors (game shaders' normal / reflection / specular maps were dropped),
  the dark town (light lists, light-mapped floors, 16-bit normal maps), lost spawn-pillar shading (object vertex
  normals), flipped bumps on mirrored UVs (tangent rule), the replaced sky dome, missing breakable-object shadows
  (shadow volumes), the game's own lower mip levels and texture formats (579 of 1400 PC textures have hand-made lower
  levels), normal-map alpha (it is the reflection mask on `sbtsrefs` and the shine mask on `sbts`), collision chunking,
  per-placement object behaviour/sounds/collider kinds, sprites, stage-model animations, cube maps.
- An optional, off-by-default "copy-back" fallback can reuse the original bytes for untouched parts; it was never used
  in the measurements above.

Still open (listed in `ROUNDTRIP_FIXES.md`): the effect models in the MD00 slots and the town area files' props are
still taken from the game file; one beam near the iron road on st02/st12/st22; shadow normals on 4 broken sign pieces;
small differences on st17's lit windows and st22's road; 4 textures whose lower mip levels are rebuilt.

## The research notes

The work was split into topics; the notes keep those names:

- `p1-visual-findings.md`: visual differences (pillar shading, normal maps, the dark town, the sky)
- `p2-stage-sections.md`: sprites, the stage-model list, enter lights, object animations, cube maps, 16-bit textures
- `p3-dropped-data.md`: per-draw light lists, joints, effect chunks, the sky dome
- `p4-roundtrip-differences.md`: dark floors, file size / collision chunking, object placements
- `p5-field-verification.md`, `p5-experiments.md`: field-by-field verification against the game's code and Xbox
  experiments (a modified map run in an emulator)
- `pm-mips.md`: mip levels and texture formats
- `ps-bloat-review.md`: a review that removed duplicated and dead code (output proven byte-identical)

Code addresses in the notes refer to the original Xbox executable and the 2017 PC version's executable; they describe
what the game does, no game code is included. No game files, extracted assets or screenshots of game data are in this
zip. Paths like `<local proof folder>` refer to working folders on our side that are not included.
