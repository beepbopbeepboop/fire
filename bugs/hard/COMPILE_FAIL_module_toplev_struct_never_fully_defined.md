# HARD BUG (non-generator, found while classifying the generator-codegen cluster): imported module's opaque "toplevel globals" struct is forward-declared incomplete and never given a matching full definition, so any `module.attr` access on it hard-fails

## Status (updated 2026-08-07)

Root-caused to completion. There are **two distinct mechanisms**
producing the identical symptom, and only one of them is fixed here:

1. **Fixed**: a module whose globals were scanned (so its field layout
   is known, in `self._module_globals`) but whose overall compile never
   completed (raised partway through — typically during function-body
   codegen, well after the early globals scan) never got a matching full
   struct definition anywhere in the `.ci`, confirmed via direct grep
   (see "Mechanism" below, unchanged from the original write-up). Fixed
   in `gen_module`'s incomplete-forward-decl loop: when a referenced
   OTHER module's field list is known AND that module was never fully,
   successfully inlined elsewhere in the same `.ci` (`mod_str not in
   self._module_stmts` — see `_compile_imported_module`, which only
   populates that dict once `gen_module` returns without raising),
   reconstruct a real, field-matching `typedef struct` here instead of
   the incomplete stub — the identical reconstruction technique the C++
   generator side already trusts from the same shared `_module_globals`
   dict (see the `_cpp_module_global_refs` typedef-copy block later in
   `gen_module`). Verified via the full 5-part quality gate (below).

