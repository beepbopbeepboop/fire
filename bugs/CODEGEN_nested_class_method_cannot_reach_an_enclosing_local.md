# CODEGEN: a method of a class defined inside a function cannot read that function's locals

**State: OPEN, unfixed.** Found 2026-10-02 while landing the fix for "a
`class` defined inside a function has no methods at all" (that doc is deleted
with its fix). This is the residue that fix leaves, it is a different shape,
and it is the reason the ordinary `cmp_to_key` factory idiom still answers
wrongly.

## What I ran and what I saw

```python
def mk(n: int):
    class C:
        def __init__(self, k: int):
            self.v = n + k
        def get(self):
            return self.v
    return C(1).get()

print(mk(10))
```

| | CPython | compiled |
|---|---|---|
| `mk(10)` | `11` | **`1`**, exit 0, no diagnostic |

`n` reads as `0` inside the hoisted `__init__`, and `self.v` is then `0 + 1`.
There is no message on stdout and no non-zero exit: the name is simply not in
scope in the emitted C, so it falls through
`mojo/backend_gimple/emit_exprs.py`'s unknown-identifier arm to
`_new_temp('int64_t')` + `(int64_t)0; /* ct param or undeclared: n */`.

The real stdlib instance is `Lib/functools.py`'s `cmp_to_key`:

```python
def cmp_to_key(mycmp):
    class K(object):
        def __lt__(self, other):
            return mycmp(self.obj, other.obj) < 0
    ...
    return K
```

Every one of `K`'s comparison dunders closes over the `mycmp` parameter.
`sort(key=...)` with `cmp_to_key` therefore compares with `mycmp` stubbed to 0
— which is `a < b` answering `0 < 0`.

## Why the fix that landed does not cover it

`mojo/backend_gimple/module_gen.py::_gmi_hoist_nested_structs` gives a nested
class a layout and emits its methods by APPENDING the class's `StructDef` to
the module-level statement list — because every consumer of the module's
struct set (the `struct_field_types` seed, `_merge_struct_inheritance`, the
`_alloc_X` helper, the `typedef struct X`, the method-body emission loop) reads
that list and nothing else. That is what makes the methods exist at all.

The emitted method is then an ordinary module-level C function
(`int64_t C___init__ (C *self, int64_t k)`), and `mk`'s frame is not reachable
from it: `mk`'s locals live in `mk`'s own C locals, and there is no
environment struct threaded through. So every free name in a nested class's
body that is not a module-level name is a hard 0.

## What it would take

A class environment, i.e. the closure machinery pointed at a class instead of
at a function. The pieces, and why each is not a one-liner:

1. **An env field per instance.** The hoisted class needs a hidden
   `_env` field of a per-class env-struct type, allocated by
   `_alloc_<Class>` and filled at the construction site from `mk`'s live
   locals. The env struct's name has to be derived from the (possibly
   renamed) hoisted class name, so it must be minted after
   `_gmi_hoist_nested_structs` has settled names — the closure env structs
   (`<lifted>_env`) are minted in `closures.discover_closures`, which runs
   BEFORE `gen_module_impl` and therefore before the hoist.
2. **A capture list per nested class**, i.e. the free names of each method
   body minus `self` and the module-level names, resolved against the
   ENCLOSING function's scope. `closures.discover_closures` already computes
   exactly this for a nested `def` (`_scan_for_closures(ctx, outer_name,
   outer_scope, body)` with `outer_scope` built from the enclosing function's
   params and body); a nested class needs the same walk over `sd.methods`
   instead of `inner.body`, with `outer_name` keyed `(enclosing, class)`.
3. **Every method takes the env**, as a leading `env *` after `self`, and
   every method CALL SITE passes `recv->_env`. The call sites go through
   `_lower_MemberExpr` / `_lower_bound_method_call_value` /
   `mojo_fnptr_call_N` (a bound method of the class), so the parameter is a
   per-class property: the emitted prototype, the definition, and the call all
   have to agree or gcc rejects the TU.
4. **The ownership half.** `ownership_destruct.lambda_value_owned`'s rule —
   "after the binding, the only acceptable mention of the name is as the
   CALLEE of a call" — has no answer for an env reachable from every instance
   of a class, and `bugs/CODEGEN_closure_env_and_boxed_local_never_freed.md`'s
   OPEN 1/OPEN 2 are the same question one level down for functions. Freeing
   wrongly here is a use-after-free on every instance, not one closure.

