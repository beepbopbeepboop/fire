# GATE: `make gate` fails in `mojoc` and `selfhost`

Found 2026-11-24 by `make gate` (306 jobs, 2 failed: `mojoc`, `selfhost`). Reproduced 2026-11-25 in the
main tree with `python3 tools/suite.py -j1 mojoc selfhost` (no clean export needed).

## What was wrong, in the order it was peeled (HEAD `a50297eb5`)

1. `unknown type name 'WordFacts'` in `version.py`, `build_config.py`, `jit/arm64.py`,
   `mojo/middle/__init__.py` (every per-module compile of a compiler source file): 19
   `_SELFHOST_SIGS` rows name `WordFacts *`, and only the whole-closure TU defined the type.
   FIXED `e0d1e6aa0` (a struct layout beside `Interpreter`'s; pin `test_selfhost_sig_types_declared.py`).
   The closure TU never showed it, which is why every closure-based check was green.
2. `ld: Undefined symbols` for module globals read through a dotted project import:
   `_types__mojo_global_get_PRESENCE_WORD`, `_comptime__..._CONST_TRUE/FALSE`,
   `_device_select__..._DEVICE/HOST`, `_summary__..._FILE_KIND`, `_float8_dtype__..._FLOAT8_CTYPE_PREFIX`,
   `_module_shared__..._UNKNOWN_FIELD_CTYPE`: the importer named the accessor after the file's
   basename, the definer after its spelling (`mojo_middle_types__...`). FIXED `617f0d05c`
   (pin `test_dotted_module_global_accessor.py`: red `_lib__mojo_global_get_LABEL` before, green after).
3. `ld: Undefined symbols` for five functions whose importer hashed the definer's parameters as
   `int64_t`: OPEN, `bugs/GIR_importer_param_hash_disagrees_with_definer.md` (stage S4).

## Facts for the next round

- Both jobs fail at LINK now, not at gcc: the closure TU compiles with 0 gcc errors at HEAD
  (`gcc-mp-15 -O0 -fgimple` exit 0 on `selfhost_ci.py` output). The three `MojoList * + double`
  errors are fixed (`52e02dc2d`).
- `mojoc` also hit its recipe time limit: `memcap: TIMEOUT ran 20.0 min > 20.0 min time limit` at
  1201 s, peak 8 GB (this was with the errors above, the build fell back per module). A full
  successful build time at HEAD is not yet measured; if it exceeds 20 min the limit in
  `tools/suite.py`'s `mojoc` registration must move (measured, not guessed).
- The suite's interpreter here is python 3.15 (`/opt/homebrew/opt/python@3.15`); the direct builds in
  the earlier sessions used 3.14. Same answers so far; keep it in mind if a difference appears.
- Closure dump with weak stubs (`PRESENCE_WORD`, `_IDENT_CHARS`, `_NONE_TYPE_MARKER`,
  `_WALK_AST_MAX_DEPTH`) is a separate defect: `bugs/mid/GIR_selfhost_four_new_closure_stubs.md`.

## Status

- 2026-11-25: items 1 and 2 fixed and verified (c_oracle identical on 286 + 35, compile_stdlib 610/0,
  test_suite 482/0). Re-run of `selfhost mojoc` after both fixes: see the next entry.
