# Plan: Bootstrap resource blowup census (CODEGEN_bootstrap_resource_blowup)

Source bug: bugs/hard/CODEGEN_bootstrap_resource_blowup.md

## Decomposition

Step 1 — Run the census (measurement only)
  Measure resource usage during bootstrap build.
  Files: tools/, no code change.

Step 2 — Identify hotspots
  Profile memory/time.

Step 3 — Apply targeted fixes
  Per hotspot.
