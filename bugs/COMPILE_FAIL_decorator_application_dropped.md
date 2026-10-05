# CODEGEN/INTERP: a plain `@decorator` on a `def` is never applied, on either execution path

Found 2026-09-27 while closing
`COMPILE_FAIL_Tools_wasm_wasi___main__.md`. Not a compile failure — the
opposite kind of problem, and the reason that file needed a separate
correctness caveat even after it started building.

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
`MojoBoundMethod *` spelling a capturing closure lowers to. That compile
failure is fixed (a module-scope `f = outer(3)` now mints its globals-struct
field, builds and answers 13; pinned by `test_gimple_runner.py`'s
`gimple_module_scope_closure_value_is_declared`). What is still missing is the
`print` half for that spelling — a capturing closure read as a value has no
repr and prints its address decimal, which is what this plan's step 1 would
have to cover as well; see
`bugs/CODEGEN_closure_value_repr_prints_its_address.md`.

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
