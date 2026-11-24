# GIR stage 2b: two gaps the doc calls done (types.py's gen._emit, build.label)

Found 2026-11-23 reviewing stage 2b (`doc/GIR.md`).

1. **`mojo/middle/types.py` still has four `gen._emit(f"...")` calls** (around lines 2148, 2151,
   2165, 2188, in `presence_set_emit` and its neighbours). The ratchet reports `gen._emit( text: 0`
   only because it skips that whole file (`bugs/GIR_stage4_ratchet_counts_every_type_string.md`
   fixes the skip). Convert each one to the builder, the way the backend modules did in stage 2b:
   `build.assign` / `gen._assign(...)` for an assignment, `build.call_void(gen, 'memcpy', [...])` for
   a call. Read lines 2140-2190 first, and keep the emitted text byte-identical.
2. **`build.label` bypasses the chokepoint.** `mojo/ir/build.py` (`label`, about line 137) does
   `gen.body_lines.append(i)` directly. Every other builder goes through `build.append`, which also
   clears `gen._last_was_terminal`. Skipping the `#line` stamp for a label is deliberate; skipping the
   flag clear is not. Give `append` a `stamp: bool = True` parameter, have `label` call
   `append(gen, i, False)`, and add a case to `test_gir_builder.py` that shows the flag is cleared
   after a label.

## Checks

    python3 tools/c_oracle.py check --base <start sha> -j 4    # identical C
    python3 test_gir_builder.py && python3 test_gimple_lint.py && python3 test_type_string_ratchet.py

Delete this doc in the same commit.
