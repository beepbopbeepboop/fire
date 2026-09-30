# `from . import SUB` then `SUB.f(...)` — link mode prints nothing, returns 0, exit 0, and the `linkmode` gate step is RED on master

**State: OPEN. Not my area, filed by `work/hard-fn-import` while fixing
the (now fixed and deleted) cross-module-import report; see the
2026-09-29 section of `bugs/hard/README.md`. Reproduced on `master`
(10023b8) with no local changes, so it is a pre-existing regression, not
something that fix introduced.**

## What I ran

`test_link_mode.py`'s own second case, on a pristine tree
(`python3 test_link_mode.py`, and then the single function directly):

```
$ python3 -c "import test_link_mode as t; print(t.test_bare_submodule_import_call())"
False
  ✗ bare_submodule_import_call: rc=0 stdout='0\n'
```

The test builds, through the real `driver.compile_program` link-mode
pipeline, this package (its own `pkg` literal, `test_link_mode.py:108-118`):

```python
# pkg2/__init__.py   (empty)
# pkg2/base2.py
def doubleval(x):
    return x * 2
# pkg2/main.py
from . import base2
print(base2.doubleval(21))
```

## What I saw

`python3` on the same text prints `42`. The compiled program prints `0`,
exits 0. **No** "unavailable in compiled mode" line, so this one is silent
even by the standard this repo uses for its worst failures.

It is a REGISTERED gate step: `tools/suite.py`'s `linkmode` entry is
`test_link_mode.py` with no `expect=`, in both `check` and `gate`, and it
currently reports 2 passed / 1 failed. `CLAUDE.md`'s "The gate is otherwise
clean" is therefore out of date for this one step.

## What I expected

`42`.

## Where

Generated C for the repro (link mode, `link_mode=True`), `.tmp/fi/pkg2_p.ci`:

```
int64_t base2_doubleval_9f63a2 (int64_t x)      <-- the real definition, INLINED correctly
...
void _toplevel (void) {
  _t1 = (int64_t)0;  /* ct param or undeclared: base2 */
  _t2 = (int64_t)0;  /* ct param or undeclared: base2 */
  _t3 = 21LL;
  _t4 = _t2;  /* int64_t.doubleval() stubbed */
```

Two separate facts, and only the first is the bug:

1. The **module was found and inlined** — `_link_inline_modules` contains
   `.base2` and `base2_doubleval_9f63a2` is defined in this TU with the
   right signature. So Phase 0 and the inline loop are working; this is NOT
   a resolution failure and NOT a duplicate of
   the cross-module-import report (fixed in the same series; see the
   2026-09-29 section of `bugs/hard/README.md`).
2. The **call site** bound to the "auto-stub a not-yet-resolved struct
   method" path because the bare submodule MARKER `base2` — the name
   `from . import base2` binds — is never registered as a module alias here,
   so `_lower_MemberExpr` reads it as an undeclared identifier
   (`(int64_t)0`) and `.doubleval()` on an `int64_t` is a method call on
   nothing.

The other two cases in the same file pass, and they are the ones that
already work:

- `bare_submodule_import_value_read` — the same marker, read as a plain
  VALUE (`f = base2.doubleval`), passes.
- `from_submodule_import_symbol_value_read` — `from .base3 import triple`
  (an actual symbol import, not a marker), passes.

So the gap is specifically: **a call through a bare submodule marker**
(`from . import M` + `M.f(...)`), not a value read through one.

## The docstring's own claim, checked

`test_bare_submodule_import_call`'s docstring says the landed fix "registers
the call's own syntactically-known module reference into
`_own_imported_func_home` (`_note_own_func_home`, module-qualified) and
resolves the C symbol through the EXISTING `_func_csym`/`_func_qualifier`
tier system", guarded on "the target module's own source independently
confirms `method_name` is a plain, non-generic, non-overloaded top-level
function (gimple_gen_methods.py's new generic branch in
`_lower_method_call`)".

Both halves are worth re-checking, because a guard that can never be
reached produces exactly the observed "stubbed" text. In the generated C
above, `_own_imported_func_home` never supplied a qualifier for `doubleval`
at all — the call site is not even trying to resolve a module, it is
calling a method on an `int64_t`. So the failure is upstream of that guard:
the marker binding is missing, not the guard.

## Exact next step

Start at the marker, not at the method call. `from . import base2` binds the
name `base2` to the module member `'.base2'`. Compare the two mechanisms
that already bind such a name and find the one link mode misses:

- `_register_sym` (`mojo/middle/module_shared.py`, the
  `self._from_import_name_is_submodule(...)` branch) records it as
  `imported_symbols[sym] = {'module': _join_import_member(...), ...}` and
  adds it to `_module_alias_names`. Check whether that path is reached in
  link mode for a TOP-LEVEL `from . import base2`, or whether it is
  `do_imports`-gated the way several neighbours are.
- `_register_link_imports` (`mojo/backend_gimple/emit_resolve.py`) has the
  matching branch (`gen._from_import_name_is_submodule(...)` ->
  `_link_inline_modules.add(_join_import_member(...))`) — that one DOES
  fire, it is what put `.base2` in the inline set. So the inline side is
  registered and the ALIAS side is not; the call site reads the marker
  through the alias path and finds nothing.

Verify by making the call site print its own `_func_qualifier('doubleval')`
and the marker's `imported_symbols['base2']` in link mode.

## Why it is not fixed here

It is a link-mode cross-module call-resolution bug in the marker-binding
path, not the function-scoped-import bug I was working, and the surrounding
area (`_lower_method_call`'s generic branch, `_from_import_name_is_submodule`
bookkeeping) is another claim's territory. Landing a guess at it without the
full gate would be worse than writing it down. It is worth fixing promptly
for a reason beyond the wrong value: while it is red, the `linkmode` gate
step cannot be used to tell a regression from a pre-existing failure.

## Note on how it was found

that report's own "suggested shape of a fix" said a change to the import-inlining area "owes
the full gate plus manual re-triage of the `COMPILE_FAIL_*.md` corpus —
a comparable cross-module resolution fix has regressed that corpus before".
That caution is well placed, and this is what re-triage looks like in
practice: one step was already red before the work started, and nothing
about it was recorded anywhere.
