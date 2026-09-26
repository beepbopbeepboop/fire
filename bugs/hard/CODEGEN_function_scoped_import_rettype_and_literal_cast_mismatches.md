# HARD BUG (4 distinct root causes, same symptom cluster): GIMPLE type mismatches from (1) function-scoped-import return-type default drift, (2) `_new_val`'s missing `_Bool` literal-cast guard, (3) uncast `self` in `super().method()` calls, (4) imported-class name mistaken for a zero-arg accessor function in `X.ATTR` member access

**State: CLOSED.** Inherited methods keep their defining module's #line; the constructor-call residual no
longer reproduces.


## Status (2026-09-25 — Mechanism 4's CONSTRUCTOR-CALL residual no longer reproduces; the weakref.py `#line` misattribution is FIXED)

Two things changed since the last re-verification entry.

### Mechanism 4's `Parameter(...)` constructor-call residual: NOT REPRODUCIBLE

The residual was: `Parameter('values', Parameter.VAR_POSITIONAL)` — a
constructor CALL on an imported class name — colliding with the class's own
later-registered `typedef`, because at the moment the call is lowered the
class may not yet be in `struct_field_types` (an ordering race). A minimal
two-file repro (`inspect.py` defining `class Parameter`/`class Signature`,
plus a module doing a **function-scoped** `from inspect import Parameter,
Signature` and then `Signature([Parameter('values',
Parameter.VAR_POSITIONAL)])`) now compiles with **zero** `error:` lines, and
the generated C contains a real `typedef struct Parameter {...} Parameter;`,
a real `inspect_Parameter___init__`, the `_MOJO_STUB_Parameter` guard already
defined, and no colliding weak stub.

