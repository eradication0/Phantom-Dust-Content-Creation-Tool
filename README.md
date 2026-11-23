# Phantom Dust Blender Add-On

Build custom maps for **Phantom Dust** (2017 Windows release) in **Blender 5.3** and play them in the game.
You model the map in Blender, tag a few collections, and export. The add-on writes the game's own map
files (`stNN.dat` and `stNN.alr`) and can install them for you.

| Map feature | Status |
|---|---|
| Visible stage with your own textures and baked lighting | Works in game |
| Collision with surface types (floors, walls, slopes) | Works in game |
| Spawn points and orb points (several layouts) | Works in game |
| Character shadows | Works in game |
| Props and breakables (hits to break, debris damage, debris stays) | Works in game |
| Jump pads | Works in game |
| Effects: steam, sparks, smoke | Works in game |
| Your own sky and background | Works in game |
| Game lighting for the stage and characters (sun direction and colours) | Works in game |
| Fog | Not possible: the PC version ignores fog |
| Materials: highlight colour and shininess, shine mask, normal maps, reflection maps | New in 1.1, in-game test pending |
| Transparent materials (checkbox and slider) | New in 1.3 |
| Scrolling textures (water, lava, glow; speeds per layer) | New in 1.3, works in game |
| Stage shadow casters (import, Stretch/Fix Shadow Casters) | New in 1.3 |
| Scale guides: the player model on spawns, the aura capsule on orbs (viewport only) | New in 1.3 |
| Characters: load, animate, export over a battle character | Works in game |
| Characters: texture export / extract / import, readable bone names, shine paint, extended Check | New in 1.3 |

Skill animations/projectiles are planned later.

## What's new in 1.3

- **Transparent** checkbox and **Transparency** slider on the Phantom Dust material (the game's see-through
  shaders; survives import and export of the game's own maps).
- **Scrolling Textures** on the Phantom Dust material: colour, normal map A and normal map B each with an X / Y
  speed; Solid, See-through or Glow. Uses the sky's cloud shader, lit by the map's light.
- The 20 MiB model data limit is checked on export, and unused textures and vertex data of the replaced map are
  stripped.
- Light baking: point lights in the Lighting collection, over-bright light in the light map's alpha, a more
  faithful preview; fixed a crash at the end of a bake.
- Shadow casters: imported with maps, **Stretch/Fix Shadow Casters** stretches them away from the sun.
- Breakable objects: break and debris sounds to pick per collection.
- Hide / Show Broken Parts button; colliders drawn as light-green wireframes.
- Scale guides: Edgar T-posing on every spawn and the aura capsule on every orb (never exported).
- Characters: **Export Textures of Selected**, **Extract All** / **Import** textures (converted to the game's
  format), cut-out and shine alpha shown correctly, the lighting lookup and the shine mask kept on export,
  **Readable Bones** (game names kept and exported), **Shine Paint** vertex paint layer, and a **Check** that
  covers textures, bones, weights, UVs and materials.

You need your own copy of the game. This repository contains no game files.

## Install

1. Get `phantom_dust_stage-<version>.zip` (from the releases, or build it: `python tools/build_addon.py`
   writes it to `dist/`).
2. Blender 5.3: **Edit > Preferences > Get Extensions**, menu (top right) **> Install from Disk**, pick the zip.
3. **Edit > Preferences > Add-ons > Phantom Dust Stage**: set **Game data folder** to the game's
   `Assets\Data` folder (the one with `Map\st04.dat` in it).

Everything is in the 3D View sidebar: press **N**, tab **Phantom Dust**.

## Quick start

1. **New Map Setup** (sidebar). In an empty scene it makes the tagged collections, a 30 m floor with its
   collider, one spawn layout (4 spawns, 3 orbs each), a jump pad in the middle and a sun.
2. Model your map under **Visuals**. Put simple shapes for what players stand on and bump into under
   **Colliders**. Move the spawns and orbs where you want them.
3. **Bake Lighting** (sidebar): bakes the sun and sky light into the stage's colours.
4. **Export...**: pick the map it **Replaces**, tick **Install into the game**, save anywhere outside the game
   folder. The game's own files are backed up first.
5. Start the game and play that map. **Restore Game Original** (sidebar) puts the game's own files back.

`examples/build_example_map.py` builds a complete example (walls, pillars, ramp, platform, crates, benches, a
jump pad, effects, sky and background) and exports it:

```
blender -b --factory-startup --python examples/build_example_map.py -- <Assets/Data folder> <out_dir>
```

## Building a map

Tags go on **collections**, in **Collection Properties > Phantom Dust**. Objects inside need no tags.
1 Blender metre = 10 game units (the default scale).

**Visuals**: the visible stage. Each material's image is the texture (power-of-two sizes are best; larger than
1024 is resized). Lighting is a colour attribute named **`PD_Light`**: the game multiplies the texture by it.
Bake Lighting fills it; you can also paint it. Images whose names match one of the game original's textures
reuse that texture. Keep each triangle within 8 texture repeats (larger UVs are clamped).

