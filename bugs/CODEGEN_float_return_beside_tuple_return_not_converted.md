# CODEGEN: a function returning a float on one path and a tuple on another fails `gcc -fgimple` ("cannot convert to a pointer type"), which breaks the self-host build

Status: OPEN. Filed 2026-11-12 from a failing `make` of `fire.o`. Re-measured 2026-11-12 (planning round, see `## Status (2026-11-12)` at the end): the gcc error is GONE on master, but the underlying bug is worse than the symptom — the float is silently truncated, and the program segfaults at run time. The guide below is the next step; no code has landed yet.

## Symptom

Building the self-hosted compiler stops at `fire.o`:

```
python3 fire.py fire.py --dump-full          # ✓ Generated fire.ci
sed -i '' 's/^int main/int mojo_main/' fire.ci
gcc-mp-15 -Os -g -fgimple -ftrivial-auto-var-init=zero -I runtime -c -x c fire.ci -o fire.o
mojo/middle/comptime.py: In function 'mojo_middle_comptime_eval_const_3837fb':
mojo/middle/comptime.py:470:3: error: cannot convert to a pointer type
  470 |     if isinstance(node, FloatLiteral): return node.value
make: *** [fire.o] Error 1
```

`fire.ci` is generated without complaint; it is the C compiler that rejects it. So the self-hosted binary (stage1 and everything after it: `make bootstrap`, `mojoc`) cannot be built from current master.

## Cause of the regression (known)

Line 470 of `mojo/middle/comptime.py` was added on 2026-11-12 by `13b16397d` ("decide float comparisons in comptime conditions"): `eval_const` gained `if isinstance(node, FloatLiteral): return node.value`. That function already returns booleans, ints, strings, `('.', name)` tuples, built tuples, built lists and `None`. The new branch is the first one that returns a `float` beside the pointer-valued (tuple/list) returns.

## Minimal repro (no compiler closure needed)

`mixed_ret.py`:

```python
from dataclasses import dataclass

@dataclass
class FloatLit:
    value: float

@dataclass
class TupleE:
    elements: list

def eval_const(node):
    if isinstance(node, FloatLit): return node.value
    if isinstance(node, TupleE):
        res = []
        for e in node.elements:
            res.append(eval_const(e))
        return tuple(res)
    return None

def main():
    print(eval_const(FloatLit(1.5)))
```

```
python3 fire.py mixed_ret.py --dump-full
gcc-mp-15 -Og -fgimple -I runtime -c -x c mixed_ret.ci -o mixed_ret.o
# mixed_ret.py:12:3: error: cannot convert to a pointer type
#    12 |     if isinstance(node, FloatLit): return node.value
```

Measured 2026-11-12 on master, same compiler, one variable changed per row (return branches of `eval_const`):

| returns | `gcc -fgimple` |
|---|---|
| float, str, None | OK |
| bool, int, float, str, None | OK |
| int, float, None | OK |
| **float, tuple, None** | **FAIL: cannot convert to a pointer type** |
| **float, str, tuple, None** | **FAIL: cannot convert to a pointer type** |

So the failing ingredient is a `tuple` (a pointer-valued) return beside a `float` return. Scalars beside each other, and a float beside a string, are handled.

## What is not yet known

- Which representation the function's return slot gets in the failing case. The error says the float branch is being converted *to a pointer type*, which suggests the return type was inferred as a pointer (from the tuple branch) and the `double` is returned without being boxed into it. Look at how `int` and `bool` returns beside a tuple are boxed and why `float` is not (the `int+float+None` row passes, so the scalar case is fine; the tuple case is the one to read in the generated `fire.ci`).
- Whether a `list` return behaves like a `tuple` (the real `eval_const` returns both).

## Scope and rule

Fix the codegen, not the call site: a function that returns a float on one path and a tuple on another is ordinary Python and must compile. Do not paper over it by rewriting `eval_const` (CLAUDE.md: no quick fix; consolidate, do not work around). If the proper fix is large, land the part that makes this repro compile and say what remains.

## Acceptance

