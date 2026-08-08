# HARD BUG: two different real classes sharing a bare name across modules corrupt each other

## Status (reassessed 2026-08-08 — deprioritized, not fixed)

Re-verified both originally-confirmed real-world triggers against current
master using the actual, default, user-facing command
(`python3 mojo.py build <file>.py`):

- `Lib/tkinter/filedialog.py` — **builds clean**, no struct-collision
  errors (runs, hits an unrelated separate bug at runtime —
  `AttributeError: curdir` from an unresolved-import stub, out of scope).
- `Lib/tkinter/simpledialog.py` — **builds clean** as well.

Neither reproduces via `mojo.py build` anymore. Root cause: `mojo.py
build` now goes through `driver.py`'s module-cache "link mode" FIRST
(`driver.compile_program`, see its own docstring: "compiles the client
in link mode (extern decls)... content-addresses the whole program...
If the link path can't produce a binary we return None so the caller
can fall back to the inline builder"), only falling back to the
`do_imports=True` whole-program inline builder
(`gimple_codegen.compile_to_gimple_cached`, `mojo.py build_executable`)
on failure. Link mode compiles EACH imported module as its OWN separate
translation unit/dylib — `tkinter/dialog.py`'s `Dialog` and
`tkinter/commondialog.py`'s unrelated `Dialog` are never in the same
`struct_field_types`/`_struct_name_owner` dict at once, so the
collision this doc describes is structurally impossible on that path.
`compile_stdlib.py` (the quality-gate corpus tool) uses the same
per-module compile primitive (`build_stdlib_dylib.compile_module_to_c_
cached`), which is why its 664/664 clean-compile corpus has never
caught this bug either — same reason, independently confirmed.

**The underlying gap is still real and confirmed live** — a fresh
minimal 2-file repro
(`class Dialog: def __init__(self, widgetName): self.widgetName = ...`
in one file, an unrelated `class Dialog: def __init__(self, result):
self.result = ...` in a sibling file, both constructed from a third
file) invoked directly against the vulnerable entry point
(`gimple_codegen.compile_to_gimple_cached(src, do_imports=True, ...)`,
bypassing `driver.py` entirely) reproduces the exact documented
mechanism: the generated C has ONE `struct Dialog { int64_t
widgetName; }` typedef, and BOTH classes' `__init__` methods get
emitted under the SAME qualified C symbol name
(`mod_a_Dialog___init__`, even for the class that's really from
`mod_b` — confirming `_struct_method_qualifier`/`_imported_struct_home`
resolve to the WRONG home module for the "loser" struct, not just a
missing-qualification gap), with the second one writing to `self->
result` — a field that doesn't exist on the struct that won the
bare-name race. This would fail with both a C redefinition error
(same symbol name emitted twice) AND a "no member named 'result'"
error, exactly matching this doc's originally-documented symptoms.

Today, in practice, this inline `do_imports=True` entry point is only
reached as `mojo.py build`'s degraded fallback (triggered when link
mode itself fails for unrelated reasons — driver.py's own docstring:
"we accept things break, but a program that can build still does") and
by `--dump-full`. Since link mode is tried first and both originally-
confirmed real-world instances succeed on it, this bug currently has
**no known live, reachable instance** through any of this project's
primary, supported entry points (`mojo.py build`, `compile_stdlib.py`,
the stdlib dylib build). Given the fix this doc's own plan calls for
touches genuinely foundational, shared struct-identity machinery
(referenced by field access, method dispatch, reflection, construction,
and forward-declaration emission — the doc's own "Risk" section already
rates this moderate-to-high, and it has been deliberately deferred
twice before under the same reasoning), attempting the general fix now
— for a bug with zero live reachable instances on any primary path —
is not the right risk/reward trade. Deprioritized, not attempted.
Revisit if: (a) a real-world file is found where link mode itself
falls back to the inline builder AND that file also hits a genuine
same-bare-name collision, or (b) `do_imports=True` becomes a primary
(not fallback-only) path again for some other reason.

## Original status (2026-08-06/07, historical)

Unfixed. Concrete diagnosis + phased plan below (2026-08-06). Found while
fixing bugs/COMPILE_FAIL_tkinter_filedialog.md's original symptom (now
fixed, see commit `a907260`) — the ORIGINAL bug was masking this deeper
one: `tkinter/filedialog.py`'s own `_Dialog(commondialog.Dialog)`
inheritance couldn't even be resolved before, so this never got compiled
far enough to reach the current failure.