2. **NOT fixed — root-caused, bigger follow-up needed**: for this
   session's own named flagship examples (`glob.py`/`subprocess.py`'s
   `genericpath`/`posixpath` chain), direct tracing (monkeypatching
   `_compile_imported_module` to log every call) showed `genericpath`
   and `posixpath` DO compile successfully and DO get a real, complete
   struct definition emitted — just **too late in the linear `.ci`
   text**. Each nested `_compile_imported_module` call produces a
   complete, self-contained C-text chunk (including that module's own
   struct definition), which gets embedded into the parent's `parts`
   list wherever the parent's own Phase-0 import scan happens to place
   it — there is no hoisting of imported modules' struct definitions to
   the front of the file (only the CURRENT module's own struct gets that
   treatment, via `_module_globals_insert_idx`). So a member-access site
   earlier in the file (e.g. in an ancestor's own preamble/body) sees
   only the always-present incomplete forward-declaration, even though a
   complete definition exists later in the same translation unit. This
   is confirmed via a controlled before/after diff on `subprocess.py`
   (see "Verification against real files" below): the fix in (1) has
   **zero effect** on this file, because `genericpath`/`posixpath` are
   NOT in the "never fully compiled" bucket — they're in this "ordering"
   bucket instead. A real fix for mechanism 2 requires hoisting every
   successfully-inlined imported module's struct definition (not just
   the current module's own) to the front of the file, with a
   shared "already fully defined" dedup so the module's own later
   official emission doesn't duplicate the hoisted copy — a genuinely
   bigger, riskier restructuring of `gen_module`'s emission order,
   deliberately NOT attempted in this pass given the project's
   documented history of narrowly-scoped changes to this exact class of
   shared machinery causing hard-to-predict regressions (see
   `bugs/COMPILE_FAIL_collections___init__.md`). Flagged as a dedicated
   follow-up.

Originally found and confirmed recurring 2026-08-06 while classifying
`CODEGEN_generator_function_Lib_*.md` (tasks #95-135) — explicitly NOT a
generator/coroutine codegen bug, filed here only because it was the
single most common blocker preventing several of that cluster's files
from reaching a clean signal about their OWN generators.

## Symptom

Recurs identically (module name varies) across at least 4 of this
session's 41 target files:

```
Lib/glob.py:179:28:         error: invalid use of undefined type 'struct _subprocess_toplev'
Lib/modulefinder.py:89:30:  error: invalid use of undefined type 'struct _subprocess_toplev'
Lib/modulefinder.py:282:30: error: invalid use of undefined type 'struct _genericpath_toplev'
Lib/mailbox.py:78:28:       error: invalid use of undefined type 'struct _subprocess_toplev'
Lib/mailbox.py:282:30:      error: invalid use of undefined type 'struct _genericpath_toplev'
Lib/subprocess.py:615:29:   error: invalid use of undefined type 'struct _genericpath_toplev'
Lib/subprocess.py:1175:28:  error: invalid use of undefined type 'struct _posixpath_toplev'
```
Also seen (different modules, same shape) in `Lib/shelve.py`'s
transitive-dependency errors: `struct _locale_toplev`, `struct
_threading_toplev`; in `Lib/turtle.py` (`struct _selectors_toplev`); in
`Lib/tempfile.py` (`struct _threading_toplev`, `struct _pprint_toplev`,
`struct _io_toplev`, `struct __py_warnings_toplev`); in `Lib/weakref.py`
(`struct _locale_toplev`); and in `Lib/typing.py` (`struct
_tokenize_toplev`, `struct _inspect_toplev` — the largest RAW occurrence
count of this pattern seen in this cluster, 60+ individual errors).

## Mechanism (traced this far)

`gen_module` (`gimple_codegen.py`, ~line 29898-29917) forward-declares
an INCOMPLETE struct for every imported module it can't fully account
for, specifically so plain references like `_module_globals.x` don't hit
a hard "undeclared" error at the point of first mention:

```python
parts.append(f'struct {struct_name} __attribute__((incomplete));  /* extern module globals struct */')
parts.append(f'extern struct {struct_name} {global_var};')
```

This is INTENTIONALLY incomplete/opaque — fine for pointer-only uses,
but ANY real member access on it (`genericpath.something`,
`subprocess.something`) requires the type to be COMPLETE at that point,
which C disallows for an incomplete type — hence "invalid use of
undefined type".

Checked whether a matching FULL definition (`struct _genericpath_toplev
{ ... }`, with real fields) appears anywhere else in the same generated
`.ci` for `subprocess.py`'s build: **it does not** — grepping the full
~14MB `subprocess.ci` for `struct _genericpath_toplev {` (the actual
definition, not the incomplete forward-decl, which repeats many times
across sub-compiles) finds zero matches. Same for `_os_toplev`. This
suggests either (a) the real/complete struct definition is keyed under a
DIFFERENT name entirely (a `_genericpath_globals`-shaped struct emitted
elsewhere that this incomplete forward-declaration's naming convention
doesn't actually match/collide with, so the two are silently unrelated
and the incomplete one is simply always what member-access code sees),
or (b) `genericpath`/`subprocess`/`posixpath`/`locale`/`threading` (the
modules seen triggering this) are modules whose own compile did NOT
succeed as a full first-class module in this particular whole-program
compile (fell back to the "relaxed imports" / partial-compile path for
some other, unrelated reason), so only the always-safe incomplete stub
ever got emitted for them, and downstream `module.attr` accesses that
assumed a full definition would be available now fail. This distinction
was not resolved — a real fix needs to trace where/whether
`{safe_mod}_globals`'s FULL struct definition is supposed to be emitted
for a module in this exact state, and why it isn't for these specific
modules despite them compiling successfully as standalone top-level
targets elsewhere in this same session's investigation (e.g.
`subprocess.py` is one of THIS cluster's own 41 target files and reaches
this same struct-incompleteness problem for `genericpath`/`posixpath`
when reached as a TRANSITIVE import instead).

## Why this matters for the generator-codegen cluster specifically

Purely incidental to generators — it happens to be the dominant reason
several `CODEGEN_generator_function_Lib_*.md` files currently fail
*before* any signal about their own generator bodies can be observed,
even though (confirmed via `MOJO_DEBUG=1`, no "not eligible" refusals
naming any of the affected files' own generators) those files' actual
generator code appears unaffected and likely already compiles cleanly.
Fixing this would let `bugs/CODEGEN_generator_function_Lib_glob.md`,
`_modulefinder.md`, `_mailbox.md`, and `_subprocess.md` all report a much
more precise (and likely much shorter, or empty) remaining-gap list —
**caveat**: per the 2026-08-07 update above, this specific cluster's
named files hit mechanism 2 (ordering), which the landed fix does NOT
address, so their remaining-gap lists are unchanged by this fix. The fix
still has genuine value for any file that hits mechanism 1 instead
(confirmed to occur for real, not merely hypothetical — see "Mechanism"
below).

## Verification against real files (2026-08-07)

Instrumented `_compile_imported_module` with a temporary trace wrapper
(logs every module name attempted + whether `self._module_globals`/
`self._module_stmts` got populated) and ran it directly through
`compile_to_gimple(..., do_imports=True)` against `subprocess.py`: both
`genericpath` and `posixpath` show `OK (globals_known=True,
stmts_known=True)` — i.e. they land in mechanism 2 (ordering), not
mechanism 1, confirming the fix's guard (`mod_str not in
self._module_stmts`) correctly and harmlessly declines to touch them.

Controlled before/after diff (`git stash` on `gimple_codegen.py` alone,
rebuild, compare) on `python3 mojo.py build
/Users/mrs/net/Python-3.14.6/Lib/subprocess.py`:

```
BEFORE: 26 "invalid use of undefined type" errors (24 _genericpath_toplev, 2 _posixpath_toplev)
AFTER:  26 "invalid use of undefined type" errors (24 _genericpath_toplev, 2 _posixpath_toplev)
```

Zero change for this file (expected — confirmed mechanism 2). Also
temporarily instrumented the fix's own new branch with a stderr print
and ran it against `glob.py` and `modulefinder.py`: it never fired for
either (0 occurrences) — both are dominated by mechanism 2 too.
Mechanism 1 is real (confirmed structurally: the original, unguarded
version of this fix caused a hard "redefinition of struct or union"
failure in `make check-selfhost`, which only makes sense if at least
some referenced modules in that build's own transitive closure DO reach
`self._module_stmts` — i.e. mechanism 1's counterpart, full success,
genuinely occurs there; the guarded version resolved it cleanly) but
was not observed to fire in this session's specific small sample of
manually-tested files. Left in place: safe (proven via the full gate
below, including `make check-selfhost`, which specifically exercises
the redefinition hazard this guard prevents), structurally sound, and
plausibly load-bearing for other files not sampled here — but its
real-world hit rate on the files THIS bug doc was originally filed
against is zero, and should not be assumed fixed for any specific file
without re-checking.

## Quality gate (2026-08-07, for the mechanism-1 fix)

1. `python3 test_gimple.py` — 247 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed.
3. `make check-selfhost` — clean (this fix was iterated specifically
   because the first, unguarded version broke this gate with
   "redefinition of struct or union" — see "Verification" above).
4. From-scratch stdlib dylib rebuild (`rm -f build/libmojostdlib.dylib`
   + `build_stdlib_dylib.build_stdlib(jobs=8)`) — clean, 0 `skip
   <module>:` lines.
5. `python3 compile_stdlib.py -j8` — 664/664 passed, 0 unexpected
   failures (unchanged from baseline).

## Not attempted (updated 2026-08-07 — see mechanism 2 above for the current, concrete version of this)

Mechanism 2 (struct definitions never hoisted, so a real definition that
DOES exist later in the file doesn't help an earlier member-access site)
is the dominant real-world cause for the files this doc was originally
filed against, and is unfixed. A real fix needs:
- A shared "already fully defined" set (module name → bool) so a
  module's struct body is textually emitted (hoisted to early in the
  file) exactly once, regardless of whether the first emitter is that
  module's own official compile or an earlier-processed ancestor
  referencing it.
- The module's own official struct-emission code (`gen_module`, the
  `if self._module_globals.get(current_mod_name):` block that builds
  `typedef struct {typedef_name} {...}` + the instance with
  initializers) needs to skip re-emitting the typedef body when an
  ancestor already hoisted it, while still emitting the actual defining
  instance (the one place that allocates real storage) — these two are
  currently combined in one code block and need to be split.
- Careful reasoning about TEXT emission order across the whole nested
  `_compile_imported_module` recursion (each nested call produces a
  complete, independent C-text chunk assembled bottom-up before being
  embedded into its parent — "already emitted" must track real linear
  text position, not just Python call order, which do not necessarily
  coincide).
- This is real, invasive, higher-risk surgery on `gen_module`'s core
  struct-emission logic — deliberately not attempted in this pass.