The whole-program inline path evidently no longer takes the
"unresolved import → weak stub" route for a name that the closure genuinely
defines as a class, so the ordering race the doc describes no longer has a
live failure mode on this path. **Not re-attempted**: the doc's own prior
assessment (a fix here means reordering class registration across the whole
transitive closure, which this project's `CODEGEN_function_scoped_import_
call_unresolved_at_link.md` records as having passed the entire quality gate
and then being reverted after a corpus-wide regression) is unchanged, and
with no reproduction to fix there is nothing to verify a change against.
The genuinely-reachable path today — `Lib/enum.py` itself — is refused
outright for a completely different, already-documented reason (its
`_iter_member_`/`_iter_member_by_def_`/`_iter_member_by_value_` classmethod
generators), so it cannot even reach this code.

### `Lib/weakref.py`'s `#line` misattribution: FIXED

"Not fixed" item 1's finding 1 was that errors in a mixin base class's
method body, re-emitted inside a SUBCLASS's compiled unit, carried the
SUBCLASS's `#line` filename with the BASE's line number — hence
"weakref.py:962" in a 574-line file, whose real source is
`_collections_abc.py:819-822`. **Reproduced and fixed.**

Root cause: `_merge_struct_inheritance` copies a base class's
`FunctionDef` node objects into the subclass's `.methods`; the struct
method-body emission loop then emits each one again as `Sub___m`, and
`gen_stmt` took its filename from `gen._current_filename` — which is the
module being compiled — rather than from the node's real origin. Every
statement node carries only a `line`, never a file.

Fix, entirely additive (no emission ordering touched):
- `GimpleGen._module_source_paths` (module name -> the absolute path its
  source was read from), populated in `_compile_imported_module` next to
  the `_abspath` it already computes for its own `#line` directives, and
  shared into each nested `temp_gen` like its sibling shared dicts.
- `module_gen` snapshots each struct's OWN method-node identities before
  the merge, then afterwards maps every node the merge INJECTED back to the
  module that originally declared it (`self._inherited_method_src`).
- The method-body emission loop sets `self._line_src_file` for the duration
  of an inherited method's emission, and `gen_stmt` prefers it over
  `_current_filename`.

The emitted C is byte-identical apart from the `#line` directives
themselves (verified by diffing with all `#line` lines stripped), so this is
a pure diagnostics fix with no codegen semantic surface. Regression test:
`inherited_method_line_directive_names_its_own_module` in `test_gimple.py`,
which builds a real two-file closure and asserts the `Sub___eq__` body
carries the base module's `#line 3 "<base>.py"` and not the subclass's.

## Re-verified 2026-08-26, wtRest19b (fresh pass, no code change; full-corpus repro not completed due to heavy concurrent system load)

Confirmed all four fix sites still present and unchanged in current
source (`gimple_gen_funcs.py:414`'s `ret = sig[0] if sig else
'int64_t'`; `gimple_gen_resolve.py:964`'s `ctype in ('int64_t',
'_Bool')` guard; `gimple_gen_methods.py:561`'s `fake_obj_type =
f"{base_name} *"` derived-to-base cast; `gimple_gen_exprs.py:909`'s
PascalCase-import guard). Attempted a fresh full `subprocess.py`/
`enum.py` isolated-compile re-run to reproduce the doc's own
error-count methodology, but this session's system is running 5+
concurrent `fire.py build` processes from other campaign agents
(opencode groups on ctypes/dyld/analyzer/util, other worktrees) —
every attempted repro (both the full `fire.py build subprocess.py` and
a standalone `compile_to_gimple(enum.py)` isolated-compile) exceeded
the mandated wall-clock safety bound (~300s, RSS stayed low so this is
contention, not a runaway) before reaching GCC or a result, and was
killed per the safety rule rather than left running unbounded. A
minimal standalone repro of the `Parameter(...)` constructor-call shape
(`from inspect import Parameter; Parameter('values', Parameter.
VAR_POSITIONAL)` in an isolated single-file module) built and ran
clean, but doesn't reproduce the doc's actual failure mode — that
needs the intra-module ordering race in a module the size of
`enum.py`/`inspect.py` where `Parameter` is a same-module class defined
earlier, not a cross-module import stub, which this minimal repro
doesn't exercise. Given source-level confirmation that nothing has
regressed the four landed fixes, and the already-documented,
already-assessed architectural risk of touching the class-registration-
ordering machinery for Mechanism 4's residual (this doc's own
2026-08-07 section: a comparable ordering fix elsewhere in this
campaign passed the full quality gate and still had to be reverted
after a corpus-wide regression), status is carried forward unchanged
rather than force a resource-contended repro. Not attempted; no code
change.

## Re-verified 2026-08-23 (fresh pass, no code change)

All four fix sites confirmed present and intact after the Wave-2 file
split of the old monolithic gimple_codegen.py: Mechanism 1's `ret = sig[0]
if sig else 'int64_t'` now lives at `gimple_gen_funcs.py:358`; Mechanism
2's `ctype in ('int64_t', '_Bool')` guard at `gimple_gen_resolve.py:857`;
Mechanism 3's derived-to-base `self` materializing cast at
`gimple_gen_methods.py:440-441`; Mechanism 4's PascalCase-import guard at
`gimple_gen_exprs.py:891`. Mechanism 1's own minimal repro
(`Foo.bar` with a function-scoped `from _colorize import can_colorize`)
builds via `fire.py build` with **zero** `invalid conversion in gimple
call` errors. The previously documented remainders are unchanged:
Mechanism 4's `Parameter(...)` constructor-call shape stays open for the
documented cross-module resolution-ordering risk reasons, and the
weakref.py line-attribution / argparse kwargs / dynamic-% items stay
out of scope as recorded below.

## Re-verified 2026-08-09 (fresh pass, no code change)

Confirmed all four fixes below are present and committed on `master`
(`ret = sig[0] if sig else 'int64_t'` at gimple_codegen.py:20264,
`ctype in ('int64_t', '_Bool')` at :5426, `fake_obj_type = f"{base_name}
*"` derived-to-base cast at :11086, and the PascalCase-import
`_lower_MemberExpr` guard at :8994-9001 — `git blame` shows these landed
in the commits this doc already describes; nothing since has touched
them). Re-ran `python3 fire.py build
/Users/mrs/net/Python-3.14.6/Lib/subprocess.py`: 0 occurrences of
`non-trivial conversion in 'integer_cst'` (Mechanism 2/3's target,
still fully gone) and only 2 residual `invalid conversion in gimple
call` (both now `Lib/enum.py:918`/`:1918`-attributed, unrelated to the
original `can_colorize`/`Signature`/`Parameter`/`unpack` cluster
Mechanism 1 fixed — not a regression of this doc's territory). The
still-not-fixed Mechanism 4 residual (`Parameter(...)` constructor-call
shape) is still present (8 `expected expression before 'Parameter'`
occurrences now vs. 7 previously — same unfixed shape, magnitude
consistent with corpus drift from unrelated fixes elsewhere, not a
regression). Total error count for the full `subprocess.py` build has
moved (720 → 486) purely from OTHER, unrelated fixes landing in the
intervening two days (execv/execve arg-type errors, `mojo_list_contains_str`
pointer-type errors, argparse `_parse_known_args` errors — none in this
doc's scope). No new work done; this doc's remaining "Not fixed" items
(weakref.py line-attribution, argparse `**kwargs`, dynamic `%`-format,
Mechanism 4's constructor-call gap) are unchanged and still genuinely
structural/deferred for the reasons already documented below — left
as-is per this session's "hard bugs" conservatism guidance.

## Status (Mechanism 4 added 2026-08-07, Track B session — partial fix; Mechanisms 1-3 fixed 2026-08-07, Track B cross-cutting COMPILE_FAIL sweep)

Follow-up to `bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_
defined.md`'s "Follow-up fix" section: once that doc's `os.py`
`'relpath' is ambiguous` fix landed, `python3 fire.py build
/Users/mrs/net/Python-3.14.6/Lib/subprocess.py` stopped failing on that
issue and exposed a different, much larger cluster of real GIMPLE type
errors dominated by `Lib/argparse.py`, `Lib/typing.py`, `Lib/enum.py`,
and `Lib/gettext.py`. This doc covers the investigation of that cluster
and the four genuinely tractable, independent root causes found and
fixed in it (a fifth, `Lib/weakref.py`'s line-attribution mystery, was
investigated but NOT fixed — see "Investigated, not fixed" below).

Mechanism 4 (this update) is exactly the "Not fixed" item from this
doc's own previous revision — the `Signature`/`Parameter`-as-bare-C-
identifier bug found via `enum.py`'s `EnumType.__signature__`, which
that revision explicitly left "not located precisely enough to propose
a fix." It's now root-caused and PARTIALLY fixed — see its own section
below for what's covered and what still isn't.

All four fixes are in `gimple_codegen.py` only. Verified via the full
5-part quality gate (below) — 0 regressions.

## Symptom (baseline, before this session's fixes)

`python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/subprocess.py
2>&1 | grep 'error:' | sort | uniq -c | sort -rn` — 785 total `error:`
lines, dominated by:

```
  15 Lib/argparse.py:211:1: error: invalid conversion in gimple call
  12 Lib/typing.py:1491:1: error: non-trivial conversion in 'integer_cst'
  11 Lib/typing.py:1300:36: error: passing argument 1 of 'typing__is_dunder_...' makes integer from pointer without a cast
  10 Lib/typing.py:1275:1: error: non-trivial conversion in 'integer_cst'
  10 Lib/enum.py:1099:1: error: invalid conversion in gimple call
   6 Lib/argparse.py:1493:9: error: request for member '_kw_default' in something not a structure or union
   5 Lib/gettext.py:445:1: error: invalid conversion in gimple call
   5 Lib/argparse.py:677:1: error: invalid types for 'trunc_mod_expr'
   5 Lib/argparse.py:662:1: error: type mismatch in binary expression / non-trivial conversion in 'integer_cst'
   5 Lib/argparse.py:587:8: error: assignment to 'int64_t' from 'MojoBoundMethod *' makes integer from pointer without a cast
   5 Lib/argparse.py:522:14 / 329:16: error: invalid operands to binary % (have 'int64_t' and 'MojoDict *')
   5 Lib/argparse.py:478:10: error: assignment to 'char *' from 'char' makes pointer from integer without a cast
   4 Lib/argparse.py:1537:33: error: unexpected RHS for assignment before ';' token
   3 Lib/typing.py:1651:48 / 1300:46 / 1300:39: error: passing argument 1 of ... from incompatible pointer type
   1 Lib/weakref.py:6xx-8xx: error: expected declaration specifiers or '...' before 'Parameter'/'Signature' (35 occurrences total)
```

After the three fixes below: **720** total `error:` lines (-65). The
`can_colorize`/`Signature`/`Parameter`/`unpack`-triggered "invalid
conversion in gimple call" cluster (argparse.py ×15, enum.py ×10,
gettext.py ×5 = 30) and ALL of typing.py's `_Bool`/`int` `integer_cst`
errors (22) and `super()`-call pointer-type errors (12, cross-verified
on an isolated `typing.py`-only compile: 14 errors -> 2) are gone.
`Lib/subprocess.py` still does not fully build — the remaining cluster
(argparse.py's `**kwargs` dict-subscript/closure-as-value/dynamic-%-
format errors, weakref.py's mystery, two small unrelated typing.py
errors) is either already covered by an explicitly-excluded bug area or
was investigated and found not tractable in this pass — see "Not fixed"
below.

## Mechanism 1 (fixed): function-scoped `from mod import Name` defaults an unknown symbol's return type to `'int'`, disagreeing with every OTHER unknown-callee default in this file (`'int64_t'`)

### Root cause

`gimple_codegen.py`'s `_gen_stmt_FromImportStmt` (~line 18872) handles a
**function-scoped** `from module import name1, name2` (e.g. `from
inspect import Parameter, Signature` inside `enum.EnumType.
__signature__`, `from _colorize import can_colorize` inside
`argparse.HelpFormatter._set_color`, `from struct import unpack` inside
`gettext.GNUTranslations._parse`) — a common Python idiom for lazy/
optional imports. For a symbol with no `_KNOWN_SIGS` entry (i.e. not a
handful of hardcoded runtime helpers), it registered:

```python
sig = self._KNOWN_SIGS.get(symbol_name)
ret = sig[0] if sig else 'int'          # <-- WRONG default
self.func_return_types[symbol_name] = ret   # (if not already present)
```

Every OTHER unknown-callee fallback in this file uses `'int64_t'` (e.g.
`self.func_return_types.get(fname, 'int64_t')`, used at ~15 call sites
across the file), and — critically — the "unavailable in compiled mode"
weak-stub generator this codegen emits for any never-linked symbol ALSO
declares its return type `int64_t` unconditionally. `_gen_stmt_
FromImportStmt`'s `'int'` default was the ONLY thing in the whole
pipeline disagreeing with that convention.

Because a call site's own SSA temp is pre-declared with a DIFFERENT
type than what `func_return_types` says at the moment the call itself
is lowered (the temp-declaration prescan runs largely independently of
per-statement lowering order), the mismatch surfaces as a real GIMPLE
"invalid conversion in gimple call" — GCC's own `-fgimple` mode does
NOT apply the ordinary C implicit-conversion rules real C compilation
would (confirmed directly: `int64_t x; x = 0;` compiles fine under
plain `-fgimple -fsyntax-only`, but a function `int64_t T (...)`
assigned into an `int`-declared temp, or vice versa, does not).

### Minimal repro

```python
class Foo:
    def bar(self):
        from _colorize import can_colorize
        if can_colorize():
            return 1
        return 0
```
`python3 fire.py build` on this (any `.py` file) fails:
```
error: invalid conversion in gimple call
int

int64_t

_t1 = can_colorize ();
```
Confirmed directly in the generated `.ci`:
```c
#ifndef can_colorize
__attribute__((weak)) int64_t can_colorize (...) { ...; return (int64_t)0; }
#endif
  int _t1;              /* WRONG: declared from func_return_types['can_colorize']='int' */
  _t1 = can_colorize (); /* stub returns int64_t -- mismatch */
```

### Fix

`gimple_codegen.py`, `_gen_stmt_FromImportStmt`: changed the fallback
from `'int'` to `'int64_t'` — `ret = sig[0] if sig else 'int64_t'`.

### Verification

- Repro above: "invalid conversion in gimple call" gone (compile now
  reaches the link stage; the synthetic repro's own link failure —
  `_can_colorize` undefined — is a SEPARATE, pre-existing artifact of a
  trivial standalone single-file build never actually linking a real
  `_colorize` implementation, not something this fix touches or causes;
  confirmed by reproducing the SAME link failure against the ORIGINAL,
  unfixed code once the (unrelated, blocking) compile-stage error is
  independently patched out for the check).
- `Lib/subprocess.py` full build: the `can_colorize`/`Signature`/
  `Parameter`/`unpack` "invalid conversion in gimple call" errors (30
  occurrences across argparse.py/enum.py/gettext.py) are gone, 0 new
  error categories introduced (785 -> 755 total errors).

## Mechanism 2 (fixed): `_new_val`'s digit-literal auto-cast guard only covered `int64_t`, not `_Bool`

### Root cause

`gimple_codegen.py`'s `_new_val(ctype, rhs)` helper (~line 5027) already
had a guard for the well-known "-fgimple requires an integer_cst's type
to exactly match its assignment target" gap — but only for `int64_t`:

```python
if ctype == 'int64_t' and rhs.lstrip('-').isdigit():
    self._emit(f'  {t} = (int64_t){rhs};')
else:
    self._emit(f'  {t} = {rhs};')
```

Two call sites pass `ctype='_Bool'` with a bare digit `rhs` —
`_isinstance_one_type`'s `isinstance(x, type)`-always-False stub
(`return self._new_val('_Bool', '0')`) and the `isinstance(x, (A, B,
...))` tuple-of-types OR-accumulator's seed value (same call, ~line
13905) — and neither got the cast, producing the identical class of
GIMPLE error `_new_val`'s own `int64_t` branch was written to prevent,
just for `_Bool` instead: `non-trivial conversion in 'integer_cst'`.

Real-world trigger: `typing.py`'s `_BaseGenericAlias.__mro_entries__`
(`if not isinstance(b, type): ...`) and `_GenericAlias._make_
substitution` both call `isinstance(x, type)`, hitting the always-False
stub twice each (once per code path through the function) — 22
occurrences total in a `Lib/subprocess.py` build.

### Fix

Generalized the guard to cover both types that need it:
```python
if ctype in ('int64_t', '_Bool') and rhs.lstrip('-').isdigit():
    self._emit(f'  {t} = ({ctype}){rhs};')
```
(Audited every other `_new_val(ctype, digit_literal)` call site in the
file — all the rest already use `ctype='int'`, which matches a bare
digit literal's own C type trivially, so no further cases needed the
guard.)

### Verification

Isolated `Lib/typing.py`-only compile (`compile_to_gimple(src,
do_imports=False)` + `gcc-mp-15 -fgimple -fsyntax-only`, faster
iteration than a full `subprocess.py` build): 36 errors before this fix
and Mechanism 3's fix combined -> 14 after Mechanism 2 alone (all 22
`_Bool`/`int` `non-trivial conversion in 'integer_cst'` errors gone,
confirmed by category, not just count) -> 2 after Mechanism 3 (below)
is added on top.

## Mechanism 3 (fixed): `super().method(...)` passes `self` typed as the DERIVED struct pointer while claiming (for lookup purposes only) it's the BASE struct pointer — `_emit_call`'s arg-coercion pass trusts the claim and never emits the actual cast

### Root cause

`gimple_codegen.py`'s `super().method(args)` lowering (~line 10305,
inside the general method-call dispatcher) resolves the call directly
to the base struct's own compiled method:

