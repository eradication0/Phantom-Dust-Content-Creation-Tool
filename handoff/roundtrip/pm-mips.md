# pm: stage texture mip levels and formats (2026-11-26)

- Claim: the game's lower mip levels are authored pictures, not a box reduction of level 0. Evidence: original files
  only, <local proof folder> (+ mipsurvey.json): 579 of 1400 multi-level stage textures (PC,
  30 files) differ from the box of the level above by > 6/255 mean at some level; Xbox identical counts. No clean
  gap in the distribution (0-40), so the count depends on the threshold; noise floor of a box reduction 1-5.
  Confidence: high that many are custom; the exact count is threshold-bound.
- Claim: the engine samples them at a distance; regenerating them changes the far look. Evidence: engine renders,
  st08 corner_c 8.29 -> 0.31 once the game's levels are written back (sheets in proof/plugin-pm/eng). High.
- Claim: uncompressed formats with mips exist in the game up to 512 px (0x85 B5G6R5 512x512, 0x86 256x256), and
  can be written back as such. Evidence: format survey (scripts/fmtsurvey.py), re-encode test byte-identical
  (cct r-mips tests/texlevels_test.py), engine renders unchanged. High.
