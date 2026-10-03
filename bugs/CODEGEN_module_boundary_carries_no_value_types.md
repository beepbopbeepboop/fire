# CODEGEN: a module boundary carries no value types — an imported function's unannotated `char *` parameter is typed `int64_t`, and `len()` on it reads a list header

**Status (2026-10-01 — OPEN, measured on current master, NOT fixed. Found while
building the CPython-comparison fixture for
`CODEGEN_inline_import_string_pool_name_collision.md`; the fixture had to be
written with annotated parameters because of it.)**

Two shapes, one root: the tables that answer "what is in this value" are
per-`GimpleGen`, and every `GimpleGen` in an inline-import closure except the
root belongs to ONE module. So a fact learned in the importer is invisible in
the imported module, and the importer's `mod.f(...)` spelling hides the call
site from the one pass that would have carried it.

Neither shape is a crash and neither reports anything: exit 0, and a number
that is really a heap address.

## Shape 1 — `mod.f(str_literal)`, and `len()` on the parameter

`m.py` / `u.py`, `compile_to_gimple(u.py, do_imports=True)` → `gcc -fgimple` →
run, next to `python3 u.py`:

```python
# m.py
def f(s):
    return len(s)

# u.py
import m
def main():
    print(m.f('abcd'))
main()
```

| | CPython | compiled |
|---|---|---|
| `m.f('abcd')` | `4` | `6581285` |
| two call sites, `'abcd'` then `'xy'` | `4` `2` | `6581285` `7308325556857761645` |

The emitted C says exactly what happened — the parameter is an integer and
`len` is the list branch:

```c
void m_f_9f63a2 (int64_t s)
{
  _t2 = s;
  _t3 = (int64_t)_t2;
  _t1 = (MojoList *)_t3;          /* the string, read as a blob */
  _t4 = mojo_list_len (_t1);      /* 6581285: the count field of "abcd" */
```

**What makes it a module-boundary bug and not a general inference gap:** the
SAME program with the callee spelled as a bare name in ONE module is right.

| shape | CPython | compiled |
|---|---|---|
| one file, `f('abcd')` | `4` | `4` |
| one file, `def f(s: str) -> int` | `4` | `4` |
| imported, `def f(s: str) -> int` | `4` | `4` |
| imported, unannotated `s` | `4` | `6581285` |

Mechanism, located. `module_gen.py`'s free-function contract builds
`_scalar_obs` (callee → param → {observed argument types}) and then, at the
`for callee in sorted(_scalar_obs)` loop, resolves a param to `char *` when the
observations are unanimously `char *` and no annotation says otherwise. Two
things are missing for `mod.f(...)`:

1. **The observation is never made.** The walk that fills `_scalar_obs`
   recognises a callee spelled as a bare `IdentExpr` — the comment above
   `_collect_method_scalar_obs` says so and then fixes exactly that gap for
   METHODS (`self.q.backward(gq, n)`, `obj.method(xs)`). A module-qualified
   free function (`m.f(...)`) is the remaining spelling with no collector, so
   `f` has no observations at all and falls through to the `int64_t` default.
2. **Even a collected observation would arrive too late.** `_scalar_obs` is a
   local of one `gen_module`, and `_inferred_param_types` is consumed while
   that module's functions are EMITTED. An imported module is compiled — and
   its C written — from inside the importer's own pass, so the importer's
   observations cannot reach it by sharing a dict; that is the same reason
   `_elem_types` is per-function (see
   `bugs/hard/CODEGEN_cross_function_container_element_type.md`, which is this
   defect one level in, for container elements instead of `char *`).

