# HARD BUG: calling a name imported (possibly aliased) from an external/relative package this compiler doesn't resolve

## Status

Unfixed. Concrete implementation plan below (2026-08-06) — reuses two
patterns this codegen already has for structurally identical problems
(the struct-method "unavailable in compiled mode" weak stub, and the
`_C_RESERVED_FUNCS` definition/call-site rename chokepoint), rather than
building real external-package/relative-import resolution (correctly
still considered out of scope — this compiler has no business trying to
resolve arbitrary third-party Python packages).

## Symptom class

`load_module()` (`module_loader.py`) only resolves imports from this
compiler's own tracked Mojo stdlib/test set. Any import from something else
— real Python's `os`/`sys`, a relative import (`from . import x`), or any
third-party/unmodeled package — raises; `gen_module`'s `FromImportStmt`
handler catches that and records the imported name(s) in
`self._unresolved_import_aliases` (added this session) with no real type
info.

When such a name is later **called**, there is no real C symbol backing it,
so the call fails one of two ways:

- `implicit declaration of function 'X'` / an undefined-symbol **link**
  error — nothing ever defines `X`.
- `conflicting types for 'X'` — `X` collides with something this compiler
  already emits under that exact literal C name, most commonly `main`
  (the program's own synthesized C entry point is *also* literally named
  `main`).

## Minimal repro

```python
# aliasmain.py / aliasmain.mojo
from os import getcwd as main
main()
```

```
aliasmain.mojo:10:5: error: conflicting types for 'main'; have 'int(int, const char **)'
```

## Real-world files exposing this

- `Lib/tkinter/__main__.py` — `from . import _test as main` (relative
  import).
- `Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py` — `from idlelib.pyshell
  import main` (external/unmodeled package).
- `Tools/clinic/clinic.py` — `from libclinic.cli import main` (external
  package).
- `Tools/c-analyzer/c-analyzer.py` — same tail symptom, but independently
  also blocked by an unrelated bug elsewhere in the same file (not part of
  this issue).

## What's already there (the two patterns this plan reuses)

1. **Weak-definition "unavailable in compiled mode" stub**
   (gimple_codegen.py:11602-11635, `_lower_struct_method_call`'s auto-stub
   path): when a struct has an unresolved base class, an inherited method
   call gets a REAL (if trivial) definition —
   `__attribute__((weak)) int64_t NAME (...) { mojo_print("...unavailable
   in compiled mode..."); return 0; }` — instead of a bare forward
   declaration. This was deliberately switched FROM decl-only TO a weak
   definition specifically because decl-only left an undefined symbol at
   **link** time (see that code's own comment referencing
   `bugs/consolidated/COMPILE_FAIL_cc_error_ld_returned_n_exit_status.md`).
   The FREE-function analogue of this same auto-stub pattern
   (gimple_codegen.py:17464-17479, and its `_lower_call`-expression-context
   twin) was never given the same treatment — it still only emits a bare
   `int64_t NAME (...);` forward declaration, so a call to an unresolved-
   import name reaches this exact same "declared but never defined" link
   failure the struct-method path already fixed once.

2. **Definition/call-site rename chokepoint** (`_C_RESERVED_FUNCS`,
   gimple_codegen.py:2713 + its consult sites): an existing, single-place
   mechanism for "this Mojo-level name must never be emitted under its own
   literal C name because this codegen's OWN output already uses that C
   name for something else" — currently scoped to libc collisions
   (`exit`, `printf`, `memcpy`, ...), renaming both the definition and its
   call sites to `mojo_<name>` consistently. `main` needs the exact same
   treatment for a different reason (collides with the synthesized
   entry-point `int main(int, char**)`, not libc) — the renaming
   *mechanism* is identical, only the trigger set differs.

## Implementation plan

### Step 1 — give the free-function auto-stub path a real (weak) definition

In both auto-stub sites that currently emit only
`int64_t {fname} (...);`:
- gimple_codegen.py:17475-17478 (`_gen_stmt_ExprStmt`'s statement-context
  auto-stub)
