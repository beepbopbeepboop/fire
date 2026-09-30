# CODEGEN/INTERP: a plain `@decorator` on a `def` is never applied, on either execution path

Found 2026-09-27 while closing
`COMPILE_FAIL_Tools_wasm_wasi___main__.md`. Not a compile failure — the
opposite kind of problem, and the reason that file needed a separate
correctness caveat even after it started building.

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
