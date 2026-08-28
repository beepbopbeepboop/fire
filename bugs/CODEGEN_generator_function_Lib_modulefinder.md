# CODEGEN_generator_function: Lib/modulefinder.py

## Status (updated 2026-08-26, fresh independent re-derivation — confirmed unchanged, not just re-trusting the prior entry)

Re-derived from scratch (fresh `compile_to_gimple_with_cpp(do_imports=False)`
call, not the prior script): identical verbatim refusal — `scan_opcodes:
every 'yield' must carry a value, and all values must agree on one scalar
type`. Re-read the 3-stacked-gap analysis against the current source
(variable-arity nested-tuple element boxing across the 3 `yield "tag", (...)`
sites; `scanner = self.scan_opcodes` local-variable aliasing before
`_cpp_for_generator_delegate` ever sees the call; tag-discriminated
variable-arity unpack at the 3 consumer sites in `scan_code`) — confirms it
independently: none of the three gaps is touched by this session's other
work (a `cls.method(...)` return-type-inference fix made for
`Lib_tarfile.md`, unrelated to tuple-yield/aliasing machinery). Genuinely 3
independent, non-trivial extensions to already-complex shared machinery;
not attempted, consistent with every prior pass. Doc stays open.

## Status (updated 2026-08-26, worktree agent-ae936147a68675d97 — independently re-derived from scratch, byte-identical)

Re-derived fresh via own isolated `compile_to_gimple_with_cpp(do_imports=
False)` call (not a re-read of this doc): identical `RuntimeError` —
`scan_opcodes: every 'yield' must carry a value, and all values must
agree on one scalar type`. Concur with the existing 3-stacked-gap
analysis (variable-arity nested-tuple element boxing; consumer-through-
local-variable aliasing `scanner = self.scan_opcodes`; tag-discriminated
variable unpack arity) — each independently non-trivial, high regression
risk to already-fixed sibling tuple-yield files if rushed together. No
code change made. Doc stays open.

## Status (updated 2026-08-26, worktree fix/rest-remainder19d — checked against today's super()/self.__class__ fix (bdfb825) and generator-value-return-slot fix (326db78); neither applies)

Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)` repro:
byte-identical verbatim refusal — `scan_opcodes: every 'yield' must
carry a value, and all values must agree on one scalar type`. Neither of
today's two landed fixes is relevant to any of the 3 stacked gaps this
doc documents (variable-arity nested-tuple element boxing; consumer-
through-local-variable aliasing `scanner = self.scan_opcodes`; tag-
discriminated variable unpack arity) — none involve `super()`,
`self.__class__`, or a generator's own value-carrying `return`. No code
change; doc stays open.

## Status (updated 2026-08-26, worktree fix/rest-remainder17 — re-verified unchanged)

Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)` re-run
against this worktree (branched from master `1e0f3f2`): identical
verbatim refusal — `scan_opcodes: every 'yield' must carry a value, and
all values must agree on one scalar type`. None of this session's other
fixes (dynamic exception-value re-raise via `SubscriptExpr`, see
`CODEGEN_generator_function_Lib_test_test_finalization.md`) touch tuple-
yield arity/aliasing machinery. The 3-stacked-gap analysis (variable-
arity nested-tuple element boxing; consumer-through-local-variable
aliasing `scanner = self.scan_opcodes`; tag-discriminated variable
unpack arity) stands unchanged. Not attempted (same reasoning as every
prior pass). No change; doc stays open.

## Status (updated 2026-08-25, worktree fix/rest-remainder14 — re-verified unchanged)

Fresh re-verify against this worktree (branched from master `f65502d`).
`compile_to_gimple_with_cpp(..., do_imports=False)` on the real file
still raises the identical refusal verbatim: `scan_opcodes: every
'yield' must carry a value, and all values must agree on one scalar
type`. The well-documented 3-stacked-gap analysis (variable-arity
nested-tuple element boxing; consumer-through-local-variable aliasing
`scanner = self.scan_opcodes`; tag-discriminated variable unpack arity)
still applies exactly as described — none of it is touched by anything
landed since the last pass. Not attempted (same reasoning as every
prior pass: three independently non-trivial extensions to shared
tuple-yield/consumption machinery, high regression risk to already-
fixed sibling files). No change; doc stays open.

## Status (updated 2026-08-25, worktree fix/rest-remainder11 — re-verified unchanged)