- `mixed_ret.py` above compiles through `fire.py --dump-full` and `gcc -fgimple -c` with no error, and `eval_const(FloatLit(1.5))` prints `1.5` when run.
- The other rows of the table still compile.
- A regression test, `test_float_return_beside_tuple_return.py`, runs that repro (compile and run, compare with CPython's output) and passes.

## Done when

`python3 test_float_return_beside_tuple_return.py` passes. Then, as the integrator's concern and not a worker's: the `fire.o` step of the self-host build (the command in the Symptom section) gets past `mojo/middle/comptime.py`. A worker does not run the whole-closure build; report that step as not run.

## Status (2026-11-12, planning round)

### What is true on master (HEAD bd6048baa), measured

The gcc error in the Symptom section no longer reproduces, because a previous change already routes the float through an `int64_t` temp:

- `mojo/backend_gimple/emit_resolve.py:2615-2630`, the `elif d.endswith(' *') and s in ('double', 'float')` arm of `_sce_simple_emit`, emits `_tN = (int64_t)<double>; dest = (<ptr>)_tN;`. Pinned by `test_float_into_pointer_return_regression.py`.
- `mixed_ret.py` (the repro above) now compiles: `gcc-mp-15 -Og` and `-Os` both exit 0.

That fix is the bug, not the cure. `(int64_t)` truncates the value, and the caller then treats the integer as a `MojoList *`:

- Generated C for `eval_const` on the float arm: `_t7 = _t6->value; _t9 = (int64_t)_t7; _t8 = (MojoList *)_t9; return _t8;`. `eval_const(FloatLit(1.5))` returns a list pointer to address `1`.
- Run-time, through the production compile path (`test_gimple_runner.compile_mojo_to_gimple_exe` + run), every mixed-return shape below exits with SIGSEGV (rc -11), and CPython prints the values shown:

| function (returns, in order) | GIMPLE binary | CPython |
|---|---|---|
| `1.5`, `"s"`, `None` (`pick`) | rc -11, no output | `1.5` / `s` / `None` |
| `2.5`, `(1, 2)`, `None` (`tup`) | rc -11, no output | `2.5` / `(1, 2)` / `None` |
| `1.5`, `"s"` (only two arms) | rc -11, no output | `1.5` / `s` |

- The inferred C return type is `char *` / `MojoList *`, not a tagged word, because `TypeLattice.join` lets a pointer beat a double: `mojo/middle/types.py:187-194` (`join`), reached through `TypeLattice.join_all` in `mojo/middle/infra_infer.py:1916-1921` (`_infer_return_type_core`) and the wrapper `gimple_codegen.py:5644`.
- The element-level guard in `mojo/middle/resolve_shared.py:1483-1492` refuses a float+pointer mix only for the RETURN ELEMENT (`_return_elem_types`, the tuple slot), not for the function's own C return type. That is why the function type is still a pointer.

### Decision for the next round (recommended: option A)

**A. Tagged-word return for a float+pointer join.** A function whose return arms join a `double` with a pointer returns `int64_t`, the tagged word the codebase already uses for "a double that must travel beside non-doubles" (`_int64_may_hold_float`, `mojo_box_from_double`). Each arm is boxed or wrapped:
- `double` arm: `mojo_box_from_double(v)` (fresh kind-'d' box, `runtime/fire_runtime.c:1889`).
- `str` arm: `mojo_box_from_str(s)` (kind-'p', `fire_runtime.h:864`).
- `None` arm: `mojo_box_none()` (`fire_runtime.h:865`).
- `tuple`/`list` arm: NEW `mojo_box_from_list(MojoList *)`, kind 'l'. `mojo_repr_boxed` already renders kind 'l' (`fire_runtime.c:2237`) but nothing creates one; `'l'` today is only a list-slot kind.
- any other pointer kind (dict, set, bytes): refuse at codegen with a diagnostic naming the function. Do not guess.

Option B, refusing a float+pointer return at codegen, is rejected: it turns `comptime.py`'s `eval_const` into an unbuildable program, which is the workaround CLAUDE.md forbids.

### Implementation plan (files, functions, order)

1. `runtime/fire_runtime.c` / `fire_runtime.h`: add `mojo_box_from_list(MojoList *)` beside `mojo_box_from_str` (kind 'l', `bits` = the list pointer, registered in `_reg_box` like the others). Add the header prototype.
2. `mojo/middle/infra_infer.py`: `_infer_return_type_core` (1916) — when `acc` holds a `double` AND a pointer, return `'int64_t'` and record the function in a `return_may_hold_float` set (module-level, like `_int64_may_hold_float`). The same change in `gimple_codegen.py:5644` if it is a second copy: consolidate, do not duplicate (CLAUDE.md).
3. `mojo/backend_gimple/emit_resolve.py` `_sce_simple_emit`: the `double`/`float` → pointer arm must not truncate. With the function's return type now `int64_t`, a return of a double goes through `mojo_box_from_double`; a pointer arm goes through the box helper for its kind. Remove the `(int64_t)` truncation arm. (The `(int64_t)<double>` form is what `test_float_into_pointer_return_regression.py` pins; that test must be rewritten to assert the boxed form, not deleted.)
4. Callers (`mojo/middle/calls_shared.py`, `_quick_type` of `CallExpr`, `mojo/backend_gimple/emit_infra.py` around 7512-7690): a call to a `return_may_hold_float` function has type `int64_t` and is a possibly-boxed word. Extend the existing name-form precedent `_is_may_hold_float_param` to `CallExpr` nodes whose callee is in that set: print and f-string render through `mojo_repr_boxed`; a use as a pointer goes through `mojo_box_word` first. `TypeLattice.coerce` (`types.py:253-256`) refuses an `int64_t`→pointer cast outright, so every such coercion has to be routed through the unwrap, not a bare cast.
5. `mojo/middle/resolve_shared.py:1483-1492`: unchanged in behaviour; its refusal already matches option A for the element case.

### Tests that prove it

- `test_float_return_beside_tuple_return.py` (new, next to `test_float_into_pointer_return_regression.py`): for each row of the run-time table above, compile through `compile_mojo_to_gimple_exe(src, filename='x.py')`, run, and compare stdout to CPython's. This is the doc's named quick test. It FAILS on master (rc -11 today) and must pass after.
- `test_float_into_pointer_return_regression.py`: rewrite its two assertions (currently pinning `(int64_t)2.5`) to the boxed form; keep `test_int_return_into_the_same_shape_still_compiles`.
- `mixed_ret.py` (the Minimal repro): `eval_const(FloatLit(1.5))` prints `1.5`, and `TupleE(...)` prints the tuple.

### Not done in this round

No code changed. The self-host `fire.o` step is the integrator's to run (see Done when). `eval_const`'s callers in `mojo/middle/comptime.py` have not been audited for which consumers read the value as a float, which option A's step 4 depends on: do that audit first in the next round.

## Status (2026-11-12, re-3 round): caller audit done; option A is not a one-function change

Round re-3 started from the planning round above and did the audit it asked for first. No codegen changed. Landed: `test_float_return_beside_tuple_return.py`, the named acceptance test (four programs: `pick`, `tup`, a `float/tuple/None` mix, and the `eval_const` repro). It compiles each through `compile_mojo_to_gimple_exe`, runs it, and compares stdout with CPython. **It is RED on master** (binary exits -11, reproduced 2026-11-12). It is not registered in `tools/suite.py`, so no gate runs it. Treat it as the acceptance test for the next round, not as a passing check.

### Audit: who reads `eval_const`'s result

`mojo/middle/comptime.py:eval_const` (line 439) is recursive and its result is consumed as a value, not just returned:

- Internal, about 45 sites in `comptime.py` (lines 258–1179 among them): `l = eval_const(node.left, ...)` then `l + r` / comparisons (650–720, 974–984), indexing `base[idx]` and slices (337–361), `in` (685), container building `res.append(v)` (485–506, and 1160), `isinstance`-style dispatch on the value, and `None` tests on every result.
- External: `mojo/middle/resolve_shared.py:2456` (`comptime_eval.eval_const(node, gen._comptime_vals)`), `mojo/backend_gimple/emit_calls.py:1776` and `:5788`, and `mojo/backend_gimple/emit_stmts.py:4561`, `:4574`.

Consequence: if `eval_const` is typed `int64_t` (option A, step 2), every one of those sites receives a tagged word where it expects a `bool`/`int`/`str`/`tuple`. The string and tuple branches would have to be unwrapped at every internal read, and the arithmetic sites would need the float unwrap as well. Changing only `infra_infer` would make the repro print wrong values silently in the self-hosted build, which is worse than the current SIGSEGV. Do not land step 2 without the consumer changes.

### Decision for the next round

1. Before any type change, make the consumer contract explicit in `comptime.py`: one `eval_const` that returns the tagged word is wrong for its own recursion. Choose one of:
   - (a) Keep the typed recursion, and make the tagged word a boundary property: `eval_const` (the pointer/bool/int typed core) stays as it is, and a separate float-aware entry point is what the codegen-facing consumers call. This needs a real split of the float arm, not a rewrite of the repro; it changes which function the float branch lives in, so it is a source-structure decision. Record the choice in the Status before coding.
   - (b) Full option A: `eval_const` returns `int64_t`, and each of the ~50 sites above unwraps with `mojo_box_word` (strings and tuples, via a `mojo_box_from_list` added beside `mojo_box_from_str`) or `mojo_box_int` (arithmetic). Larger, but it is the change the planning round's guide describes, and it touches no new contract.
   Recommendation: (b), because the repro is the consumer contract the codegen has to honour for any mixed-return function, not just this one. (a) hides the bug in `comptime.py` and leaves the next mixed function broken.
2. Then the planning round's plan steps 1–5 (runtime box, `infra_infer` join, `_sce_simple_emit` truncation arm, call-site typing via a `_ret_may_hold_float` set, and `_gen_stmt_ReturnStmt` boxing). Run the four cases in the test; the printed output must match CPython.
3. Rewrite the two assertions in `test_float_into_pointer_return_regression.py` that pin `(int64_t)2.5` to the boxed form, keeping `test_int_return_into_the_same_shape_still_compiles`.

The self-host `fire.o` step remains the integrator's to run (see Done when).