The sibling doc `CODEGEN_polymorphic_unannotated_param_vacuous_unanimity.md`
holds the full statement of the contract and the other half of its defect (an
integer call site's silence counted as agreement). This doc is the
module-qualified spelling, and it needs a fix that doc's does not.

## Shape 2 — a generator in an imported module yields strings as addresses

Same closure, same silent wrong answer, different carrier:

```python
# m.py
def gen(xs):
    for x in xs:
        yield x

# u.py
import m
def main():
    for v in m.gen(['p', 'q']):
        print(v)
main()
```

| | CPython | compiled |
|---|---|---|
| `m.gen(['p','q'])` | `p` `q` | `4302433896` `4302433904` |
| `m.gen([1,2,3])` | `1` `2` `3` | `1` `2` `3` (correct) |
| one file, `gen(['p','q'])` | `p` `q` | correct |

Ints cross the boundary and strings do not, which is the value model again: the
element type of `['p','q']` is recorded in the IMPORTER's `_elem_types`, the
imported generator's loop variable is untyped, and `x` — the `char *` itself —
is what gets yielded and then read as an integer. Linking needs the coroutine
runtime (`runtime/fire_coro.c`, `fire_coro_gen.c`, `fire_async_sched.c` and the
stack-switch context) or the program does not link at all, which is a
misleading first symptom: the shape looks refused when it is wrong.

Annotating the generator's parameter changes the symptom rather than fixing it
(`def gen(xs: list) -> list:`) — the emitted companion then references
`__mojogen_m_gen_destroy` / `__mojogen_m_gen_resume`, which are not defined
where a plain-C link can find them.

## Next step

1. Collect observations for a module-qualified callee: teach the `_scalar_obs`
   walk to accept `AttributeExpr` whose base resolves to an imported module and
   key it by the member's bare name, and do it in a collector that runs over
   the WHOLE closure before any module's functions are emitted. Step 2 above is
   the part that is not a small edit — it is the same "provenance has to
   outlive the function that learned it" wall as the `_elem_types` doc's, and
   the two should be solved by one mechanism rather than two.
2. Until then a parameter annotation is the workaround, which is why the
   sibling doc's regression fixture (in `test_gimple_runner.py`,
   `imported_string_pool_declared_once`) annotates every parameter it passes
   across a module boundary. That comment is the only place in the tree that
   says so, and this doc is the reason it has to.

## Evidence

- `.tmp/probe_matrix.py`, `.tmp/probe_gen2.py` (regenerate: they are three-line
  `compile_to_gimple(..., do_imports=True)` + `gcc -fgimple` + run harnesses,
  each printing CPython's answer beside the compiled one).
- The `int64_t` parameter and the `mojo_list_len` read are quoted from the
  emitted C, not inferred.
- Measured unchanged by the string-pool work that found it: re-running the same
  probes with the pre-fix pool emission emulated (every gen given an empty
  `_str_pool_declared`) returns byte-identical wrong answers.

## Status (2026-10-02, `work/bugs4-3-c`) — one wall of this doc's step 2 now has a named precedent

Neither shape is fixed and neither regressed: `m.f('abcd')` still prints
`6581285`-shaped garbage where CPython prints `4`, and
`for v in m.gen(['p','q'])` still prints two addresses. What this branch added
is a second instance of the SAME wall this doc names, and the way it was
solved is the precedent for step 2 here.

The wall: "the observation must outlive the function that learned it". For a
`from b import K` global read as a BARE name, the importing module has to load
`_b_globals.K` — the OWNER's field — and `_b_globals` is not in `_a_globals`'s
scope in any table `_lower_IdentExpr` had. The fix is a per-instance dict,
`_own_imported_global_home` / `_own_imported_global_field`, filled once by
`_gmi_scan_imported_global_homes` (`mojo/middle/module_shared.py`) from THIS
module's own top-level `FromImportStmt`s, and deliberately NOT shared across
nested temp_gens — the same decision `_own_imported_func_home`'s own comment
gives ("sharing is exactly what caused the bug", from the `alpha_wrapper` /
`beta_wrapper` miscompile).

Two things about that are worth carrying into this doc's step 1:

* **The collection point is a module-level scan, not the call site.**
  `_gmi_scan_imported_global_homes` runs once per `gen_module_impl`, after
  Phase 1.7 and before the first function body — because a per-call-site
  collector cannot answer "was this name imported HERE", and the name-keyed
  whole-tree tables it would consult (`_global_to_module`) answer that question
  wrongly for a sibling's same-named global. A `_scalar_obs` collector over the
  whole closure wants the same shape: one pass, per-compilation-unit, keyed so
  that two modules' claims cannot silently merge.
* **The owner must be provable, not plausible.** The scan records a home only
  when `_module_global_field_type(owner, name)` answers — i.e. when the owner's
  field list says the field EXISTS. A collector that trusts `_global_to_module`
  alone would type `m.f`'s parameter from a call site in some OTHER module and
  get it wrong silently, which is the homonym class
  `_module_global_field_type`'s own docstring argues about at length.

The other half of step 1 is unchanged and still the real work: teaching the
`_scalar_obs` walk to accept a module-qualified callee at all, which this doc's
"Shape 1" section locates precisely.
