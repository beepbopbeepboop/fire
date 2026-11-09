# plan/step-19a: build an OPTIONAL runtime unit (sqlite3 first) as a loadable dylib for the formal link line
**Status: DONE 2026-11-07 (measured).** `build_stdlib_dylib.py`: factored shared `_compile_reflect_table()` and added/refined `optional_runtime_dylib(unit, arch)` (Mach-O, CAS-cached by unit/arch/source/effective flags/libs, unit+namespace-filtered `__mojo_reflect`, links unit libs and core runtime, `_arch_or_die`, clear errors for unknown unit/missing source/compile/link including dev-package hint). sqlite3 arm64+x86_64 build: manifest exports `mojo_sqlite3_close` and not `mojo_strlen` (22/22). `python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_runtime_link.py` => `20 passed in 23.60s` / `213 passed, 0 failed, 213 checks`. `python3 tools/memslot.py --gb 8 --label t -- python3 test_runtime_header_scan.py` => `43 passed, 28 failed, 71 checks` (pre-existing census/quote drift only; no files touched by this change). `python3 tools/plan_index.py --check` => PASS.
Class: mid      Size: M      Depends: 15a      Blocks: 19b
Source: `bugs/FORMAL_known_limits.md` §3.1 "What is still open, and it is [1]'s half".

## Current state (measured 2026-11-05; the draft's "registry" already exists and its counts were stale)
- The REGISTRY exists: `build_config.py::_OPTIONAL_RUNTIME_UNITS` (line 125; rows `unit, source, header, link flags, dev pkg, cc, cc flags`; units sqlite3, zlib, ssl, ncurses, metal) with accessors `optional_unit_names/source/header/libs/cc/cc_flags/symbols/namespace` (lines 194-277) and `referenced_optional_runtime_units(c_code)` (:416) — the GIMPLE path uses them.
- The FORMAL path links ONLY the core runtime: `formal/build.py::_runtime_library_for` (:21880) -> `runtime_library(arch, fmt)` (:21777) -> `build_stdlib_dylib.runtime_dylib(arch=arch)` (:1380, builds `runtime_units(arch, None)` i.e. NOT the optional units, see `_RUNTIME_UNITS`). Pinned by `test_formal_runtime_link.py` (`STR_CALL` case: `mojo_strlen("hello")` exits 5).
- Measured census (`python3 -c "from formal import model as M; a=M.runtime_abi(); ..."`): 897 entry points, 411 word-shaped (`entry['word']`). Per optional unit (entries/word-shaped): sqlite3 22/16, zlib 6/2, ssl 13/11, ncurses 18/16, metal 6/5. The draft's 683/272 are stale; `bugs/FORMAL_known_limits.md` §3.1 figures (871/405) are older than this too: update them in 19c.
- `mojo_sqlite3_open` is NOT word-shaped; the 16 word-shaped ones are `close errmsg exec step finalize bind_int bind_text bind_null column_count column_type column_name column_int column_text column_bytes last_insert_rowid changes`.

## Decisions already made
- Add `build_stdlib_dylib.py::optional_runtime_dylib(unit: str, arch: str = None) -> str`, modelled on `runtime_dylib`: compile `build_config.optional_unit_source(unit)` for `arch` with `optional_unit_cc(unit)` / `optional_unit_cc_flags(unit)` (default: the same compiler/flags `runtime_units` uses for a C unit), link as a Mach-O dylib with `optional_unit_libs(unit)` (e.g. `-lsqlite3`), CAS-cached under a key that includes unit name, arch, source digest and flags, with the same `__mojo_reflect` table + `_arch_or_die` check `runtime_dylib` does. Reuse `runtime_dylib`'s helper functions; if they are inline in `runtime_dylib`, factor the shared part into one private function used by both (CLAUDE.md: consolidate, no parallel copy).
- Mach-O only (ELF stays refused exactly as `runtime_library` does).
- The unit dylib exports ONLY its own namespace (`optional_unit_namespace(unit)`), so a name can be covered by exactly one library.

## Work order
1. Read `runtime_dylib` (:1380-end of function) and `runtime_units`/`_RUNTIME_UNITS` (:340); factor, then write `optional_runtime_dylib`.
2. Unit test in `test_formal_runtime_link.py` (copy `test_word_shaped_call_links_and_runs`' style, no program yet): `optional_runtime_dylib('sqlite3', arch)` returns an existing file; its manifest (`formal.build.load_dylib_manifests([path])[0]['map']`) contains `mojo_sqlite3_close` and does NOT contain `mojo_strlen`. Both arches only if the x86_64 toolchain builds (the existing runtime tests do both; mirror whatever they do for x86_64 skips).
3. If the host lacks the dev library (`-lsqlite3` link fails), the function must raise a clear error; add the case `a missing unit library is an error, not a silent skip` using `unit='nosuchunit'` -> raises.

## Do NOT
- Do not touch `formal/build.py` here (19b). Do not add the unit to `_RUNTIME_UNITS` (that would put sqlite on every image's link line).
- Do not cache by unit name alone.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_runtime_link.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_runtime_header_scan.py
python3 tools/plan_index.py --check
```

## Done when
- [ ] new cases pass; every pre-existing case in `test_formal_runtime_link.py` and `test_runtime_header_scan.py` has the same verdict as before
- [ ] `runtime_dylib`'s bytes for the core library are unchanged (cache key unchanged: `ls` the CAS entry before/after or compare `runtime_dylib()` path)

## If stuck
Write the toolchain error verbatim into §3.1 Status and stop.