An honest interim is a REFUSAL rather than a silent 0: a nested class with a
method that reads a name that is neither module-level, nor a parameter of that
method, nor `self`, nor a field of the class is a compile error. That is a much
smaller change than the feature (it is a check over `sd.methods`' free names
against the enclosing function's locals, which
`_gmi_local_binding_names` already collects) and it converts a plausible wrong
number into a build failure — but it will refuse real code, including
`functools`, so it wants `compile_stdlib.py`'s `U` count measured first, per
CLAUDE.md's rule about type-resolution refusals.

## Regression test (when the full fix lands)

`test_gimple_runner.py`, `run_tests`, next to `gimple_nested_class_methods` /
`gimple_nested_class_in_every_body` — the fixture above plus the
`cmp_to_key` shape (a nested class whose method reads the enclosing
PARAMETER), asserted against CPython's exact text. The full fix restores the
`11\n` assertion in place of the refusal below. A compile-only assertion
is worthless here: this compiles, links and exits 0.

## 2026-10-28 update (work/bug-codegen-nested-class-method-cannot-r-2810)
- Confirmed still OPEN / unfixed.
- Added regression test `test_gimple_runner.py::test_nested_class_method_reads_enclosing_local_regression` (expects `11\n`, currently produces `1\n` — failure verified by inspection of emitted C fallback to `/* ct param or undeclared: n */`).
- Full fix requires per-class env struct, capture list over `sd.methods`, and ownership/freeing rules; beyond light-worker scope (needs `discover_closures` extension + env struct minting before `_gmi_hoist_nested_structs`, plus `emit_methods.py` / call-site parameter threading). Not attempted.
- No doc removal; not fully fixed.

## 2026-10-29 planning round (work/bug-codegen-nested-class-method-cannot-r)

Output of this round is a planning guide, not a fix. Reason: the full fix is
the env-threading feature described above, which is a multi-file change to
the hoist, closure discovery, method emission and call-site lowering, with an
ownership question still open (point 4); it cannot be verified inside a light
round, and the one interim that is small (a refusal) changes stdlib behaviour
that only the gate can measure.

### Measured state
- `python3 tools/memslot.py --gb 8 --label nested-class-test -- python3 -c
  "import test_gimple_runner as t; t.test_nested_class_method_reads_enclosing_local_regression()"`
  prints `FAIL gimple_nested_class_method_reads_local: expected stdout '11\n',
  got '1\n'` (peak 0.2 GB). The regression test is already on the branch; it
  is red and pins the right value. (Note: the helper records FAIL in its
  module-level `_FAIL` counter and does not raise, so a direct call returns
  normally; judge by the printed FAIL line or by the runner's tally.)
- Indented `class` inside `def` in the repo's own `.mojo` sources: none
  outside `bugs/`/`.tmp/` and the formal docstrings (`formal/hostmods/enum.mojo`
  declares `class Reg(Enum)` inside a test-program string, not a live nested
  class). The Mojo stdlib itself lives in an external modular checkout
  (`module_loader.py` `_STDLIB_CANDIDATES`, `mojo/stdlib` / `Mojo/stdlib`), not
  in this worktree, so the stdlib impact of a refusal is NOT measured yet.
  Measurement to run before any refusal lands: an AST walk over that stdlib
  tree for a `ClassDef` nested in a `FunctionDef` whose method's free loads
  intersect the enclosing function's bound names (a ~40-line script; the
  bindings walk is `_gmi_local_binding_names` in
  `mojo/backend_gimple/module_gen.py:2875`). Count the hits per file; that
  number is the `U` risk for `compile_stdlib.py`.

### Decision needed (for the next round)
- **A. Full env threading** (recommended end state). Per-class `_env` field,
  capture list, env param on every method, call-site threading, ownership rule.
  Implementation order below.