**Materials** (Material Properties > **Phantom Dust Material**): stage materials use the **PD Stage Shader**, a
node group with only the settings the game's stage shaders have. New Map Setup and Import use it; **Make
Phantom Dust Material** converts any material (its image becomes the Diffuse texture).
- **Maps**: **Diffuse** (the texture), **Normal Map** (OpenGL style, green up; set the image to Non-Color; its alpha
  also masks the highlight; **Strength** scales the bumps: the game has no such setting, so the exporter rescales
  the map's pixels), **Reflection Map** (a sphere map added on top). Which maps are set picks the game
  shader: simple (`sd`), normal map (`sbts`), reflection (`sdrefs`) or both (`sbtsrefs`); the panel shows which.
- **Highlight**: **Specular Color** (colour and strength of the sun's shine; black = none, as on most of the game's
  surfaces; the game uses dark to mid grey, about 0.1-0.5, and full colours are very strong) and **Shininess** (how
  exactly a face must face the sun's reflection to shine: low = most sunlit faces glow, high = only faces at the
  right angle; the game uses 2-80). The game works the shine out per vertex, so a flat face shines evenly all over:
  there is no small highlight spot. Curved or bevelled shapes show it best.
  **Shine Mask** says where the highlight and reflection show: one value, or **Paint Shine Mask** (brush button) to
  paint it (white = shine). **Reflection Strength** scales the reflection map.
- **Lighting**: **Baked Light** = the `PD_Light` colour attribute that Bake Lighting fills. Normal-mapped surfaces
  are lit by the game's sun and use only the bake's red channel, as shade.
There is no roughness, metalness or emission in the game's stage shaders: Shininess is the closest to roughness.
- **Game Preview** (on by default; sidebar and material panel): in Material Preview, PD materials show what the
  game draws, worked out like the game's shader: texture x baked light x (sun x facing + ambient), plus the shine,
  using the scene's Sun and the Phantom Dust Lighting colours, in the game's colour space. Set Color Management to
  **Standard** (New Map Setup does) so the colours match. Approximate: the ambient is one colour (the game blends
  two), and the shine's view term assumes a value not yet read from the game. Bake Lighting switches it off while
  baking.
Materials that don't use the PD Stage Shader export their image with no highlight.

**Sky and background**: child collections of Visuals named `Sky...` and `Background...`, exported when
**Replace background and sky** is ticked (otherwise the map's own animated sky stays). A big inward-facing
sphere textured with a gradient works as a sky; give it a white `PD_Light`. They use the simple shader, so they
don't animate.

**Colliders**: every mesh inside (and in child collections) becomes collision. Faces must point the way players
stand on or hit them (Blender face normals; check with Face Orientation). **Surface type** (hex) on a collection
applies to its children: `08` (the default) for floors and walls, `07` for slopes. Players who drop below game
height 0 are put back on the map by the game, so no kill floor is needed, but every floor must stay above 0 (the
export warns). Special walls: `12` stops players only (camera and attacks pass), `1F` stops only the camera (keeps
it inside the arena), `14` stops walking but lets a jump through. The dropdown's tooltips explain each one.

**Spawn Points**: each child collection is one layout (`LAYOUT_1`, `LAYOUT_2`...). In a layout each spawn is an
empty whose **+Y axis is the facing** (Blender's green arrow) with exactly **3 child empties** as its orb points.
Each layout needs as many spawns as the game original has (4 in most maps). With fewer layouts than the map
has, they are repeated; the game picks one per match.

**Objects** (props, breakables, jump pads): an Objects collection holds one child collection per object type.
Every mesh directly in a type collection is one placement (use linked duplicates; turn about Z only; scale 1).
Model the object around the world origin. On the type collection:
- **Behaviour**: the game's own object classes: Solid, Break Scatter, Break Roll, Crumble, Break Touch, Wall,
  Wall Crumble, Ceiling, Pillar, Jump Pad.
- Breakables: **Hits to break**, **Debris damage**, **Debris stays**, and optional child collections `Broken`
  (each mesh is one piece) and `Debris`. Debris speed is set by the game from the piece's size (lighter pieces
  fly faster, up to a fixed limit).
- Jump pads: **Jump power** (the game's pads use 100-250; 200 launches a player about twice a 6 m wall).
- Optional child collection `Collider` (default: a box around the model).

**Effects**: an Effects collection holds one child collection per effect type (**Effect**: Steam, Sparks,
Smoke). Every object in it (empties work well) is one placement: location, turn about Z, and scale.

**Lighting** (Scene Properties > **Phantom Dust Lighting**, tick the header): the game lights the stage, objects
and effects with one light and characters with another. Each has a **Light** colour and an **Ambient** colour
(the shaded side). **Sun**: the game's light follows this Sun's direction; use the sun you baked with. The game
multiplies the stage's baked colours by its light, so keep the stage colours near the defaults unless you want
a tint. Off: the game original's lighting is kept.

## Export

**File > Export > Phantom Dust Stage (.dat)** or the sidebar's **Export...**:
- **Replaces**: the map slot the map takes over (the game only loads its own maps). That map supplies
  what the scene doesn't have: without Colliders, Spawn Points or Visuals its own are kept.
- **Clean slate** (on for new maps): removes the game original's own props and effects.
- **Replace background and sky**, **Character shadows** (on).
- **Install into the game**: copies the result over the map in the game data folder, after backing up the
  game's files once into `Map\pd_addon_backup`. Exports always start from the game's own files (the backup),
  never from a map installed earlier. Without it, copy `stNN.dat` and `stNN.alr` over the game's yourself.

Everyone in an online match should have the same map installed.

**Editing an existing map** (secondary): **Import Game Original...** loads a map's collision, spawns and (with
**Visible model**) its stage, background and sky with textures. Edit and export back to the same slot; Clean
slate is off for imported maps so their objects stay.

## For developers

See [handoff/HANDOFF.md](handoff/HANDOFF.md) for setting up a new machine and continuing the work, and [FORMATS.md](FORMATS.md) for every decoded format and how it was confirmed in game. The readers and writers
are plain Python in `addon/phantom_dust_stage/pdstage/` (no Blender needed; `import pdstage` works from the repository root).

```
python tools/dump_dat.py      Map/st04.dat --spawns       header, layouts, spawns, collision summary
python tools/collision_obj.py Map/st04.dat st04_col.obj   collision to OBJ
python tools/render_stage.py  Map/st04.dat st04.png       picture of collision, spawns and orbs (needs Pillow)
python tools/dump_alr.py      Map/st04.alr --root 0       models and textures
python tools/dump_ssb.py      Map/st04.dat                the map's lighting script
python tools/test_patch.py    ...                         the in-game test edits (writes a new file)
python tools/dump_cso.py      <game>/SD_vs.cso            a game shader's constants and code
```

Tests (Blender without a window, or plain Python):

```
blender -b --factory-startup --python tests/blender_workflow.py  -- <Assets/Data folder> <work_dir>
blender -b --factory-startup --python tests/blender_roundtrip.py -- <Assets/Data folder> <out_dir>
blender -b --factory-startup --python tests/blender_visuals.py   -- <Assets/Data folder> <out_dir>
blender -b --factory-startup --python tests/blender_material.py  -- <Assets/Data folder> <out_dir>
python tests/alr_rebuild.py   <Assets/Data/Map folder>
python tests/maplight_test.py <Assets/Data/Map folder>
python tests/objects_test.py  <map.dat> <map.alr> <out_dir>
```

`blender_workflow.py` works on a copy of the game's files: setup, bake, export with install, a second export,
and restore.

## Credits

The `.alr` container layout builds on [desert-breeze-dust](https://github.com/ZacheerKour/desert-breeze-dust)
by ZacheerKour (original Xbox release).
