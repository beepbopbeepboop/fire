# CODEGEN_generator_function: Lib/turtle.py

## Status (updated 2026-08-06)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'Vec2D' does not name a type` .cpp error no longer
reproduces. `turtle.py` has 3 bare `yield` sites (no value, lines 1312,
3442, 3586) — none appear in the current error list, and `MOJO_DEBUG=1`
shows no "not eligible" refusal for any of them: turtle.py's own
generators now appear to compile cleanly through the coroutine path.

**Classification: NOT a generator-codegen-cluster failure anymore.**
Current errors are all unrelated:
- `bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_defined.md`
  (6th confirmed occurrence, here for `selectors`):
  `turtle.py:264:27: error: invalid use of undefined type 'struct _selectors_toplev'`
- Several other apparently-unrelated non-generator bugs: `mojo_open_file`
  called with 2 args but declared to take 1
  (`turtle.py:171`), implicit declarations of
  `genericpath_isfile_584a43`/`ntpath_split_0c85c9`/`ntpath_join`
  (`turtle.py:213/218/219` — looks like a module-qualified-symbol
  resolution gap distinct from the toplev-struct issue, since these are
  function CALLS not member-struct accesses), and a `MojoList *` field
  assigned from a raw `int` at `turtle.py:218`.

Not investigated further — out of scope for this generator-codegen
cluster.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/turtle.py