**2026-08-07**: repro re-confirmed reproducing byte-for-byte identically
on current master (`python3 mojo.py build
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py` — same
`conflicting types for 'tkinter_commondialog_Dialog___init__'`/`'Dialog'
has no member named 'widgetName'/'parent'/'result'/'initial_focus'`
errors as originally documented). Implementation deliberately NOT
attempted this session: assessed the 4-step plan below against the
current code (`_struct_name_owner` at gimple_codegen.py:3649, the
registration loop at ~26765-26771, Phase 2a's per-StructDef method
compile loop) and confirmed steps 1 and 3 are more tractable than the
original write-up suggested (Phase 2a already iterates real `StructDef`
objects with real `id()` identity, not just names, so "is this the
`_struct_name_owner`-registered winner for its own bare name" is a
cheap, local check at each struct's own method-compile site) — but step
2 (propagating which-qualified-class a given VALUE resolves to, through
to every later field-access site derived from it, for the general case
where the disambiguating construction-site signal isn't locally
available) is a genuinely broad dataflow problem, and the doc's own
"Risk" section's warning — partial qualification "will just move the
corruption to a different consumer instead of fixing it" — was judged a
real, not theoretical, risk given this project's documented history of
exactly this class of regression from narrower changes to adjacent
shared machinery (see `bugs/COMPILE_FAIL_collections___init__.md`).
Given the "moderate-to-high" risk this doc's own Risk section already
assigns, and this being core struct-identity machinery "referenced by
field access, method dispatch, reflection..., constructor lowering, and
forward-declaration emission" (far broader blast radius than a
preamble-only change), deferred to a dedicated pass with a larger time
budget rather than attempting a partial version under time pressure.

