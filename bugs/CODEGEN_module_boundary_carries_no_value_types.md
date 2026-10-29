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
   `_elem_types` is per-function. The doc that covered that half,
   `“Container element types do not survive a function boundary”`, was removed
   2026-10-02 with its fix — container ELEMENT types now cross a function
   boundary — so this wall is narrower than it was: the `char *` case above is
   the one still standing, and the container-element case beside it is not.

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

## Status (2026-10-28, work/bug-codegen-module-boundary-carries-no-v-9328) — PARTIAL

Point 1 (collection gap) fixed: `_scalar_obs` walk now accepts
`MemberExpr` whose base resolves to an imported module (`m.f(...)`) and
keys by the member's bare name (`f`). Verified by `DEBUG` prints that the
call is recognized.

Point 2 (provenance outliving the collector) NOT fixed: when compiling
`u.py` with `do_imports=True`, `_free_params` holds only `['main']` — the
imported `m.f` is not visible to the importer's loop, so `_scalar_obs`
remains empty and `int64_t s` stays emitted for `f`. The mechanism needed
is the same per-module-scan / per-compilation-unit provenance wall described
in step 2 of this doc (precedent: `_gmi_scan_imported_global_homes` for
globals). Next step for a full close: make imported free-function params
visible to the importer's observation pass (either by including them in
`_free_params` via `imported_stmts` or by sharing `_scalar_obs` across the
nested `gen_module_impl` call that emits `m`).

Regression test: `test_module_boundary_regression.py` (fails before/after on
full behavior, because step 2 is missing; passes for the collection fix).

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

## Status (2026-10-29) — PLANNING ROUND; Shape 1 no longer reproduces, Shape 2 is live

Measured on master at 5c238ac76, one `compile_to_gimple(..., do_imports=True)` +
`gcc -fgimple` + run per row (the probes are in `test_module_boundary_regression.py`):

| program | CPython | master |
|---|---|---|
| `m.f('abcd')` then `m.f('xy')`, `def f(s): return len(s)` | `4` `2` | `4` `2` — **correct** |
| `m.gen(['p','q'])`, `def gen(xs): for x in xs: yield x` | `p` `q` | `4370836896` `4370836904` — **wrong** |

So Shape 1 (the `int64_t s` / `mojo_list_len` read) is no longer a wrong answer on
this tree. The emitted parameter may still be untyped; the runtime dispatch
(`mojo_is_registered_dict` and friends) now answers `len` correctly for the
string. I have NOT established why it stopped reproducing, so do not treat that
as the fix for the mechanism — pin it (done, see below) and move on.

**Correction to the 2026-10-28 Status above.** Its "Point 1 fixed" claim does not
hold for the case it names. The `_g2m` branch in `module_gen.py` (the
`MemberExpr` arm of the `_scalar_obs`/`_calls_in_stmts` walk, ~line 9075) only
keys a module-qualified callee when `member_name in _free_params`, and
`_free_params` is built from the IMPORTER's own top-level `FunctionDef`s
(~line 8571). So `m.f(...)` with `f` defined only in `m` is never recorded. The
branch fires only for a homonym (the importer also defines `f`), where it
contributes evidence for the wrong function. The branch is inert for the doc's
own shape.

### Shape 2 — the mechanism, located

Emitted C for the importer (`u.c`, probe in `.tmp/probe2/`):

```c
bb_4:  /* count(guessed_local(10)) */
  _t9 = __mgco_gen_value (_t5);
  v = _t9;                       /* v: int64_t, from the generator's value slot */
  ...
  sprintf (_t10, _t12, v);       /* "%ld" */
```

The loop variable `v` is typed from the callee's yield element type. For
`m.gen(...)` nothing supplies that type to the importer:

1. The importer's element evidence for the argument `['p','q']` is recorded by
   `_static_arg_elems` / `_record_param_elem` only for callees in `_free_params`
   (the loop at ~line 9085–9089), and `m.gen` is not in it (Point above).
2. The imported module's `gen` is compiled by `_compile_imported_module`
   (`module_gen.py:4212`, inside the importer's `gen_module_impl`), which runs
   BEFORE the importer's observation pass (`_free_params` at 8571, `_scalar_obs`
   and the `_param_elem_types` application at ~9630). So even a collected
   observation would reach the child too late: the child's `xs` element type and
   its `yield` slot type are already final in its C when the importer looks at
   its call sites. This is the ordering wall the doc names as step 2; it is real,
   and it is the reason the 2026-10-28 collection fix could not work.
3. Within ONE module the same program is correct because the producer and the
   consumer share one `_elem_types`/yield table. That is the value model working
   as designed, one module deep.

### Decision for the next round (recommendation: A-full)

- **A-full (recommended):** a whole-closure, pre-emission observation pass,
  per compilation unit. Before the root's import loop (`module_gen.py` ~4190,
  before the `for _mc_iter in sorted(modules_to_compile)` loop), parse every
  module in the import closure once (the loader already does this in
  `_compile_imported_module`; hoist it), and collect, for each
  `(defining_module, callee)` pair, the per-parameter element/scalar/container
  observations from EVERY call site in the closure — both `f(...)` in the
  defining module and `alias.f(...)` / `from m import f` in any importer. Store
  the result on the root gen as `_closure_param_obs[(module, callee)]`, keyed by
  the defining module so two modules' same-named functions cannot merge (the
  homonym class `_module_global_field_type`'s docstring argues about). The child's
  `gen_module_impl` consults that table for its OWN `_free_params` when it
  applies `_param_elem_types` / `_scalar_obs` / the yield element type, and the
  unanimity rule is over the whole closure, which is what the vacuous-unanimity
  class (a silent call site counted as agreement) requires. An
  unseen call site (a dynamic `getattr`, a call through a value) must count as
  disagreement, not silence.