- **B. Refusal interim** (the doc's named stopgap). A compile-time error for a
  nested-class method free name that is an enclosing-function local/param.
  Reading: changes silent-0 into a build failure. Under B, `compile_stdlib.py`
  `U` must not rise: if the measurement above finds hits in the stdlib, each
  such file goes in `EXPECTED_FAILURES` with a reason, or B is not landed and A
  is done first. Choose B only if the measurement is zero or small.
- Recommendation: measure first (no code), then A if the stdlib hits are
  non-trivial and B if they are zero-to-few and A is deferred.

### Implementation plan for A (exact files, functions, ordering)
1. **Measurement** (above). No code.
2. **Capture analysis** — `mojo/middle/closures.py`: factor the free-name walk
   behind `discover_closures` / `_scan_for_closures(ctx, outer_name, outer_scope,
   body)` so a class body can use it: walk each `sd.methods` entry instead of
   `inner.body`, key the capture list by `(enclosing, class)`. Both the function
   and the class path call the same walk (no parallel copy — CLAUDE.md).
3. **Env struct minting** — must happen after `_gmi_hoist_nested_structs`
   settles names and before `_alloc_<Class>` is emitted. Today
   `closures.discover_closures` (imported in `module_gen.py:70`) runs before
   `gen_module_impl`, so the class-env struct either moves into that pass or is
   minted in `module_gen.py` right after the hoist (`module_gen.py:3085`).
4. **Hoist** — `_gmi_hoist_nested_structs` (`module_gen.py:2964`): add the
   hidden `_env` field to the hoisted `StructDef` when the class has captures.
5. **Construction** — the `_alloc_<Class>` helper and the construction site
   (the call that instantiates the class inside `mk`) fill `_env` from `mk`'s
   live locals (`mk`'s C locals are addressable there; use the existing
   closure-env fill as the model).
6. **Method emission** — `emit_methods.py` (method prototype and definition)
   takes a leading `env *` after `self` when the class has captures; the
   method body reads captured names as `self->_env-><name>`.
7. **Call sites** — `emit_calls.py` (`_lower_MemberExpr`,
   `_lower_bound_method_call_value`, `mojo_fnptr_call_N` path; see the
   `_gmi_hoist_nested_structs` note at `emit_calls.py:3460`) passes
   `recv->_env` for a capturing class. Prototype, definition and call must agree
   or gcc rejects the TU.
8. **Ownership** — `ownership_destruct.lambda_value_owned` has no rule yet for
   an env shared by every instance. Until it does, the env is leaked, not freed
   (leak is safe; a wrong free is a use-after-free). Track with
   `bugs/CODEGEN_closure_env_and_boxed_local_never_freed.md`, which is the same
   open question for functions.

### Tests that prove it
- `test_gimple_runner.py::test_nested_class_method_reads_enclosing_local_regression`
  (exists; must go green: `11\n`).
- Add the `cmp_to_key` shape (a nested class whose method reads the enclosing
  PARAMETER, comparing via `sort`) to `test_gimple_runner.py` next to
  `gimple_nested_class_methods`, asserted against CPython's exact text.
- Under B only: a test asserting the refusal diagnostic and a non-zero exit,
  not a silent `1`.
- Gate (integrator, not this worker): `make gate` for any change under
  `module_gen.py`/`emit_*`/`closures.py`; `stdlib-syntax` `U` must not rise.

Status after this round: planning guide landed; no code changed; the doc stays
(not fixed).

## 2026-10-29 partial fix (work/bug-codegen-nested-class-method-cannot-r): the refusal interim, B

What landed (the doc's own named stopgap; the silent 0 is now a build failure):

- `mojo/backend_gimple/module_gen.py::_gmi_refuse_nested_class_enclosing_reads`,
  called once from `gen_module_impl` after the hoist. A method of a class
  declared in a function body that reads a parameter or binding of that
  function raises `ValueError` naming the method, the class, the name and the
  function. Method-own names, `self` and module-level names are not refused.
- Measurement behind choosing B: the Mojo stdlib (`modular/mojo/stdlib`) has
  no real nested-class-in-def. Its 57 indented `struct`/`class` hits are
  docstring examples, so the refusal changes no stdlib compile. Gate
  `stdlib-syntax` `U` should therefore stay flat; the integrator confirms.
- `test_gimple_runner.py` (`run_tests`): two refusal cases (the `cmp_to_key`
  parameter shape, and a local read) and one no-regression case (a method
  reading a module global, expecting `12`). The old regression test that pinned
  `11` was a function defined after the file's `if __name__` guard, so it never
  ran; it is replaced by the refusal cases above.

What is still missing: the full fix (per-class env, capture list, env param on
every method, call-site threading, ownership rule), plan steps 2-8 above. Until
it lands, a nested-class method that reads an enclosing local is refused, not
answered.
