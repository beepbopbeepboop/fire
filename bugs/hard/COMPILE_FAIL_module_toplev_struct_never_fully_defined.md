# HARD BUG (non-generator, found while classifying the generator-codegen cluster): imported module's opaque "toplevel globals" struct is forward-declared incomplete and never given a matching full definition, so any `module.attr` access on it hard-fails

## Status (updated 2026-08-07, mechanism 2 now ALSO fixed)

**Both mechanisms are now fixed.** See "Mechanism 2 fix (2026-08-07)"
below for the second one, landed in a separate follow-up session from the
mechanism-1 fix (whose original write-up is preserved below for context).

Root-caused to completion. There are **two distinct mechanisms**
producing the identical symptom:

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

## Mechanism 2 fix (2026-08-07)

**Root cause, precisely identified** (via a temporary trace + direct .ci
grep on `Lib/subprocess.py`): the "known-but-not-embedded" scenario the
mechanism-1 fix already handled for a module's own DIRECT compile failure
was too narrow. A module can be **fully, successfully compiled**
(`self._module_stmts[mod]` populated) and still have its real struct
definition text embedded **nowhere** in the final output, because text
propagation is per-PARENT: a nested module's C text only reaches the root
by being threaded, unmodified, through every ancestor's own
`imported_code` list (`if code: imported_code.append(code)` in Phase 0).
If ANY ancestor in that chain itself later fails outright — confirmed:
`os.py` fails on a completely unrelated bug (`'relpath' is ambiguous`,
NOT one of this session's tracked hard bugs) well AFTER its own Phase 0
already successfully, recursively compiled `posixpath` -> `genericpath` —
`os`'s entire returned `code` is discarded, taking its successfully-
compiled descendants' text down with it, while those descendants' own
entries in the SHARED `self._module_globals`/`self._module_stmts` dicts
remain (they commit independently of what their parent does afterward).
Confirmed directly: `grep -c "struct _genericpath_toplev {"` on
subprocess.py's full ~14MB .ci output is **0** (only the incomplete stub,
940 occurrences), and `Imported module: os` never appears in the output
at all.

Old mechanism-1 guard (`mod_str not in self._module_stmts`) can't
distinguish this case from "will definitely be inlined, incomplete stub
is fine" — `self._module_stmts` says "compiled successfully" but says
nothing about whether the text actually survived its ancestor chain.