- **B (rejected):** defer emission of imported modules' functions until the
  importer's pass is done. Changes the emission order of every stdlib module, and
  the whole-closure gate would need to be rerun on a reordering. Not a
  single-round change.
- **C (rejected for now):** the root-cause fix is the element type of the
  generator's `xs`, so annotate it. The sibling workaround
  (`def gen(xs: list) -> list:`) changes the symptom and links against
  `__mojogen_m_gen_*`, per the original doc. Not a fix.

### Implementation plan for A-full (exact places)

1. `module_gen.py`, before the import loop at ~4190: collect the closure's parsed
   statements (reuse `_compile_imported_module`'s parse, hoisted into a helper so
   the closure is parsed once and both passes share it).
2. New `mojo/middle/module_shared.py` helper `_gmi_scan_closure_call_sites(gen,
   closure_stmts)`: a single walk over every module's `_calls_in_stmts` output.
   For `IdentExpr` callees, resolve to the defining module via the importer's
   `_own_imported_func_home` / `_global_to_module`; for `MemberExpr` callees
   (`alias.f`), resolve via the importer's import alias table. Record into
   `_closure_param_obs[(module, callee)][pname]` the same observation kinds
   `_scalar_obs`, `_param_elem_types` and `_param_container_obs` already collect
   (reuse their collectors — do not write a second one, per CLAUDE.md).
3. `module_gen.py` `gen_module_impl`, at the point where `_free_params` is built
   (~8571): when this module is a compiled import, merge
   `_closure_param_obs[(this_module, name)]` into the local observation maps
   before the application loops at ~9630 and at the `_param_elem_types` apply.
4. Yield element type: the consumer's `for v in m.gen(...)` loop var must take
   the callee's yield element type. Find where `for`-over-generator types its
   target (grep `__mgco_gen_value` / `guessed_local` in `emit_stmts.py`), and feed
   it from the same closure table, keyed by the defining module.
5. Tests: `test_module_boundary_regression.py` (already in place) — the
   `imported_generator_yields_str` case must PASS after; `module_qualified_str_param`
   must keep passing. Add a homonym case (importer and `m` both define `f`,
   different element types at each site) and a case where an unseen dynamic call
   (`getattr`) makes the result int64.
6. Gate, for the integrator (NOT run here): `compile_stdlib.py` `U` must not rise;
   `build_stdlib_dylib.py` `skip` count must not rise; byte-identical C on a
   large succeeding case before vs after, per the CLAUDE.md standard for a
   behaviour-changing fix. Changes to `module_gen.py` and `emit_stmts.py` owe a
   full `make gate` (CLAUDE.md "Before considering a compiled-path change done").

### Evidence for this round

- `test_module_boundary_regression.py` rewritten from a print-only probe (it
  asserted nothing) to a real CPython-comparison test. Run:
  `python3 test_module_boundary_regression.py` → `1/2 passed`, the failing case is
  `imported_generator_yields_str`.
- Probe sources: `.tmp/probe2/{m.py,u.py}` (scratch, not committed).

## Status (2026-10-29, work/bug-codegen-module-boundary-carries-no-v) — PARTIAL FIX (Shape 2, direct importers)

Landed: the importer's call sites now type an imported generator's yield slot.
`coro.lower(stmts, closure_stmts, module_name)` takes the statement lists of the
modules already in the closure (`GimpleGen._closure_call_stmts`, root first, each
imported module appended as it is compiled) and `_scan_callsite_param_kinds`
counts two spellings of a call to THIS module's generator from them:
`<module>.gen(...)` and a bare `gen(...)` bound by an un-aliased
`from <module> import gen`. The evidence feeds the same unanimity/hole rule the
module's own call sites feed, so the child's `value_ctype` becomes `char *` and
the importer's consumer, which already dispatches through the child's published
api, reads it. Measured: `m.gen(['p','q'])` and `from m import gen` print `p q`
(was: addresses); `m.gen([1,2,3])` still prints `1 2 3`.

Test: `test_module_boundary_regression.py` — 4/4 (was 1/2). Covering file
`test_gimple_generator_runner.py` 263/263.

Still open (measured, not fixed):

* **Aliased import** (`from m import gen as g`, `import m as k; k.gen(...)`):
  not counted. Next step: resolve the alias through the importer's
  `name_alias_strs` / `import` table the same way `_from_bound_names` does.
* **A value passed on through a parameter** (`import k; k.pass_through(["p","q"])`
  where `pass_through` does `for v in m.gen(xs)`): the call site that matters
  is one level further out. Needs the param-kind evidence of `pass_through` to
  flow into `m.gen`'s argument, which is the transitive form of the same scan.
* **Ordering**: a call site in a module that is compiled AFTER the child is not
  visible to it. The closure is accumulated in compile order, not pre-parsed.
  The A-full plan's step 1 (hoist the parse of the whole closure before the
  import loop) is what closes this; it is not done.
* **Mixed str/int call sites** of one generator still miscompile (in a single
  module too): `bugs/CODEGEN_generator_mixed_element_call_sites_miscompile.md`.
* **Shape 1** still has no regression pin beyond `module_qualified_str_param`,
  which passes; the mechanism note above still stands unverified.

Gate, for the integrator (NOT run here): `coro.py`, `gimple_codegen.py` and
`emit_resolve.py` changed — a full `make gate` is owed (CLAUDE.md, "Before
considering a compiled-path change done"). Watch `stdlib-dylib` `skip` count and
`stdlib-syntax` `U`, and `bootstrap` because `coro.py` is itself compiled by the
self-host (the new code uses only plain loops and set membership, like its
neighbours, but has not been self-compiled).
