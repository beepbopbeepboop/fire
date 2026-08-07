# HARD BUG (non-generator, found while classifying the generator-codegen cluster): imported module's opaque "toplevel globals" struct is forward-declared incomplete and never given a matching full definition, so any `module.attr` access on it hard-fails

## Status

Unfixed / not root-caused to completion — found and confirmed recurring
2026-08-06 while classifying `CODEGEN_generator_function_Lib_*.md`
(tasks #95-135), but this is **explicitly NOT a generator/coroutine
codegen bug** — filed here only because it was the single most common
blocker preventing several of this cluster's files from reaching a clean
signal about their OWN generators. Confirmed on current master
(`2b0c4c5`). Mechanism partially traced (see below); the deeper "why is
the full struct definition never emitted for these specific modules"
question was not run to ground — flagged for a dedicated non-generator
investigation.

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
_threading_toplev`; and in `Lib/turtle.py` (`struct _selectors_toplev`)
and `Lib/tempfile.py` (`struct _threading_toplev`, `struct
_pprint_toplev`, `struct _io_toplev`, `struct __py_warnings_toplev` —
by far the largest occurrence count of any file in this cluster).

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
more precise (and likely much shorter, or empty) remaining-gap list.

## Not attempted

Root-causing exactly why these specific modules never get a full
`_toplev` definition needs tracing `gen_module`'s module-compile-success/
partial-compile bookkeeping (`self._module_globals`, the "successfully
compiled" set referenced in the incomplete-forward-decl loop's own
comment) — a genuinely separate, non-generator investigation, out of
scope for the pass that found it.