Re-verified fresh against this worktree. `scan_opcodes` still refuses
with "every `yield` must carry a value, and all values must agree on one
scalar type" — the 3-stacked-gap analysis from 2026-08-11 stands
(nested-tuple element boxing with variable inner arity; consumer-through-
local-variable aliasing; tag-discriminated variable unpack arity). None
of the recently landed shared mechanisms touch any of the three. Not
attempted (deliberately out of narrow-fix scope, same conclusion as
every prior pass). Doc stays open.

## Status (updated 2026-08-24 — re-verified unchanged)

Fresh isolated compile (`GimpleGen(do_imports=False, relaxed_imports=
True)`): identical refusal — `scan_opcodes`: "every `yield` must carry a
value, and all values must agree on one scalar type" — the variable-
arity nested-tuple-yield shape this doc already documents (different
`yield` sites in the same generator produce tuples of DIFFERENT arity,
which the fixed-shape tuple-yield machinery elsewhere in this codegen
can't represent as one promise type). No change; doc stays open.


## Status (updated 2026-08-23 — re-verified; scan_opcodes refusal unchanged, 3-gap analysis stands)

Isolated compile reproduces the identical honest refusal for `scan_opcodes`.
This session's three generic generator-codegen fixes (enumerate-over-
generator delegation; struct-method default-arg padding; list/dict/set
literal locals + append in coroutine bodies) deliberately do NOT touch any
of the three stacked gaps the 2026-08-11 entry documented: nested-tuple
element boxing with VARIABLE inner arity, consumer-through-local-variable
(`scanner = self.scan_opcodes`), and tag-discriminated unpack arity. The
literal-local fix is worth noting as ADJACENT progress — it removes the
"no list accumulator representation at all" obstacle for OTHER generators —
but scan_opcodes' dynamic-shape yields remain genuinely unrepresentable in
the fixed-arity promise-slot model. Documented-not-fixed stands; doc kept
open.


## Status (updated 2026-08-11 — re-verified still refused; deepened root-cause to 3 independent, stacked gaps, real fix attempt not made — genuinely out of narrow-fix scope)

Re-verified against current master: `python3 mojo.py build
/Users/mrs/net/Python-3.14.6/Lib/modulefinder.py` still fails with the
identical `RuntimeError: cannot compile module: function(s)
scan_opcodes ...` before any C is emitted — unchanged from 2026-08-10.

Went deeper than the previous session's assessment to see whether a
real, bounded fix was possible (not just re-confirming the refusal).
Found this is actually **3 independent, stacked gaps**, not one — a
real fix would need all three, and each is itself non-trivial:

1. **Nested-tuple element boxing.** `scan_opcodes`'s 3 yield sites are
   `yield "store", (name,)` / `yield "absolute_import", (fromlist,
   name)` / `yield "relative_import", (level, fromlist, name)` — the
   OUTER tuple is always 2 elements (agrees with
   `_generator_tuple_yield_slot_ctypes`'s fixed-arity-per-slot model),
   but slot 1 is itself a nested `TupleExpr` whose OWN arity varies
   (1, 2, then 3 elements) depending on which site fired. The existing
   `_cpp_yield_tuple`/`_generator_tuple_yield_slot_ctypes` model assigns
   ONE C++ scalar type per top-level slot, unified across every yield
   site in the function — there is no representation at all for "this
   slot is itself a variable-arity nested tuple," which is a
   structurally different (dynamically-shaped, not fixed-shape) case.
   A real fix would need slot 1 to box recursively into its own
   `MojoList *` (storing the boxed pointer as `int64_t` the same way
   this codebase already boxes other pointer-typed values into int64_t
   containers) and mark that slot's ctype as `'MojoList *'` instead of
   a scalar — a genuinely new code path, not a parameter tweak.
2. **The consumer never calls the generator directly.**
   `scan_code`'s consuming loop is:
   ```python
   scanner = self.scan_opcodes
   for what, args in scanner(co):
   ```
   `_cpp_for_generator_delegate` (the coroutine-body consumer for
   `for <target> in <call>:`) only recognizes `self.<method>(...)`
   (checked via `isinstance(call.func, MemberExpr)` +
   `call.func.obj is IdentExpr('self')`) or a free-function
   self-recursive call by name — a call through a local variable
   (`scanner`) that was bound to a bound-method value earlier in the
   same function is neither shape, so this loop would raise
   `_UnsupportedGeneratorShape` regardless of whether gap #1 above is
   fixed. This is the SAME "closure/bound-method-as-value" class of gap
   as other already-fixed bugs this session, but applied specifically
   to a GENERATOR consumption site, which `_cpp_for_generator_delegate`
   has no alias-resolution for at all.
3. **The consumer destructures with tag-dependent, non-fixed arity.**
   Even with #1 and #2 solved, `scan_code`'s body does
   `name, = args` / `fromlist, name = args` / `level, fromlist, name =
   args` in different branches keyed on the `what` tag string — i.e.
   the nested tuple's real shape is a discriminated union (arity/typing
   varies by which string tag accompanies it), not a single fixed
   N-tuple. No part of this codegen's tuple-yield/tuple-unpack model
   represents tag-discriminated variable-shape data; each unpack site
   would need to trust its own local arity assumption against a
   runtime `MojoList *` of unknown-at-compile-time length, which is a
   correctness question this codegen doesn't have an existing pattern
   for (every other tuple-unpack consumer assumes a single, statically
   agreed arity for the whole generator).

