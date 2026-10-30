# CODEGEN/INTERP: a plain `@decorator` on a `def` is never applied, on either execution path

## Status (2026-10-29, rebinding extended to a `def` nested in a function body)

- `module_gen.py` `_gmi_rebind_decorated_defs` is now `_gmi_decorator_pass`,
  a scope-aware walker that runs at module scope and recurses into every
  function body. A decorator resolves against the defs of the enclosing
  scopes, so a nested `@twice` (module-level def) and a nested sibling both
  rebind. The nested rebinding is a local `step = twice(step__undecorated)`.
- The scalar refusal (`_gmi_refuse_scalar_decorator_rebind`) runs at every
  level against the same scope, so a nested scalar decorator is refused too.
- Probe before / after on `outer(7)` with a nested `@twice`: before `8`,
  after `16` (CPython `16`).
- Tests: `test_gimple.py` `nested_decorator_is_applied_at_runtime` (compiled
  output equals CPython, `40`) and `nested_scalar_decorator_rebind_is_refused`.
  `test_gimple.py`: 413 passed, 1 failed. The failure was the walk-memo
  census on `mojo/middle/coro.py` (`_capture_self_into_generator` and
  `_finish_sync_hoist` mutated memoized AST nodes without invalidating them);
  it is not this change and is fixed on this branch by invalidating at those
  two write sites.

**Still OPEN:**

- **Decorators from another module** are still silently unapplied (an
  imported decorator stays on the `def`). This is the `subdir` shape from
  `Tools/wasm/wasi/__main__.py` if that decorator is imported.
- A decorated `def` inside an `if`/`for`/`with` block in a function body is
  not reached: the recursion covers a body's direct statements only.