```python
self_type, self_val = self.lower_expr(IdentExpr(name='self', ...))
fake_obj_type = f"{base_name} *"
return self._lower_struct_method_call(self_val, fake_obj_type, func.member, node)
```

`self_val` is the C identifier `self` — its REAL declared C type is the
CURRENT (derived) struct, e.g. `_LiteralGenericAlias *`. `fake_obj_type`
is used purely so `_lower_struct_method_call`'s method-name/return-type
RESOLUTION machinery treats the call as if `self` were already the base
type — but the label was never backed by an actual C-level cast.

`_lower_struct_method_call` passes `(fake_obj_type, self_val)` as the
call's first `(ctype, value)` arg pair straight through to `_emit_call`,
whose arg-coercion loop (~line 5668) only emits a cast when the
CALLER's claimed type and the CALLEE's declared param type visibly
DIFFER (`ptype == atype` -> skip coercion). Since both were the SAME
string (`fake_obj_type` == the base method's own declared first-param
type, `{base_name} *`), the coercion pass saw "no mismatch" and passed
`self` completely unchanged — producing a real C pointer-type mismatch
GCC correctly flags: `passing argument 1 of '..._method' from
incompatible pointer type`.

Hits EVERY multi-level struct-inheritance chain with more than one
`super().method(...)` call across levels — confirmed in `typing.py`'s
`_LiteralGenericAlias -> _GenericAlias -> _BaseGenericAlias` and
`_CallableType`/`_TupleType`/`_DeprecatedGenericAlias -> 
_SpecialGenericAlias` chains (`__dir__`, `__mro_entries__`, `copy_with`
— 12 occurrences in the `subprocess.py` build; 8 distinct call sites,
isolated `typing.py`-only count).