**2026-08-07 (Track B session)**: a second, independent real-world
instance found (not investigated/fixed, purely logged per this
project's "elaborate the bugs database" convention) — `python3 mojo.py
build /Users/mrs/net/Python-3.14.6/Lib/typing.py`: `Lib/_collections_
abc.py` defines `class _CallableGenericAlias(GenericAlias):` and `Lib/
typing.py` INDEPENDENTLY defines its OWN, unrelated `class
_CallableGenericAlias(_NotIterable, _GenericAlias, _root=True):` (line
1615) — same bare name, same shape of bug: `redefinition of
'_collections_abc__CallableGenericAlias___repr__'`/`___reduce__`,
`conflicting types for '..___getitem__'`, `'_CallableGenericAlias' has
no member named '__parameters__'/'__module__'`. Same root cause, same
"deferred to a dedicated pass" status — not attempted here either,
explicitly out of scope per this session's own assignment (task #141).

## Symptom

```
error: conflicting types for 'tkinter_commondialog_Dialog___init__'; ...
error: 'Dialog' has no member named 'widgetName'
```
or, depending on which file's `Dialog` "wins" the name first:
```
error: redefinition of 'tkinter_commondialog_Dialog___init__'
error: 'Dialog' has no member named 'parent'
error: 'Dialog' has no member named 'result'
```

## Repro

Real: `Lib/tkinter/dialog.py` defines `class Dialog(Widget):` (fields
`widgetName`, `num`, ...). `Lib/tkinter/commondialog.py` defines a
COMPLETELY UNRELATED `class Dialog:` (fields none of the same). `Lib/
tkinter/simpledialog.py` defines YET ANOTHER unrelated `class
Dialog(Toplevel):` (fields `parent`, `result`, `initial_focus`, ...).
Real Python has zero ambiguity — each file imports whichever `Dialog` it
needs under its own binding (`from tkinter.dialog import Dialog`, or
stays qualified as `commondialog.Dialog`) — but any TWO of these reaching
the same whole-program compile (e.g. `tkinter/filedialog.py` transitively
pulls in `tkinter/dialog.py`'s `Dialog` AND `tkinter/commondialog.py`'s
`Dialog`; `tkinter/simpledialog.py` pulls in its OWN `Dialog` AND
`commondialog.py`'s) corrupts one of them.

Not yet minimally reproduced with a small hand-written 2-file repro (a
first attempt using `from a import Dialog as ADialog` + a same-named
local `Dialog` compiled clean — the real files' actual trigger involves
`from tkinter import *` wildcard imports pulling in `Dialog` transitively
through `tkinter/__init__.py`'s own re-exports, a shape not yet isolated
down to a minimal case). The two REAL, directly-confirmed repros
(`Lib/tkinter/filedialog.py`, `Lib/tkinter/simpledialog.py`, both via
plain `python3 mojo.py build <file>.py`) are solid, reproducing evidence
on their own — see their exact errors above, captured directly from the
real compiler.

## Root cause (confirmed)

`gen_module`'s struct pre-registration pass (gimple_codegen.py:~26440-26463)
uses `self._struct_name_owner: dict[str, int]` (name -> `id()` of the
StructDef that "owns" that bare name) as a cross-module-shared collision
guard: the FIRST StructDef seen anywhere in the transitive closure under
a given bare name claims `struct_field_types[name]`/`_class_attrs[name]`;
every OTHER StructDef with the same bare name is skipped entirely at this
registration step (`if self._struct_name_owner.get(s.name) != id(s):
continue`) — this guard exists specifically to prevent the WORSE bug it
replaced (silently MERGING two unrelated classes' fields into one
Frankenstein struct — see its own docstring, "two unrelated classes
sharing a bare name... must NOT have their fields merged").

But this guard only protects the FIELD-TABLE REGISTRATION step. Phase 2a
(gimple_codegen.py's per-statement body-compilation loop) is NOT gated by
`_struct_name_owner` at all — it iterates `stmts`/`imported_stmts`
directly and compiles EVERY StructDef's methods it finds, including the
"loser" class's. Those method bodies (e.g. `Dialog.__init__` from
whichever file lost) get compiled against `struct_field_types['Dialog']`,
which by then belongs entirely to the WINNING class — any field access
the loser's own methods make that isn't ALSO a field of the winner either
hard-fails ("has no member named") or, worse, silently reads/writes the
wrong offset if the two structs happen to share a same-named-but-
different-meaning field.

## Why this wasn't caught before

Two real classes sharing a bare name AND both being reachable in the SAME
whole-program transitive-closure compile is uncommon in the curated
test_gimple.py/compile_stdlib.py corpus (which mostly compiles one
stdlib module's dependency tree at a time, rarely hitting two unrelated
same-named classes at once) but is a completely ordinary shape in a large
real-world package like `tkinter` with many small, independently-named-
after-their-purpose dialog files.

## What a real fix needs

This codegen's struct-identity model currently assumes one bare class
name maps to exactly one real class within a whole-program compile — true
almost everywhere except this shape. A real fix needs genuine cross-
module-qualified struct identity, mirroring the pattern this codegen
ALREADY uses for the analogous free-function and struct-METHOD-symbol
collision cases (SB-1 project: `_func_qualifier`/`_imported_func_home`
for free functions, `_imported_struct_home`/`_struct_method_qualifier`
for method SYMBOLS) — just not yet applied to the struct's own FIELD
TABLE / TYPE IDENTITY itself:

1. When `_struct_name_owner` detects a genuine collision (a second
   StructDef, different identity, same bare name), instead of silently
   skipping its registration, register it under a MODULE-QUALIFIED key
   (e.g. `f"{home_module}::{name}"`, mirroring `_struct_method_qualifier`'s
   existing qualification scheme) in `struct_field_types`/`_class_attrs`
   — do NOT drop it.
2. Every consumer that currently looks up `struct_field_types[bare_name]`
   for an instance whose STATIC type is ambiguous between two same-named
   classes needs to resolve to the right qualified entry instead. Since
   this codegen already tracks a value's real originating type in several
   places (`_actual_types`, construction-site tracking, `_imported_struct_
   home`), the disambiguation signal usually already exists at the point
   a value is CONSTRUCTED (`Dialog(...)` called from within a specific
   module's own compile context resolves unambiguously to THAT module's
   Dialog) — the gap is propagating that resolved identity through to
   every later field-access site on values derived from it, not
   re-deriving "which Dialog" from the bare type name alone.
3. Phase 2a's struct-method compilation loop needs to use each struct's
   OWN qualified field table (from step 1) when compiling its methods,
   not the bare-name lookup that currently always wins for whichever
   struct claimed the name first.
4. C symbol emission (the `struct Dialog { ... }` typedef, `Dialog_init`-
   style method symbols) already has SOME qualification machinery
   (`_struct_method_qualifier`) for methods — extend it to also qualify
   the STRUCT TYPEDEF NAME ITSELF when a genuine bare-name collision is
   detected (two real, structurally-different structs), so the two C
   struct definitions don't collide either. A struct with NO collision
   keeps its current unqualified name unchanged (no behavior change for
   the overwhelmingly common non-colliding case).

### Verification

1. The minimal 2-file repro above compiles, links, and runs correctly —
   `x.widgetName` prints `"a"`, `y.result` prints `"b"`, no cross-
   contamination.
2. `Lib/tkinter/filedialog.py` and `Lib/tkinter/simpledialog.py` (both
   real, confirmed-live triggers) compile clean.
3. Full quality gate (test_gimple.py, test_module_cache.py, make
   check-selfhost, from-scratch dylib rebuild, compile_stdlib.py -j8) —
   this touches core struct-identity machinery used by every single
   compiled struct, so a regression here would be broad; all four (plus
   compile_stdlib.py) must stay green, not just the two new repros.

### Risk

Moderate-to-high. Struct identity is foundational — referenced by field
access, method dispatch, reflection (`_mojo_dispatch_getattr`/`dataclasses.
fields()`), constructor lowering, and forward-declaration emission. The
qualification must be applied CONSISTENTLY everywhere a bare struct name
is currently used as a dict key, or partial qualification will just move
the corruption to a different consumer instead of fixing it. Recommend
implementing behind the EXISTING `_struct_name_owner` collision-detection
signal (only qualify when a real collision is detected, never for the
common single-owner case) to keep the change's blast radius scoped to
genuinely-colliding names.