**Not attempted**: this is 3 stacked, independently non-trivial
extensions to already-complex, heavily-shared machinery
(`_cpp_yield_tuple`/`_generator_tuple_yield_slot_ctypes`/
`_cpp_for_generator_delegate`) that every other fixed tuple-yield bug
this session depends on for correctness (mailbox.py, ipaddress.py,
etc.) — a rushed combined fix risks regressing all of them. This is a
genuine, deep structural gap, not a narrow one; consistent with the
previous session's own "out of this fix's scope" conclusion, now with
the full 3-part breakdown documented so a future dedicated pass
doesn't have to re-derive it. Doc kept open.

## Status (updated 2026-08-10, later same session — re-verified the "struct _X_toplev" pattern task; unaffected, file still fails before GCC stage regardless)

Investigated this session's cross-cutting task tracing a recurring
`invalid use of undefined type 'struct _<modname>_toplev'` GCC error
across 9 bug docs, this file included (the 2026-08-06 entry below —
already noted GONE as of 2026-08-07, fixed by `bugs/hard/COMPILE_FAIL_
module_toplev_struct_never_fully_defined.md`'s mechanism-1/mechanism-2
fixes). Also found+fixed one closely related residual bug in the same
struct-family area this session (`_gen_struct_method`/`_gen_lifted_
closure` never setting `self._current_module_ctx`, a `global`-write
misrouting bug — see that hard-bug doc's history). No effect on THIS
file either way: `scan_opcodes`'s nested-tuple-yield refusal (below)
raises a Python-level `RuntimeError` in `gen_module` before any C code
is ever emitted, so the build never reaches GCC at all, with or
without either fix. No reclassification.

## Status (updated 2026-08-10 — general tuple-valued yield now FIXED; `scan_opcodes`'s specific NESTED-tuple shape remains a distinct, still-refused sub-case)

Implemented real tuple-valued-`yield` support this session (`yield a,
b, ...` boxes into a real `MojoList *` at the yield site — see
`gimple_codegen.py`'s `_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes`). `scan_opcodes` is STILL refused, correctly — its shape is a
DISTINCT, deeper sub-case this fix deliberately does not cover:

```python
yield "store", (name,)
yield "absolute_import", (fromlist, name)
yield "relative_import", (level, fromlist, name)
```

Each of these is a tuple whose SECOND element is ITSELF a nested tuple
literal (varying inner arity: 1, 2, then 2 elements). `_cpp_expr`
lowers a bare tuple/list/dict/set literal to a raw C++ braced-init-list
(`{name}`), which is not a valid argument to `mojo_list_append_int/
_double/_str` (nor castable to any of those types) — attempting to box
it anyway would reproduce this family's ORIGINAL malformed-C++ failure
mode one level deeper. This session's fix added an explicit guard for
exactly this (`_generator_yield_ctype`'s `TupleExpr` branch now refuses,
via `return None`, whenever any element of the tuple is itself a
`TupleExpr`/`ListExpr`/`DictExpr`/`SetExpr`) — confirmed via a direct
repro (`yield "store", ("name",)`) that this now produces the same
clean, honest Python-level refusal `scan_opcodes` already got, not a
GCC-stage syntax error.

Recursive/nested tuple-element boxing (and, separately, the outer
tuple's own arity varying if it did) is out of this fix's scope — see
the task's "yield tuples with a FIXED, small element count" scope
boundary. Doc kept open (not deleted) — `scan_opcodes` remains
refused, now for a more precisely diagnosed reason.

## Status (updated 2026-08-09 — RECLASSIFIED: `scan_opcodes`'s tuple-valued yield is now the blocking error)

Re-verified against current master (`5ba7d4b`) via a real
`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/modulefinder.py`.
The build now fails immediately, before reaching any GCC-stage error
(i.e. before the `_quick_type` fix documented just below even gets a
chance to matter), on a hard Python-level `RuntimeError` from
`gen_module` (`gimple_codegen.py:30968`):

```
Error building: cannot compile module: function(s) scan_opcodes
(generator function(s), contain a `yield`/`yield from`) — this codegen
compiles every function into a single straight-line C function and has
no suspend/resume state-machine transform for generators, ...
```

This is exactly the tuple-of-heterogeneous-arity-yield shape the
2026-08-06 section below already identified in `scan_opcodes` (lines
393-403: `yield "store", (name,)` / `yield "absolute_import", (fromlist,
name)` / `yield "relative_import", (level, fromlist, name)`) — confirmed
again by re-reading the source. This is the same well-known,
already-tracked structural gap as `ipaddress.py`'s `_find_address_range`
and `mailbox.py`'s `iteritems` (see those bug docs' 2026-08-09 updates):
coroutine promises only support a single scalar, and
`_infer_generator_yield_ctype`'s `TupleExpr` branch at
`gimple_codegen.py:2699-2724` now honestly refuses rather than
mis-emitting broken C++.

This supersedes the "ONE error remained" claim in the 2026-08-07 section
below: that section's testing was done when `scan_opcodes` was
apparently still eligible under a weaker tuple-yield check (or wasn't
yet reached before other passes ran), so the module compiled far enough
to hit the `find_all_submodules` `_quick_type` bug and the `self.msg`
`*args` bug at GCC stage. A later session's work (visible in current
`gimple_codegen.py`) tightened the tuple-yield eligibility check, so
`scan_opcodes` now correctly aborts the whole-module compile before
either of those two are reached.

**The `_quick_type` `.keys()`/`.values()`/`.items()` fix described below
is still landed and still correct** (verified present in current
`gimple_codegen.py`'s `_quick_type`, around the `CallExpr`-on-`MemberExpr`
branch) — it's just no longer the *blocking* error for a full-module
build of this file, since `scan_opcodes`'s tuple-yield refusal now fires
first. **Classification: matches the tracked "tuple-valued yield"
structural generator-codegen gap** — out of scope for a narrow fix per
this task's guidance. Not attempted here.

## Status (updated 2026-08-07 — `_quick_type` `.keys()`/`.values()`/`.items()` case FIXED)

Re-verified against current master: the `struct _subprocess_toplev`/
`struct _genericpath_toplev` errors quoted below are already gone
(fixed by `bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_
defined.md`'s "mechanism 2" landing since 2026-08-06). Only ONE error
remained: `modulefinder.py:296:1: error: invalid conversion in return
statement` — still well outside the generator (`scan_opcodes`, lines
393+), inside `find_all_submodules`:

```python
def find_all_submodules(self, m):
    if not m.__path__:
        return                      # bare return -> void/None
    modules = {}
    ...
    return modules.keys()           # MojoDict *.keys() -> MojoList * (real)
```

**Root cause: another `_quick_type` return-type-estimator gap, same
family as `bugs/hard/CODEGEN_comprehension_return_type_defaults_
int64.md` (task #145).** `_quick_type` (gimple_codegen.py:6691, the
project-wide return/expression-type estimator that populates forward-
declared function return types via `_collect_return_types`/
`_infer_return_type`, Pass 2b) had NO case at all for a `.keys()`/
`.values()`/`.items()` method call — the real lowering
(`_lower_dict_method`, gimple_codegen.py:11406) correctly returns a real
`MojoList *` (`mojo_dict_keys`/`_values`/`_items`) for all three, but
the pre-pass fell all the way through to the `int64_t` default,
producing a wrong `int64_t` forward declaration against a body that
really returns a pointer — the exact "non-trivial conversion"/"invalid
conversion" class of `-fgimple` refusal this family of bugs always
produces.

**Fixed** in `_quick_type`'s `CallExpr`-on-`MemberExpr` branch
(gimple_codegen.py, right before the "Try as struct instance method
call" fallback): added
```python
if meth in ('keys', 'values', 'items') and not node.args:
    return 'MojoList *'
```
Deliberately UNCONDITIONAL on the receiver's own known type (unlike a
first attempt gated on `self.var_types.get(mod) == 'MojoDict *'`, which
did NOT work — `_collect_return_types` runs BEFORE a function's own
local variable types are recorded into `self.var_types`, so `modules =
{}` earlier in the SAME function body being scanned is invisible at
this point; same documented blind spot as the `.read()`/`.readline()`
case a few lines above it in the same method). Instead treated the same
way that block already treats `.strip()`/`.lower()`/etc. — unconditional
because `.keys`/`.values`/`.items` are dict-view-only method NAMES in
this codebase's supported Python subset (no other builtin container
type has them), so blind-trusting the method name alone is safe by the
same reasoning already established there.

**Verified fixed**: isolated compile
(`compile_to_gimple_with_cpp(..., do_imports=False)`) now declares
`MojoList * ModuleFinder_find_all_submodules(...)` (was `int64_t`), and
the original `:296:1` GCC error is gone from both the isolated compile
and the full `python3 mojo.py build .../modulefinder.py` re-run.

**Remaining, NOT fixed (out of scope, matches an already-deferred hard
bug)**: 2 new-visibility errors at line 284 (`passing argument 3 of
'ModuleFinder_msg' makes pointer from integer without a cast`) —
`def msg(self, level, str, *args):` called as `self.msg(2, "can't list
directory", dir)`. This is the `*args`-parameter-signature shape
`bugs/hard/CODEGEN_args_kwargs_signature_assumed_forwarding_only.md`
(task #142) already covers and this task's guidance explicitly holds
back — not attempted.

### Gate verification for this fix

- `python3 test_gimple.py`, `python3 test_module_cache.py`: see combined
  end-of-session gate run (all passing, 0 failed).
- `make check-selfhost`: passing.
- From-scratch stdlib dylib rebuild: 0 `skip <module>:` lines (same as
  baseline).
- `python3 compile_stdlib.py -j8`: 664/664, 0 unexpected failures (same
  as baseline — this fix does not change the count, since
  `Lib/modulefinder.py` was already not part of the 664-file corpus
  compile_stdlib.py tracks; verified via the shared end-of-session run
  covering all fixes made in this session together).

## Status (updated 2026-08-06, superseded above — struct_toplev errors since independently fixed)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'dis' was not declared` .cpp error no longer reproduces.
`modulefinder.py` has one generator, `scan_opcodes` (lines 393-403,
`yield "store", (name,)` / `yield "absolute_import", (fromlist, name)` /
`yield "relative_import", (level, fromlist, name)` — a tuple-of-
heterogeneous-arity yields). It does NOT appear anywhere in the current
error list and `MOJO_DEBUG=1` shows no "not eligible" refusal naming it
— `scan_opcodes` now appears to compile cleanly through the coroutine
path.

**Classification: NOT a generator-codegen-cluster failure anymore.**
Every current error is well before the generator (lines 89-343, vs. the
generator at 393+) and is the same recurring pattern seen in
`Lib/glob.py`'s current re-diagnosis:

```
/Users/mrs/net/Python-3.14.6/Lib/modulefinder.py:89:30: error: invalid use of undefined type 'struct _subprocess_toplev'
/Users/mrs/net/Python-3.14.6/Lib/modulefinder.py:282:30: error: invalid use of undefined type 'struct _genericpath_toplev'
/Users/mrs/net/Python-3.14.6/Lib/modulefinder.py:296:1: error: invalid conversion in return statement
```
`struct _subprocess_toplev`/`struct _genericpath_toplev` are opaque
per-module "namespace" pseudo-structs this codegen emits for whole-module
attribute access (e.g. `subprocess.something`) — used here but apparently
never given a matching full definition, a module-attribute-access gap in
the same spirit as (though a different concrete shape from) dyld.py's
already-documented bullet 4 ("module attribute access not threaded into
generator scope"), except this occurs in ORDINARY (non-generator) code,
well outside `scan_opcodes`'s own body. Not investigated further — out
of scope for this generator-codegen cluster; worth a `struct _X_toplev`-
focused non-generator bug report on its own (recurs identically in
`Lib/glob.py`'s current error list too — see that file's bug doc).

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/modulefinder.py