### Fix

Materialize the cast instead of merely asserting it via the type label:
```python
self_type, self_val = self.lower_expr(IdentExpr(name='self', ...))
fake_obj_type = f"{base_name} *"
if self_type != fake_obj_type:
    self_val = self._new_val(fake_obj_type, f"({fake_obj_type}){self_val}")
return self._lower_struct_method_call(self_val, fake_obj_type, func.member, node)
```
A derived-to-base struct pointer cast is always valid C (the same
struct-pointer-cast convention every other method-dispatch site in this
file already relies on for its own `(StructName *)obj_val` casts).

### Verification

Isolated `Lib/typing.py`-only compile: 14 errors (after Mechanism 2's
fix alone) -> **2** (only two small, unrelated, NOT-investigated errors
remain — see "Not fixed" below). Full `Lib/subprocess.py` build: 755 ->
**720** total errors (with Mechanism 2 landed in the same commit; the
two fixes were verified together in the full-build count and
individually in the isolated `typing.py`-only count above).

## Mechanism 4 (root-caused and PARTIALLY fixed, 2026-08-07): an imported class name used as a bare `X.ATTR` member-access base gets mistaken for a zero-arg accessor function, colliding with the class's own later-registered `typedef`

### Symptom

`python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/typing.py`
(pulls in `enum.py` transitively) — repeated, identical-looking errors:

```
/Users/mrs/net/Python-3.14.6/Lib/enum.py:1095:10: error: expected expression before 'Parameter'
 1095 |             return Signature([Parameter('new_class_name', Parameter.POSITIONAL_ONLY),
```
(14 occurrences before this fix, all reported at the exact same
source line/column — GCC's `#line`-directive diagnostics collapse
multiple DIFFERENT generated call sites down to one reported location
whenever they all trace back to the same Python source statement, so
"14 identical-looking errors" was actually several distinct generated
C call sites, not one error printed 14 times — confirmed by stripping
every `#line` directive from the `.ci` before recompiling, which
recovers the real, distinct physical line numbers GCC's own diagnostic
was masking.)

This is `enum.py`'s `EnumType.__signature__` property:
```python
    @property
    def __signature__(cls):
        from inspect import Parameter, Signature
        if cls._member_names_:
            return Signature([Parameter('values', Parameter.VAR_POSITIONAL)])
        else:
            return Signature([Parameter('new_class_name', Parameter.POSITIONAL_ONLY), ...])
```
— a FUNCTION-SCOPED `from inspect import Parameter, Signature`, then
`Parameter.VAR_POSITIONAL`-style class-attribute reads on the imported
name.

### Root cause

Confirmed directly in the `.ci` (with `#line` directives stripped so
GCC's reported line numbers are the real physical ones): `Parameter` is
BOTH a real `typedef struct Parameter {...} Parameter;` (the genuine
`inspect.Parameter` class, correctly discovered and inlined SOMEWHERE
else in this same transitive-closure translation unit — its
`_alloc_Parameter`/`_mojo_repr_Parameter`/`_mojo_getattr_Parameter`/
`_mojo_setattr_Parameter` all exist) AND the target of a colliding
`__attribute__((weak)) int64_t Parameter (...) { ...; }  /* stub from
inspect */` — a bare-name "unresolved import" stub function. In C, a
typedef name and a function/value identifier can't share one namespace
scope this way — any expression trying to CALL `Parameter` (`Parameter
()`, `Parameter (_t7, _t10)`) hits `error: expected expression before
'Parameter'`, because the parser sees `Parameter` as a type name where
an expression was expected.

The half of this that's now fixed: `_lower_MemberExpr`'s handling of
`X.ATTR` bare-name attribute access (`gimple_codegen.py`, ~line 8598)
already has a correct path for `X` being a KNOWN struct
(`module_name in self.struct_field_types`) — it stubs the unresolved
class-attribute read as `t = 0; /* class attr X.ATTR — UNRESOLVED */`.
But when `X` (here `Parameter`) is not YET in `self.struct_field_types`
at the moment THIS particular member-access is lowered (an ordering
race: `enum.py`'s `__signature__` body can be lowered before
`inspect.py`'s `Parameter` class definition has been processed
elsewhere in the transitive closure — `self.struct_field_types` is a
single dict shared by reference across every module's `temp_gen`, so
WHETHER a name is in it depends purely on processing order, not on
whether the class exists at all), the code falls through to a
DIFFERENT, older fallback a few lines down: "if the object is a
zero-arg function used in member-access context (e.g. `block_idx.x`),
call it first so we get the struct return value, not a void* funcptr."
That fallback's guard (`node.obj.name in self.func_return_types and
... not in self.struct_field_types`) is satisfied for `Parameter` too
(the generic "unresolved import" registration path treats every
imported name as a potential callable, adding it to
`func_return_types` regardless of whether it's actually a class) — so
it emits `Parameter ()` (an actual call) instead of the safe `0` stub,
producing the `typedef`-vs-function-identifier collision above.

### Fix (partial — see "Not fixed" below for what this doesn't cover)

`gimple_codegen.py`, `_lower_MemberExpr` (~line 8598): added a new
branch, checked BEFORE the `block_idx.x`-style zero-arg-function
fallback, that catches this exact shape — `module_name` is registered
as an import (`in self.imported_symbols`), not a known var or struct,
not a `BUILTIN_VALUE_MAP` entry, AND starts with an uppercase letter
(a PascalCase identifier, per Python's own class-naming convention —
deliberately narrow so it can't affect the `block_idx`/`thread_idx`/
`grid_dim` real accessor-function cases the zero-arg fallback exists
for, which are always lowercase). When it matches, emit the SAME
"class attr ... UNRESOLVED" `0`-stub the already-known-struct case
uses, instead of falling into the zero-arg-call fallback.

This is a narrow, MemberExpr-only fix — it does **not** address calls
to the constructor itself (`Parameter('values', Parameter.VAR_POSITIONAL)`
— the `Parameter(...)` CALL, as opposed to the `Parameter.ATTR` member
read) hitting the exact same `typedef`-vs-identifier collision through
a completely different code path (`_lower_named_call`'s own
"unresolved import" stub-emission, unrelated to `_lower_MemberExpr`).
Root-causing that side traced as far as confirming it's the SAME kind
of ordering race (the STRUCT eventually gets registered, just not
before the call in question is lowered) but fixing it safely would
require either reordering when class definitions get registered across
the whole transitive closure (high blast radius — this project's OWN
`bugs/hard/CODEGEN_function_scoped_import_call_unresolved_at_link.md`
documents a full session where an analogous cross-module resolution-
ordering fix passed the ENTIRE 5-part quality gate clean and STILL had
to be reverted after a corpus-wide regression only visible via manual
re-triage of the `COMPILE_FAIL_*.md` corpus) or deferring the "is this
name secretly a class" decision to the very end of the whole-program
compile (a genuine architectural change, not a bug-fix-sized one).
Left alone given that documented risk and this session's time budget.

### Verification

`typing.py` isolated build (pulls in `enum.py` transitively):
`enum.py:1095:10: error: expected expression before 'Parameter'`
occurrences: **14 -> 7** (the 7 remaining are all the unfixed
`Parameter(...)`-constructor-call shape described above, confirmed via
the same `#line`-stripped-recompile technique). Total `error:` count
for this same build: 687 before and after (other clusters unaffected,
consistent with 7 of the original 14 lines simply being replaced by 7
DIFFERENT still-real errors from the constructor-call shape, not a net
new error). `Lib/csv.py` (a different, independently-chosen transitive
closure that also reaches `enum.py`): baseline 703 `error:` lines ->
**695** with this fix (-8, consistent with the same partial win).

Spot-checked 3 unrelated files for regressions (`Lib/json/__init__.py`,
`Lib/csv.py`, `Lib/heapq.py`): all build with the same or fewer errors
as baseline (`json/__init__.py` and `heapq.py` both build clean, 0
errors, both before and after).

## Not fixed / investigated only

- **`Lib/weakref.py`'s 35-error cluster** (`expected declaration
  specifiers or '...' before 'Parameter'/'Signature'`, plus a handful
  of `unexpected RHS for assignment`/`implicit declaration of function
  'deepcopy'` errors, plus 3 `'inspect_Signature_...' undeclared here`
  errors): partially root-caused but NOT fixed. Two separate findings:
  1. The `#line` directives attributing this text to `weakref.py` are
     WRONG — `weakref.py` is genuinely only 574 lines, but errors are
     reported at lines up to ~962. Direct comparison against
     `Lib/_collections_abc.py` confirms the ACTUAL source: lines 819-822
     of `_collections_abc.py` (`Mapping.__eq__`/`.items()`, inherited by
     `WeakValueDictionary(_collections_abc.MutableMapping)`) match
     line-for-line and statement-for-statement with the C emitted under
     the WRONG `#line ... "weakref.py"` tag at .ci line ~307183. This
     looks like an inherited-method "flattening" mechanism (copying a
     mixin base class's method body into the subclass's own compiled
     unit) that updates the `#line` NUMBER per source line but never
     re-points the `#line` FILENAME to the mixin's own file
     (`_collections_abc.py`) when it switches into that source. This
     part is purely a diagnostics/line-attribution bug — the C logic
     itself, inspected directly, looked semantically correct for
     `Mapping.__eq__`.
  2. The literal `Parameter`/`Signature` identifiers appearing directly
     in what looks like a C declaration/parameter list (`expected
     declaration specifiers or '...' before 'Parameter'`) — **UPDATE
     2026-08-07: root-caused and partially fixed, see "Mechanism 4"
     below.** This weakref.py instance specifically was not re-verified
     against the Mechanism 4 fix (weakref.py's OWN build still has its
     own separate `#line`-attribution issue from finding 1 above, and
     the `deepcopy`/`unexpected RHS` errors are unrelated), but the
     underlying `Parameter`/`Signature`-as-bare-C-identifier mechanism
     is the same one Mechanism 4 fixes at its `enum.py` occurrence — see
     that section for what's covered and what still isn't.
     Originally: traced as far as ruling out
     `module_loader.py`'s `.mojo`-source text-scan path (`_mojo_type_to_
     c` there delegates to `gimple_codegen._mojo_type`, whose documented
     unknown-type fallback is `int64_t`, not the bare literal name; also
     that path only applies to `.mojo` files, not `.py` sources like
     `inspect.py`/`weakref.py`). The actual site is presumably in
     `gimple_codegen.py`'s own parameter/return-type-annotation
     resolution for a type name that's a locally-imported class
     (`Parameter`/`Signature` from `from inspect import Parameter,
     Signature`) rather than a primitive — not located precisely enough
     to propose a fix without further investigation. Flagged as a
     follow-up; NOT attempted given the remaining time budget in this
     session and the CLAUDE.md-documented history of narrowly-scoped
     changes to this exact class of shared machinery causing
     regressions.
- **`Lib/argparse.py`'s `**kwargs` dict-subscript errors** (`request for
  member '_kw_default' in something not a structure or union`, line
  1493: `action.default = kwargs[action.dest]` inside `def
  set_defaults(self, **kwargs)`) — this is the EXPLICITLY excluded
  `bugs/hard/CODEGEN_args_kwargs_signature_assumed_forwarding_only.md`
  (task #142) bug area per this session's assignment; not touched.
- **`Lib/argparse.py`'s dynamic (non-literal) `%`-format-string errors**
  (`invalid operands to binary % (have int64_t and MojoDict *)` at
  lines 329/522 — `usage % {"prog": ...}`, `text % dict(prog=...)`;
  `invalid types for 'trunc_mod_expr'` at 662/677/1329 — `' '.join(...)
  % get_metavar(...)`): traced to `gimple_codegen.py`'s `_lower_percent`
  (~line 9650), whose own docstring already documents this as a
  DELIBERATE scope limit: "Only a *literal* format string on the LHS is
  handled specially here... Anything else — including a `char *`
  variable holding a dynamic template — falls through to the ordinary
  numeric-modulo path below (pre-existing behavior, not made worse)."
  Extending this to non-literal LHS values requires a genuine RUNTIME
  `%`-format engine (parsing `%s`/`%d`/`%(name)s`/etc. directives out of
  a template string not known until runtime, materializing a
  `mojo_str_percent_format(fmt, args)`-shaped runtime helper) — a real
  feature, not a bug-fix-sized change, and already flagged by the
  existing docstring as affecting "~130 real stdlib files". Left alone
  per this doc's own prior scoping decision; not re-litigated here.
- **Two small, unrelated `Lib/typing.py` errors** (isolated-compile
  count 2, both untouched by the three fixes above): `error: non-
  register as LHS of unary operation` at a global-struct-field
  assignment (`_root_globals._lazy_annotationlib = (struct
  _LazyAnnotationLib *) _t2;`), and `error: '_TypedDictMeta' has no
  member named '__orig_bases__'` (`td.__orig_bases__ = (TypedDict,)`
  inside `TypedDict`'s `__new__`-ish construction). Neither investigated
  beyond locating them — out of scope for this pass.

## Quality gate (2026-08-07, all three fixes together)

1. `python3 test_gimple.py` — 247 passed, 0 failed (unchanged from
   baseline).
2. `python3 test_module_cache.py` — 76 passed, 0 failed (unchanged).
3. `make check-selfhost` — clean (`Results: 1 passed, 0 failed`, "✓
   self-host compiles + links clean").
4. From-scratch stdlib dylib rebuild (`rm -f build/libmojostdlib.dylib`
   + `build_stdlib_dylib.build_stdlib(jobs=8)`) — clean, 0 `skip
   <module>:` lines.
5. `python3 compile_stdlib.py -j8` — **664/664 passed, 0 unexpected
   failures** (unchanged from baseline — no regression from any of the
   three fixes).

## Quality gate (2026-08-07, Mechanism 4 fix, separate session)

1. `python3 test_gimple.py` — 247 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed.
3. `make check-selfhost` — clean (`Results: 1 passed, 0 failed`, "✓
   self-host compiles + links clean").
4. From-scratch stdlib dylib rebuild (`rm -f build/libmojostdlib.dylib`
   + `build_stdlib_dylib.build_stdlib(jobs=8)`) — clean, 0 `skip
   <module>:` lines.
5. `python3 compile_stdlib.py -j8` — **664/664 passed, 0 unexpected
   failures**.
6. Cross-cutting spot-check (this fix touches `_lower_MemberExpr`, a
   shared/broad lowering path): `Lib/json/__init__.py` and
   `Lib/heapq.py` both build 0-error clean, unchanged. `Lib/csv.py`
   went from 703 to 695 `error:` lines (improvement, not a regression —
   it transitively reaches the same `enum.py` code path).
