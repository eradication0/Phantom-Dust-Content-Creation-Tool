# ps: bloat review of OUR add-on changes (d42caa7..roundtrip-fixes 748fde9)

Scope: `git diff d42caa7..748fde9` (our code: +6575 / -267 lines in addon/, tests/, tools/, examples/). Upstream lines
touched only where our change made them redundant. Lines are at 748fde9. "Saved" = net lines removed.
Status: APPLIED (on r-slim, byte-identical), SIDE (byte-changing, branch r-slim-cubedxt, reported apart), or NOT CUT.

Ranked by lines saved:

1. exporter.py:698 `_patch_moved_models` + :818 `_patch_moved_meshes` (fallback) - the import vertex-order walk,
   node-matrix inverse, "a vertex another mesh shares" scan, vertex write and centre/radius/box recompute were
   written twice -> `_import_vertices`, `_node_inverse`, `_write_moved` shared. ~45 saved. APPLIED.
2. motion.py:96 `euler_quat`, `slerp`, :149 `quat_matrix`, `compose`, `mul` - copies of character.py's
   `_q_from_euler`, `_slerp`, `quat_matrix(q, t, s)`, `mul` (same float ops) -> imported; :177 `matrix_quat` and
   :62 `run_length` unused -> deleted. ~72 saved. APPLIED.
3. cubemap.py:16 `face_bytes`, :47 `decode_level`, :72 `decode`, :90 `atlas` - own size table, own B8G8R8A8 /
   swizzle decode and own atlas loop -> texlevels.level_dims / level_bytes / decode_level / mip_atlas (DXT1/DXT5
   per-texel decoder kept: it rounds 565 colours as floor(c*255/31)). ~27 saved. APPLIED.
4. cubemap.py:27-69 legacy DXT decoder - the remaining per-texel DXT1/DXT5 loop -> texlevels.decode_level
   (bit-replicated 565, as dxt.py's encoder and the GPU). ~35 saved. SIDE (r-slim-cubedxt 1eebbe5): every .dat stays identical, but the .alr changes on st03, st08,
   st24 and Ascension (the maps with DXT1 cube maps), all three cycles; st09 / st09_05 stay identical. Not merged.
   It changes import pixels by up to about 1 level per channel; whether that counts as a fix needs a cube-map
   pixel check against the game's own decoder first.
5. townlights.py:49 `read_lights`, :150 `build_stream` packer - a second parser/packer of the chunk-0x09 light
   list that pdstage/enter.py already reads and writes (same 40-byte record) -> enter.read(field=...) /
   enter.build. ~34 saved. APPLIED.
6. exporter.py:635 `visual_shapes` / :667 `object_shapes` (fallback) - the same 18-line mesh digest body twice
   -> `_shape(me)`; digests unchanged (digest(*parts) feeds the same values). ~25 saved. APPLIED.
7. alr_build.py:249 `_templates` - first loop searched the base file for an "sd" mesh and prim-5 fields, then our
   change overwrote `found` with the documented records and `del prim5_unk`: the loop is dead. ~22 saved. APPLIED.
8. stage_extras.py:306 `read_md00` - re-parses MD00 names/pairs that dat.md00 already reads (identical on all 79
   PC / Xbox / Ascension / our-output stage files) -> dat.md00 + a 9-line blob reader. ~16 saved. APPLIED.
9. alr.py:151 `_dds16` - 16-bit unpack (565 / 5551 / 4444) duplicated texlevels.decode_level -> calls it
   (texture_dds identical on all 3138 game textures). ~12 saved. APPLIED.
10. visuals.py:34 `CUBE_FACES`, `cube_face_textures` - unused since cubemap.py -> deleted; `_cube_image` tmpdir
    arg unused. ~14 saved. APPLIED.
11. texlevels.py:55 `_c565` (= dxt._from565), :103 `_morton` wrapper, :191 `box_half` (unused) -> dropped.
    ~16 saved. APPLIED.
12. exporter.py:188 `_add_object_types` - name / definition / sound-row reader written twice -> `_tables`. ~8 saved.
    APPLIED.
13. Small: exporter.py:1577 `sets` (made redundant by our edit()), stage_extras.py:29 `import math`,
    gather_md00 `town` arg, import_md00 `n`. ~4 saved. APPLIED.

Looked at, NOT cut:
- Copy-back fallback (roundtrip.py, scene_digests/model_digests, KEPT_OBJECTS/MOVED_PLACEMENTS/ADDED_TYPES/
  PLACEMENT_EDIT globals, collision_build.patch, _write_placement_table): operator-accepted option; slimmed only
  (1, 6, 12). Removing the module globals would need export_models/export_scene to return a state object: a
  design change, not a trim, and it touches the off-by-default path the rebuild measurement cannot see.
- stage_extras.py:336 `_skeleton` vs alr.skeleton: they disagree on 6 of 5992 roots (count field vs record size):
  not equivalent, kept.
- stage_extras.py:463 `build_md00` vs dat.set_md00: the encoding overlaps (4 lines) but put_md00 also writes the
  blob list: not worth the coupling.
- Enter Lights vs Town_Lights (p1/p3 overlap): already exclusive at import (importer.py:151); export picks one.
  Merging the two collections changes the scene layout: not a trim.
- Sky dome (replace[2] as a node dict vs custom sky meshes): both paths are live (game dome / preset sky).
- tests/blender_rebuild_one.py vs blender_roundtrip_all.py: different modes (fallback off, three cycles / edits
  vs fallback on, byte-identical with the game); shared import/export glue is ~20 lines. Kept.
- tools/check_stage.py vs tools/stage_semantics.py: structure checker with its own readers (independent of the
  add-on on purpose) vs what the game reads; no overlap worth merging.
- No debug/ablation switches or timing code found inside the add-on (grep environ/DEBUG/time.time: none).