- **Defect 1** (the decorator's own parameter typed `int64_t`) is not
  addressed; it works because a function pointer is carried as an `int64_t`
  bit pattern.
- **The repr of a decorated wrapper** prints the decorated name, not
  `<function twice.<locals>.wrap at ...>`.
- **Integrator gate:** the rewrite now also applies to nested decorated defs
  in the stdlib. The `stdlib-dylib` `skip` count and `stdlib-syntax` `U`
  count must be compared before and after.

Found 2026-09-27 while closing
`COMPILE_FAIL_Tools_wasm_wasi___main__.md`. Not a compile failure — the
opposite kind of problem, and the reason that file needed a separate
correctness caveat even after it started building.

## Status (2026-10-29, rebinding landed for same-module decorators — defect 3 is fixed for integer returns; the rest is open)

**Landed (the step-(b) rebinding model, in its simplest correct form):**

- `module_gen.py` `_gmi_rebind_decorated_defs`: a top-level `@deco` or
  `@deco(x)` whose name is a top-level `def` in the SAME module is rewritten
  to `def step__undecorated(...)` plus `step = deco(step__undecorated)` at the
  def's position, in source order. Stacked decorators nest innermost-first
  (`@a @b` -> `a(b(...))`). A factory is `step = deco(x)(step__undecorated)`.
  The global then holds the decoration's value, and the existing module-global
  call machinery (`_root_globals` + `mojo_fnptr_call_N`) calls it. No call
  site had to learn about decorators. Annotation decorators (`staticmethod`,
  `export`, `doc_hidden`, ...) and imported decorators stay on the `def`.
- `emit_calls.py` `_callee_is_fnptr_value`: one predicate for "a bare-name
  callee is a value, not a C symbol", now used by BOTH the expression call
  path and the statement call path. Before, a discarded top-level `step(7)`
  checked only locals and called the absent `step` symbol, which lowered to a
  weak `unavailable in compiled mode` stub. That stub bug was already present
  for an ordinary module-level closure (`f = outer(3); f(10)` as a statement).
- `emit_exprs.py`: a global read carries `_global_func_value_names` to its
  read-back temp, so `print(step)` formats a function value.
- The scalar refusal (a) still runs first, so a scalar decorator is still
  refused rather than rebound to a non-callable.

**Tests:** `test_gimple.py` `decorator_rebinding_is_applied_at_runtime`
compares compiled stdout with CPython for a wrapping decorator, a factory
wrapper, and stacked decorators. Against the pre-change `module_gen.py` it
prints `8` where CPython prints `16` (checked by disabling the rewrite); with
the change it passes. `test_gimple.py` as a whole: 412 passed, 0 failed.
`every_ast_mutation_site_invalidates_the_walk_memo` needed one allowlist
entry for the new `copy.copy`'d node, with its reason.

**Still OPEN:**

- **Decorators from another module** and a decorated `def` nested in a
  function body are still silently unapplied.
- **A wrapper that returns `str`** prints a decimal address. That is the
  closure str-return gap (fixed as CODEGEN_closure_str_return_is_lost), not this rebinding.
  The runtime test is integer-only for that reason.
- **Defect 1** (the decorator's own parameter typed `int64_t`) is not
  addressed. It works today because a function pointer is carried as an
  `int64_t` bit pattern, which is fragile and not the model the planning entry
  below intended.
- **The repr of a decorated wrapper** is the decorated name (`<function step at
  ...>`), where CPython prints `<function twice.<locals>.wrap at ...>`. The
  pass-through case matches CPython; the wrapper case does not.
- **Integrator gate:** the rewrite applies to every same-module decorated
  top-level `def` in the stdlib too. The `stdlib-dylib` `skip` count and
  `stdlib-syntax` `U` count must be compared before and after.

## Status (2026-10-29, worker round — refusal extended to factories; a false refusal in (a) fixed; defects 1-3 still open)

- **Factory decorators are now refused too.** `@deco(x) def step` where
  same-module `deco` returns a scalar (`return 99`) stops the compile with
  `decorator 'deco(...)' on 'step' returns int64_t (not callable)`. Test:
  `test_gimple.py` `scalar_decorator_factory_rebind_is_refused` (fails
  before this change: the CallExpr decorator was skipped).
- **A false refusal in the (a) refusal below is fixed.** `_infer_return_type`
  types a bare `def` name as `int64_t`, so `def deco(f): def wrap(g): ...;
  return wrap` (and `return some_module_def`) was refused although it returns
  a function. A return of any `def` name is now exempt, as a return of a
  parameter already was. Test: `nested_bare_decorator_returning_a_def_still_compiles`
  (fails at the previous HEAD, passes after); `nested_decorator_factory_still_compiles`
  guards the factory spelling of the same shape.
- **`test_print_of_a_function_value_is_not_a_decimal_address` fixture
  corrected.** It was red on the tree because its `deco` returned `99`, which
  the (a) refusal correctly rejects. Its fixture is now a pass-through
  decorator, so `step` is a function value on both engines.
- Still NOT covered: an imported decorator, and a factory whose argument is
  returned (`@wrap(helper)` with `return g`), which is exempt and so unrefused,
  not proven correct.
- `test_gimple.py`: 411 passed, 0 failed (`memslot --gb 8`); the two new
  shape tests fail against the previous HEAD `module_gen.py`.

Defects 1-3 and the rebinding model are unchanged; the next step is still
step (b) of the plan below.

## Status (2026-10-29 — partial fix (a) landed: the scalar-decorator refusal; defects 1-3 still open)

Landed the refusal from the plan below, step (a). It changes behaviour: a
scalar-returning same-module decorator on a top-level `def` now stops the
compile with `decorator 'deco' on 'step' returns int64_t (not callable)`
instead of building a binary that silently calls the undecorated function.

- Code: `mojo/backend_gimple/module_gen.py` `_gmi_refuse_scalar_decorator_rebind`,
  called from `gen_module_impl` beside the nested-class refusal. It inspects
  only a bare-name decorator that names a top-level `def` in the same module,
  and only when that decorator's inferred return is `int64_t`/`double`/
  `_Bool`/`char *`. A decorator that returns its own parameter (`return f`)
  is exempt: the undecorated answer is correct for it. The exemption is
  needed because an untyped parameter infers as `int64_t`.
- Tests: `test_gimple.py` `scalar_decorator_rebind_is_refused` (raises,
  message `returns int64_t (not callable)`) and
  `pass_through_decorator_on_a_def_still_compiles`. Both were run in
  isolation and pass. The full `test_gimple.py` run used to abort before
  reaching them (a refusal on `fire_compiler.py`'s `assert_raises` helper); that
  is fixed, and the full run now reaches and passes both.
- NOT covered by the refusal, so still silently wrong: a factory decorator
  (`@deco(x)`), a decorator imported from another module, and a decorator
  whose scalar return is hidden behind a nested call.

Defects 1-3 and the rebinding model are unchanged. The next step is still
step (b) of the plan below. Doc kept open.

## Status (2026-10-29 — planning round: re-measured, sites located, guide for the next round; no code change)

**Re-measured on this tree**, from the minimal repro (`.tmp`-scratch copy of the
doc's own `deco(f) -> 99`, `@deco def step`, `print(step)` / `print(step(7))`):

| | result |
|---|---|
| CPython 3.14.7 (doc) | `99`, then `TypeError: 'int' object is not callable` |
| `python3 fire.py run` | `99`, then `Error: 'int' object is not callable`, exit 1 — **matches CPython; interpreter half stays fixed** |
| `gimple_codegen.compile_to_gimple` (C emitted, not linked this round) | `print(step)` → `_t2 = (void *)_funcptr_step_9f63a2;` → `mojo_sprintf_ptr(...)` — **defect 2 stays fixed**. `print(step(7))` → `_t5 = step_9f63a2 (_t6);` where `_t6 = (int64_t)7` — **defect 3 is still there**: the call resolves the bare name to the UNDECORATED C symbol `step_9f63a2`, and `deco_9f63a2` is never called. |

Defect 3's emitted call is the bug. Its runtime answer (`1` where CPython
raises) was measured on 2026-10-02 and was not re-linked this round, so
treat that number as inherited and re-check it when the fix lands.

**Where the three defects live (the sites a next round edits, all measured):**

- Decorator is stored and never applied on the GIMPLE path. Only
  `staticmethod`/`classmethod`/`export`/`gpu`-family names are read by name
  anywhere: `mojo/backend_gimple/module_gen.py:7020` (`'export'`),
  `:7154-7156` (`'staticmethod'`/`'classmethod'`), `device_select.py:183-213`
  (`_decorator_names`, the one place a call-shaped decorator is normalised).
  Nothing turns `FunctionDef.decorators` into a rebinding.
- Module-scope value read: `mojo/backend_gimple/emit_exprs.py:454`
  `_lower_IdentExpr`. Its function-value arms are the BUILTIN_VALUE_MAP
  branch (~`:575-584`, which sets `_func_value_names`, i.e. defect 2's fix),
  then `_callable_value_symbol` (~`:612-628`), then `bare_global_read_plan`
  (~`:637`) for `_<mod>_globals.<name>`. A module-scope decorated name would
  go through the last of these, so the rebinding can reuse the global-field
  path rather than a new one.
- Bare-name call resolution: `mojo/backend_gimple/emit_funcs.py:2592`
  `_func_csym` (mangled-key mirror, `_effective_param_types`,
  `_overload_suffix`), used at the definition (`emit_funcs.py:625`) and at
  the call sites `cpp_core.py:4034` and `emit_calls.py:7883-7920`. The
  address-of arm is `cpp_core.py:1838`. **Every one of these resolves a bare
  name to a function symbol without asking whether the name was rebound.**

**Decisions the next round needs (with the readings):**

1. *Rebinding model.* Recommended: a decorated module-level `def f` keeps its
   C symbol `f_<csym>` as the undecorated body, and additionally emits a
   module-scope variable `f` (a `_<mod>_globals` field, as for any module
   `var`) initialised to `deco(f)` in source order. Call sites for a name
   that is a rebound global read the variable and call through it
   (`mojo_fnptr_call_N` / `MojoBoundMethod *` already exist for a
   callable value). Alternative: rewrite the call site to `deco`'s result
   at compile time. Rejected — it cannot represent a decorator that returns a
   different callable on each call, and it duplicates the `_lower_IdentExpr`
   closure-value path.
2. *Defect 1 — the decorator's own parameter.* Currently typed `int64_t`
   because the decoration is never a call site. Once step 1 emits
   `deco(f)` as a call, the scalar observation pass sees a `FunctionDef` as
   argument. **Measure before choosing:** the ordering hazard in
   `CODEGEN_string_arg_type_lost_across_forwarding_hop.md` says the
   observation pass runs before parameter refinement, so the decorator's
   parameter may need the function-value type passed in explicitly, not
   inferred.
3. *Refusal (the cheap, independent partial fix).* `step` rebound to a
   decoration whose inferred return is a scalar (`int64_t`/`char *`/`double`
   …), then CALLED with `step(...)`, is currently silently wrong. Refusing
   it at compile time is a real behaviour change and is safe on its own. It is
   NOT a refusal of decorated `def`s in general (the 426-definition stdlib
   measurement above rules that out). It can land BEFORE step 1, as a partial
   fix: its test is a compile-refusal assertion in `test_gimple.py`.

**Implementation plan (ordering, for the next round):**

- (a) *Partial fix, lands first:* the refusal in step 3 above. Add the check
  where the module-scope `FunctionDef` is registered (`module_gen.py`, near
  the `_local_def_nodes` / `_direct_toplevel_names` build at `:3461`/`:3529`)
  and raise the existing "unsupported" compile error. Test:
  `test_gimple.py::decorated_scalar_rebind_called_is_refused` — compile the
  repro, assert the error. Fails before, passes after.
- (b) *Rebinding model:* emit the module-scope field and its
  source-order `deco(f)` initialisation (`module_gen.py`, module-global
  init emission); make `_func_csym`'s callers check a `rebound_globals` set
  first (`emit_funcs.py:2592`). Test: `test_gimple.py` shape test that the
  call site of `step` reads `_<mod>_globals.step` (NOT `step_<csym>`), plus
  the interp oracle `interporacle` case already registered by the interpreter
  half — the two must agree on `99`/`TypeError`.
- (c) *Defect 1:* type the decorator's parameter from the new call site, per
  decision 2. Test: the repro's `deco` parameter is not `int64_t` in the
  emitted C for a decorator that takes a function.
- (d) *Runtime check:* link and run the repro through `driver.compile_program`
  (not the single-TU path) to confirm `TypeError`-equivalent output, since
  CLAUDE.md says link-mode-only module bugs are invisible to the inline path.

**The gate for this change is `make gate`, once, by the integrator** — the
change touches `module_gen.py` and `emit_funcs.py`, which are on the
compiled-path list in CLAUDE.md.

Not landed this round. No code change; the planning round's output is this
entry. The doc stays open.

## Status (2026-10-02, later — defect 2 is FIXED; the feature is not, and the remaining call-site defect is unchanged)

Defect 2 below — the `sprintf("%d", (void *)ptr)` — is closed, and the entry
that called it "independent of the feature and fixable on its own" was right.

```
                       before        after
CPython 3.14.7      <function step at 0x7f...>   (unchanged)
fire.py run         99                             (unchanged — interpreter half)
compiled + run      74387272         <function step at 0x10469cf48>
```

A function VALUE lowers to a `void *` (the pre-declared `_funcptr_<csym>`
static, because GIMPLE forbids `&func_name` as an rvalue). Nothing downstream
knew it was a function rather than a pointer, so `print` reached its generic
`sprintf(fmt, val)` arm and `TypeLattice.printf_fmt('void *')` answered `%d`
— it has no format for a pointer and its default is the integer one.
Formatting a 64-bit pointer with `%d` is undefined behaviour; on this target
it prints the low half in decimal. **The address was never the wrong answer**
(CPython prints one too), so the `%d` was the whole bug and the NAME was the
missing half.

Fixed at both sites that spell one: both `_lower_IdentExpr` function-value
branches now record the value name in `gen._func_value_names`, and `print`'s
dispatch has an arm for it. The format string stays a literal and the `%p`
conversion happens in a new runtime helper `mojo_sprintf_ptr` — because
`printf_fmt` cannot know a value is a pointer from its C type alone, which is
exactly why it was the wrong place for this. Regression:
`test_gimple.py::print_of_a_function_value_is_not_a_decimal_address`, which
compares the SHAPE rather than the value (the address differs per build and
per platform) and fails with the fix reverted.

**Deliberately NOT changed**, so the next reader does not read it as an
oversight: `printf_fmt`'s `%d` default for every OTHER unlisted pointer type.
Widening it to `%p` would alter the printed form of every struct pointer in
the tree on no evidence that any of them wants it. That is a separate
measurement and a separate decision.

### What is still open, unchanged

**Defect 3 — the actual bug — is untouched.** The call site still resolves the
bare name to the C symbol, so `step(7)` still answers `1` where CPython
raises `TypeError: 'int' object is not callable`. It needs the module-level
rebinding data model the 2026-10-02 entry lays out in three steps, and its
own measurement stands: refusing decorated `def`s wholesale is ruled out
because the stdlib decorates 426 definitions with names outside the
compile-time-only set, 11 of them on free functions. Defect 1 (the decorator's
own parameter typed `int64_t`, because the decoration is its only call site
and is never emitted) is likewise unchanged and is a prerequisite of step 2.

**And the three-step plan in the entry below is still the plan**, with defect 2
now off the list: (1) the module-level rebinding data model, (2) the
decorator's parameter typed from that new call site, (3) a refusal for the
one unrepresentable case. Step 3 remains cheap and safe to land on its own
precisely because that case is silently wrong today.

**One thing the plan does not yet account for**, found while fixing defect 2:
`print` now formats a function value correctly, but the CLOSURE form did not
compile at all on this tree, so the arm was not exercised for the
`MojoBoundMethod *` spelling a capturing closure lowers to. That is FIXED
(`work/bugs6-1`, 2026-10-04): `_root_globals` now mints the field and the call
reads it, so a module-scope `f = outer(3)` compiles and `f(10)` answers `13` —
pinned by `test_gimple_runner.py`'s
`gimple_module_scope_closure_value_is_declared_and_callable`, which calls it
twice so the field cannot be right by accident on the first read.

What did NOT come with it is `print(f)`'s text: a capturing closure read as a
value still has no repr and prints its address decimal where CPython prints
`<function outer.<locals>.inner at 0x...>`, so this doc's first paragraph is
still true for the closure spelling. That is filed, with its own next step, as
the now-fixed closure-value repr bug (deleted with its fix). The wider gap the
same measurement turned up — a module-scope global bound to a
container-returning CALL is declared `int64_t` and does not compile — is
`bugs/CODEGEN_a_module_scope_global_bound_to_a_container_returning_call_is_a_box.md`,
and the two are separate: one is a repr, the other is a declaration.

## Status (2026-10-02 — re-measured: the compiled half is STILL wrong, and the two candidate fixes are now MEASURED, one of them ruled out)

Same verdict, from the doc's own minimal repro compiled through
`compile_to_gimple` + `gcc -fgimple` and run (`deco(f) -> 99`, `@deco def
step`, `print(step)` / `print(step(7))`). The doc's 2026-09-30 entry read the
compiled address as `35260224` and this tree prints `7901000`; the value is an
address and moves per build, which is itself the answer to whether it is a
correct one:

| | result |
|---|---|
| CPython 3.14.7 | `99`, then `TypeError: 'int' object is not callable` |
| `fire.py run` | `99`, then the same `TypeError` — the interpreter half is fixed |
| compiled + run | `7901000`, then `1` — the UNDECORATED result |

**The generated C, because it splits this into three separable defects and two
of them are prerequisites rather than the feature:**

```c
int64_t deco_9f63a2 (int64_t f) { ... return 99LL; }   /* (1) */
static void * _funcptr_step_9f63a2 = (void *)step_9f63a2;
  _t1 = _funcptr_step_9f63a2;
  sprintf (_t2, "%d", _t1);                              /* (2) */
  _t6 = step_9f63a2 (_t7);                               /* (3) */
```

1. **The decorator's own parameter is `int64_t`.** The decoration is the only
   call site of `deco` and it is never emitted, so the call-site observation
   that types an unannotated parameter has nothing to observe and the default
   stands. This is the ordering hazard the 2026-10-01 entry below already names
   (`CODEGEN_string_arg_type_lost_across_forwarding_hop.md`): the free-function
   scalar-observation pass runs BEFORE any body's parameters are refined, so
   whatever makes the decoration visible has to survive that.
2. **`sprintf("%d", (void *)ptr)`.** `print(step)` reads the function value as
   a `void *` and formats it with `%d`, which on a 64-bit target is undefined
   behaviour and is where the decimal address comes from. CPython prints
   `<function step at 0x…>`, so the *address* is not the wrong answer — the
   `%d` is. This one is independent of the feature and fixable on its own.
3. **The call site resolves the bare name to the C symbol**, so `step(7)` runs
   the undecorated body. This is the bug.

**The obvious cheap fix — refuse a decorated `def` at compile time — is
RULED OUT by measurement, and this is the useful part of this entry.** The
interpreter's compile-time-only decorator name set has ten names; the stdlib
(249 `.mojo` modules under `build_stdlib_dylib.STDLIB_PATH`) decorates
**426** definitions with names outside it — `doc_hidden`, `stable`,
`deprecated`, `explicit_destroy`, `unavailable`, `implicit`,
`__nonmaterializable`, `__allow_legacy_custom_self_type`,
`__unsafe_nested_origins_read_only`, `lldb_formatter_wrapping_type`,
`__annotation` — and 11 of those are on FREE functions. Refusing them would drop real
stdlib modules, which is exactly the `stdlib-dylib` `skip` regression
CLAUDE.md makes a judgement call about. So the fix has to be *application*, and
it has to decide per NAME whether a decorator is a declaration annotation (which
the stdlib shows is most of them, and which the Mojo front end strips) or a real
callable — a bigger question than "apply the decorator".

**So the first commit of the real fix is three things, in this order:**

1. a module-level REBINDING data model: `@deco def step` becomes a module-scope
   variable `step` holding the decoration's value, the same
   `_lower_IdentExpr` closure-value branch (`emit_exprs.py:764`) that already
   handles `return add` for a LOCAL, lifted to module scope;
2. the decorator's parameter typed from that new call site (defect 1 above),
   which is a chicken-and-egg with the observation pass and is the delicate
   part;
3. a compile-time refusal for the one case that cannot be represented —
   `step` bound to a decoration whose inferred return type is a scalar, then
   CALLED (`step(7)` where CPython raises `TypeError`). Cheap, and safe to land
   on its own precisely because it is a case that is silently wrong today; it
   is NOT the same as refusing decorated `def`s, which is what the 426 above
   rules out.

Defect 2 is independent of all three and can be landed whenever.

Not attempted this session, and not attempted by any of the three commits above:
the codegen half is feature-sized, `mojo/backend_gimple/*` is mid-merge under
other claims, and a mistake in it is a silent wrong value in the compiler's own
compiled path. The interpreter half remains fixed; the compiled half remains
the work.

Doc kept open.

## Status (2026-10-01 — re-measured, the compiled half is STILL exactly as the entry below describes; not attempted)

Confirmed unchanged on this tree, from the doc's own minimal repro
(`deco(f) -> 99`, `@deco def step`, then `print(step)` / `print(step(7))`):

| | result |
|---|---|
| CPython | `99`, then `TypeError: 'int' object is not callable` |
| `fire.py run` | `99`, then the same `TypeError` — the interpreter half really is fixed |
| `fire.py build` + run | the UNDECORATED result — `8` for `step(7)` |

**Not attempted this session, and the entry below's analysis of why still
stands.** This is feature-sized (a decorated `def` is a module-level
REBINDING, and every name-keyed table — `_func_csym`'s mangled-key
mirror, `_effective_param_types`, `_overload_suffix` — is keyed on the
bare name), and it is a SILENT wrong answer rather than a refusal.

**One thing the entry below's "Next bounded action" does not mention, and
that its own proposed fix has to contend with.** It proposes lifting
`_lower_IdentExpr`'s closure-value branch to module scope so a decorated
function becomes a module-level variable. Measuring the neighbouring
machinery for other bugs this session turned up a constraint worth
recording before anyone attempts it:

- The free-function scalar-observation pass runs BEFORE any function's
  parameters are refined, so a parameter forwarded straight through a hop
  is recorded as no-evidence and never re-examined — measured, with the
  evidence, in `CODEGEN_string_arg_type_lost_across_forwarding_hop.md`.
  A decorated `def` is exactly a module-level rebinding feeding calls that
  resolve through those same tables, so whatever makes the decoration
  visible has to survive that ordering.
- `_func_csym` currently answers only for names it can resolve to a
  module-level DEFINITION or an import. A name bound to a VARIABLE is not
  something it can answer for at all — the same "the bare-name tables
  cannot see it" shape, measured in
  the bare-`import` module-qualified call, fixed 2026-10-02 (the member
  registration is `funcs_shared.register_imported_symbol`), which is
  the failure a decorated name runs into.

Neither is part of this bug; both are prerequisites or neighbouring
hazards for whatever makes the decoration visible.

Doc kept open. The interpreter half remains fixed; the compiled half
remains the work.

## Status (2026-09-30 — compiled half still OPEN; re-measured, not attempted)

Re-measured on this tree, so the numbers below are current rather than
inherited: the doc's minimal repro (`deco(f) -> 99`, `@deco def step`, then
`print(step)` / `print(step(7))`) gives CPython `99` then
`TypeError: 'int' object is not callable`, `fire.py run` `99` then the same
TypeError (the interpreter half really is fixed), and `fire.py --jit`
`35260224` then `1`, exit 0 — the function's own code address printed as a
scalar, then the UNDECORATED result. Unchanged, and still a feature-sized
piece of work rather than a small fix; not attempted this session. See
"Next bounded action" for what the current tree says the first step is.

One correction to the 2026-09-27 note below, because it would send the next
session to the wrong place: the free-function calling convention is no
longer name-keyed in quite the way that entry describes. Import
resolution now answers "which module DEFINES this symbol" by following
re-export hops (`_find_symbol_home_module` in `mojo/middle/funcs_shared.py`,
used by `_register_sym`, `_gen_stmt_FromImportStmt`, `_collect_body_
import_bindings` and the extern preamble), so the qualifier half of a
mangled symbol is derived from the defining module rather than from the
import statement's own module string. That does NOT make decorated
functions easier — a decorated `def` is a module-level REBINDING, and
nothing in this area rebinds a name that the overload/qualifier machinery
(`_func_csym`'s mangled-key mirror, `_effective_param_types`,
`_overload_suffix`) reads — but the obstacle to clear first is smaller than
"make five name-keyed tables agree", and the import half of that work is
already done and regression-tested
(`test_gimple.py::test_aliased_and_reexported_imports_resolve_to_the_defining_module`).

## Status (2026-09-27, later — the INTERPRETER half is FIXED; the compiled half is untouched and still open)

Landed, each piece with a regression that fails at `435cc71`:

1. **The parser no longer discards a decorator's argument list.**
   `fire_compiler.py`'s decorator block skipped the tokens between the
   parentheses, so `@deco` and `@deco(x)` produced the *identical* AST node
   and the arguments were unrecoverable — which is part of why a decorator
   could be dropped without anything noticing. The call is now parsed by a
   new shared `_parse_paren_args` (extracted from `_parse_expr`'s postfix
   loop, so a decorator's arguments follow exactly the same rules as any
   other call's, including `*args`/`**kwargs` and generator-comprehension
   arguments) and stored as a real `CallExpr` **in place of** the bare name.
   A bare `@deco` still stores the plain string, so every existing
   `'staticmethod' in decorators` / `d != 'parameter'` reader across the tree
   is unaffected. The `dumps` path stopped losing the arguments as a side
   effect.
2. **The interpreter applies them.**
   `myinterpreter.py`'s `execute_FunctionDef` calls a new
   `_apply_function_decorators`, which is `f = deco(f)` applied **bottom-up**
   (Python's order: `@a` over `@b` means `a(b(f))`), through `self.invoke`
   so a Mojo-defined decorator gets the interpreter threaded in exactly as
   `eval_CallExpr` does. A parameterised `@deco(x, k=1)` is **two**
   evaluations — the `CallExpr` produces the decorator, and that is then
   called with `f`; collapsing them into one call is what made the factory
   idiom bind its first parameter to the function instead of to `x`.
   `execute_StructDef` applies the same rule to methods, storing the result
   back in the class's `methods` dict.
3. **A named set of compile-time-only decorators is excluded**, because they
   select a calling convention or a lowering mode and there is no user-level
   function to call: `staticmethod`, `classmethod`, `property`, `export`,
   `parameter`, `fieldwise_init`, `always_inline`, `inline`, `unroll`,
   `comptime`, the trait-conformance names, and
   `__allow_legacy_any_origin_fields`. Every one of them is read by name
   elsewhere in the tree, so this is a name set, not a second mechanism.
4. **Regression: `test_interp_oracle.py`, newly registered as `interporacle`.**
   The oracle had NO test of its own — every parity test in the repo compares
   the two *engines* with each other, which structurally cannot catch a bug
   they share, and a shared wrong answer is exactly what an interpreter bug
   produces. That file runs each program through both `python3 fire.py run`
   and `python3` on the *same* text and requires identical stdout and exit
   code. Three cases are decorator cases (bare, stacked, parameterised, on a
   method, on a `@staticmethod` method) plus the compile-time-name case.

Verified against CPython on the same source:

| | CPython | `fire.py run` (before) | `fire.py run` (after) |
|---|---|---|---|
| `@wrap def dbl` | `42` | `21` | `42` |
| `@tag("A") def one` | `A:1` | `1` | `A:1` |
| `@tag("B") @wrap def two` | `B:10` | `5` | `B:10` |

### What is still open: the compiled half, unchanged and now MEASURABLE

The compiled paths still drop a decorator, exactly as before. That is now a
*visible* interp/jit diff rather than a shared silent wrong answer, which is
the point of the interpreter half:

```
@wrap on a free function   : cpython 42,  interp 42,  jit 21
@sdeco on a method         : cpython 2,   interp 2,   jit 2   (and @sdeco
                             on a @staticmethod method: cpython 103, jit 3)
```

The work is unchanged from the section below and is not smaller for it: a
free function is a module-level C symbol resolved by bare name
(`_func_csym`), and a rebound name is a *variable* holding a function pointer
or a `MojoBoundMethod *`, so every call site that resolves the bare name has
to learn to read the variable instead. The overload/qualifier machinery
(`_effective_param_types`, `_overload_suffix`, `_func_csym`'s mangled-key
mirror) is all keyed on the bare name. A decorated `async def` / generator
additionally has its calling convention fixed in `_async_api` /
`_generator_api` at *registration* time, before any module-level statement
runs, so decoration would have to invalidate that registration and
re-register under the new value.

**Next bounded action:** the GIMPLE path only, and only for the free-function
case — lift `_lower_IdentExpr`'s existing closure-value branch (already
handles `return add`) to module scope, so a decorated function is a
module-level variable holding the decorated value and a call site that
finds one reads it. Register the case in `test_runtime_diff.py` at the same
time, so the fix is measured as an interp/jit agreement rather than asserted.

## Status (2026-09-27 — OPEN, reproduced fresh on both paths, no code change)

`FunctionDef.decorators` is parsed (`fire_compiler.py`'s `_parse_funcdef`
stores it, and the `dumps`/AST-text path re-emits it) and then **never
read** by either executor. The only consumer in the whole tree is
`myinterpreter.py:3362`, and it looks for exactly one name:

```python
if 'staticmethod' in (getattr(m, 'decorators', None) or []):
```

— a `@staticmethod` on a *method*, which the interpreter needs in order to
bind it. Struct-level decorators have their own handling
(`fire_compiler.py:3968`'s `fieldwise_init` / `_OWN_DECS`). A bare
`@deco` on a free function is stored and dropped.

### Minimal repro (both paths wrong, identically)

```python
def deco(f):
    return 99

@deco
def step(context):
    return 1

def main(n):
    print(step)
    print(step(7))
```

| | CPython | `fire.py run` | compiled |
|---|---|---|---|
| `print(step)` | `99` | `<MojoFunction object …>` | `9637660` |
| `print(step(7))` | `TypeError: 'int' object is not callable` | `1` | `1` |

`step` is the *undecorated* function on both paths: the decoration is
inert. The compiled `9637660` is the function's own code address printed
as a scalar, which is the same class of "a real pointer laundered
through `int64_t`" that the rest of this area keeps producing.

## Why it matters more than "a missing feature"

It is **silently** wrong, not a refusal. A decorated function compiles,
links, runs, and returns its own undecorated result. `subdir` in
`Tools/wasm/wasi/__main__.py` is exactly this shape, so that program's
compiled `@subdir(...)`-decorated build steps run with `working_dir`
never changed and `contextlib.chdir` never entered — the file builds
cleanly and its output is not what the source says.

The interpreter half matters just as much: `fire.py run` is the
documented oracle for "the compiled path is wrong", so a program that
relies on a decorator silently gets the same wrong answer from both, and
`test_runtime_diff.py`'s whole premise (the two engines must agree) cannot
catch it.

## Why the fix is feature-sized, and what it would take

Applying `@deco` to `def f` is a module-level rebinding: `f = deco(f)`
after the definition, in source order, with the decorator expression
(`@deco(x)`) evaluated at that point. Each half is small; the cost is in
the free-function calling convention, which is currently name-keyed
throughout:

- **Interpreter.** Smallest piece of this work. The decorated `def` must
  register the resulting value under the function's own name in the
  module scope instead of (or after) installing the raw `MojoFunction`.
  `nonlocal`'s implementation already establishes the pattern — a
  declaration recorded on the running scope, consulted by the name
  lookup (`Scope.nonlocals`).
- **Compiled, GIMPLE path.** A free function is a module-level C symbol
  resolved by bare name (`_func_csym`); a rebound name is a *variable*
  holding a function pointer or a `MojoBoundMethod *`, and every call
  site that resolves the bare name has to learn to read the variable
  instead. That is the same "closure value as a first-class name" work
  `_lower_IdentExpr`'s closure-value branch already does for a *local*
  (`return add`), lifted to module scope for every decorated function.
  The overload/qualifier machinery (`_effective_param_types`,
  `_overload_suffix`, `_func_csym`'s mangled-key mirror) is all keyed on
  the bare name and would each need the same treatment.
- **Compiled, C++20-coroutine path.** A decorated `async def` /
  generator additionally has its call convention fixed in `_async_api` /
  `_generator_api` at *registration* time, before any module-level
  statement runs. Decoration would have to invalidate that registration
  and re-register under the new value.

## Next bounded action

Land the **interpreter** half first, on its own, with an
interpreter-vs-CPython regression: it is self-contained, it makes the
oracle correct (so every later compiled-path decorator bug becomes
*visible* as an interp/jit diff instead of agreeing on the wrong answer),
and it is the prerequisite for trusting any compiled-path decorator work.
The compiled half is a separate piece of the same project and should not
be bundled with it.

## Regression coverage

None yet — a test that asserts today's behaviour would lock the bug in.
`test_nonlocal.py` documents the interaction instead: its three-closure
cases are the `subdir`/`decorator`/`wrapper` chain, and they are driven
by a DIRECT call precisely because the `@decorator` spelling cannot work
yet.