**Fix**: drop the `self._module_stmts` guard entirely — reconstruct a
full, field-matching struct from `self._module_globals` whenever the
field list is known, unconditionally, in the "other referenced modules"
forward-decl loop. Redefinition risk (this module's real definition MAY
also independently appear later, if its ancestor chain didn't fail) is
handled by a C preprocessor `#ifndef _MOJO_TOPLEV_GUARD_<safe_mod>` /
`#define` / `#endif` pair around each `typedef struct {...} {...};`
emission site — both this reconstruction site and the module's own
"official" per-module emission site (`if self._module_globals.get(
current_mod_name):`) use the identical guard-macro name (derived purely
from the module's own C-safe name), so whichever occurrence ends up
textually first in the final file is the one real definition and every
other one is a harmless no-op — correct by construction regardless of
emission order or how many places attempt it, no Python-side "already
emitted" bookkeeping needed at all.

**A real regression was found and fixed during verification, not just
theorized**: the first version of this fix (guard added, but the
reconstruction loop left in its ORIGINAL position — right after
`all_modules_to_declare` is computed, well BEFORE the `struct_field_types`
typedef block) dropped the targeted "invalid use of undefined type" count
on `Lib/subprocess.py` from 26 to 0, but the file's TOTAL `gcc -fsyntax-
only` error count went **UP**, 788 -> 1123 — new "unknown type name
'_Unknown'"/`'_TupleType'`/`'_LazyAnnotationLib'`/etc. errors appeared.
Root cause: a module's "known field" C type can itself be a pointer to a
Mojo struct/class (`_Unknown *`, from `self.struct_field_types`, NOT the
module-globals mechanism) — reconstructing the module-globals struct
this early referenced those types before their own typedefs existed.
Fixed by moving the entire `for mod_name in sorted(all_modules_to_
declare):` loop to run AFTER the `struct_field_types` typedef block —
the exact same position (and for the identical reason) `external_call[
...]` prototypes and elaborated-instantiation externs already occupy,
per their own pre-existing NOTE comments in the same preamble. After the
move: `Lib/subprocess.py` 788 -> **762** total errors (a net DROP, not a
wash) — the 26 targeted errors gone, zero new error categories introduced
(confirmed via a full before/after diff of error-message categories, not
just totals).

### Verification against real files (2026-08-07, mechanism 2)

`gcc -fsyntax-only` error counts (same flags `compile_stdlib.py` uses:
`-fgimple -I<runtime> -fsyntax-only -D__MOJO_STDLIB_MODE__`), direct
`compile_to_gimple(..., do_imports=True)` + dump to `.ci`, before
(`git stash` on `gimple_codegen.py`, i.e. Phase-1-perf-only baseline) vs
after (this fix):

| file | "invalid use of undefined type" errors | total errors |
|---|---|---|
| `Lib/subprocess.py` | 26 -> **0** | 788 -> **762** |
| `Lib/glob.py` | (present, per symptom list) -> **0** | n/a (no before count taken) |
| `Lib/mailbox.py` | (present, per symptom list) -> **0** | n/a (no before count taken) |
| `Lib/modulefinder.py` | (present, per symptom list) -> **0** | n/a (no before count taken) |

A full diff of error-message *categories* (not just counts) between
subprocess.py's before/after `gcc -fsyntax-only` output shows the ONLY
difference is the exact disappearance of the 26 targeted "invalid use of
undefined type" lines (24 `_genericpath_toplev` + 2 `_posixpath_toplev`)
— every other error category (including the pre-existing, unrelated
`functools.py`/`reprlib.py` "unknown type name 'partial'" errors, and the
`os.py` "'relpath' is ambiguous" failure that blocks a full build of this
file regardless of this fix) is untouched, count-for-count.

Note: `subprocess.py` still cannot fully BUILD+LINK in this session
regardless of this fix — `os.py` itself fails on the separate, unrelated
"'relpath' is ambiguous" bug (not one of this session's tracked hard
bugs), which is a hard blocker for any file that needs a working `os`
module. This fix's scope and verification bar is specifically the
`gcc -fsyntax-only` "invalid use of undefined type" error class, per the
task's own framing — not full end-to-end build success for these
specific files, which remains blocked on an unrelated issue.

### Quality gate (2026-08-07, mechanism 2 fix)

1. `python3 test_gimple.py` — 247 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed.
3. `make check-selfhost` — clean.
4. From-scratch stdlib dylib rebuild — clean, 0 `skip <module>:` lines.
5. `python3 compile_stdlib.py -j8` — 664/664 passed, 0 unexpected
   failures (unchanged from baseline).

### Not attempted / out of scope

- The `os.py` "'relpath' is ambiguous" failure (this session's own
  concrete instance of transitively-imported same-named free functions
  colliding) is a separate, unrelated bug blocking full build success for
  `subprocess.py` and others — not investigated further here.
- No attempt was made to also emit a REAL (non-`extern`) instance
  definition for a module whose only text-propagation path is broken
  (mechanism 2's scenario) — the `#ifndef`-guarded reconstruction here
  only ever produces `extern struct {...} {...};` (a declaration, not a
  defining instance), matching the pre-existing mechanism-1 technique
  exactly. A module in this state would still fail at LINK time with an
  undefined-symbol error for its `_<mod>_globals` instance if a full
  build were ever attempted — out of scope per the `-fsyntax-only`-based
  verification bar above; not otherwise investigated.