- its `_lower_call`-expression-context twin (same "Auto-stub completely
  unknown names" comment, elsewhere in `_lower_call`)

When `raw_name in self._unresolved_import_aliases` specifically (NOT the
general "unknown name" case — an ordinary same-TU forward reference to a
not-yet-emitted user function must keep the current decl-only behavior,
since a real definition genuinely follows later; only names we KNOW will
never get a real definition need the weak-stub treatment), emit the same
shape the struct-method path already uses:

```c
#ifndef _MOJO_STUB_{FNAME}
#define _MOJO_STUB_{FNAME}
__attribute__((weak)) int64_t {c_name} (...) {
  mojo_print((char *)"{fname}: unavailable in compiled mode "
                      "(imported from an unresolved external/relative module)");
  return (int64_t)0;
}
#endif
```

This alone fixes every case in the "Real-world files" list EXCEPT the
`main`-alias collision (Step 2 below) — `idlelib.pyshell.main`,
`libclinic.cli.main` (both plain names, no collision with a literal `main`
symbol emitted for other reasons *by that same file*... except they
ARE literally named `main` too, so Step 2 applies to all of them, not just
the minimal repro).

### Step 2 — rename `main`-colliding unresolved-import stubs, reusing `_C_RESERVED_FUNCS`'s pattern

Add a small, purpose-specific analogue: when the auto-stub in Step 1 fires
for a name that is *also* `'main'` (or any other single-fixed-purpose
name this codegen's own synthesized output always emits literally — audit
for others, but `main` is the only confirmed one from the real-world
corpus), emit the weak definition under a renamed C symbol
(`_unresolved_import_main`, mirroring `mojo_<name>`'s existing convention
for the libc case) instead of the literal `main`, and make the CALL SITE
that triggered the auto-stub emit a call to that renamed symbol too — this
needs a small side-table (`self._unresolved_import_renames: dict[str,
str]`, populated at the same point the stub is registered, consulted by
`_emit_call`/`_call_expr`'s name-resolution the same way `_C_RESERVED_FUNCS`
already is at gimple_codegen.py:30737-30738) so the call-lowering and the
stub definition always agree on the same renamed symbol.

Both steps together make `from os import getcwd as main; main()` compile
and link clean, printing a clear runtime message instead of either
misdirecting to the real entry point (the bug 12ff719 already fixed) or
colliding with it (this bug).

### Step 3 — verification

1. The minimal repro compiles, links, and — run — prints the "unavailable
   in compiled mode" message instead of crashing or silently doing
   nothing.
2. `Lib/tkinter/__main__.py`, `Mac/IDLE/IDLE.app/Contents/Resources/
   idlemain.py`, `Tools/clinic/clinic.py` via `py314_harness.py`/direct
   `mojo.py build` — confirm the specific "conflicting types"/"implicit
   declaration" symptom from this doc is gone for each (an unrelated
   remaining error, as already noted for `Tools/c-analyzer/c-analyzer.py`,
   is an acceptable outcome per this session's established norm).
3. Full quality gate (test_gimple.py, test_module_cache.py, make
   check-selfhost, from-scratch dylib rebuild, compile_stdlib.py -j8) —
   Step 1's change is gated tightly (`_unresolved_import_aliases`
   membership only), so risk of regressing the ordinary same-TU forward-
   reference auto-stub case should be low, but must be confirmed, not
   assumed.
4. Add a `test_gimple.py` case exercising the exact `from X import Y as
   main` shape end to end (compile + link + run), since this is the one
   real-world instance with genuinely new, specific, verifiable behavior
   (a clean run producing the runtime warning) rather than just "stops
   erroring".

### Risk

Low. Both steps are narrowly gated (`_unresolved_import_aliases`
membership, and within that, `== 'main'` for Step 2) and additive — no
existing passing call site should be reachable through either new branch.
The main risk is under-auditing Step 2's "other reserved names" list;
starting with just `main` (the only confirmed real-world collision) and
extending later if another concrete instance surfaces is the right scope,
not trying to enumerate every hypothetical collision up front.
