# CODEGEN: a callable-valued parameter called in an ordinary generator returned garbage, silently

**State: FIXED 2026-10-02 for the value the call produces; one adjacent,
independent defect found while fixing it and filed separately.** The doc's own
two-part next step is done, in the order it named, with the side-table option
(its second) rather than a new callable category in `_param_ctype`.

## What is fixed

The repro, measured before and after on this tree:

```python
def upper(s):
    return s.upper()

def apply_to(items, _f=upper):
    for it in _f(items):
        yield it

def go():
    for v in apply_to('ab'):
        print(v)

go()
```

| | CPython | compiled before | compiled after |
|---|---|---|---|
| `go()` | `A` then `B` | **nothing**, exit 0 | `A` then `B` |

And the shape that isolates the value, in an ordinary function:

```python
def apply_to(items, _f=upper):
    r = _f(items)
    print(r)          # CPython AB;  compiled 4337064208 before
    print(len(r))      # CPython 2;    compiled 0 before
    for ch in r: ...  # CPython A, B; compiled nothing before
```

`AB / 2 / A / B` on all three now. Regressions:
`test_gimple_runner.py`'s `gimple_callable_param_result_keeps_its_type` and
`test_gimple_generator_runner.py`'s
`generator_callable_param_result_keeps_its_type`.

## What the generated C was doing

The doc's original analysis holds exactly. The parameter is typed `int64_t`
(there is no callable category in `_param_ctype`, which both emitters share),
and `_lower_call`'s indirect-call branch boxes the callee's real value —
here a `char *` — into an `int64_t` with nothing recording that it was a
pointer. Every consumer then had no kind to dispatch on: `print` formatted
the integer, `len` was 0, and the `for` loop the call fed iterated a garbage
object.

The A3 stack-switch twist is not in the original write-up and is what made the
generator half of this need its own plumbing: `_lower_one` MOVES every source
parameter into a `var p = __mojo_gen_arg(...)` local, so the body function
the ordinary codegen emits carries no `param_defaults` at all.

## The three changes, which are the doc's "order matters" made concrete

**1. Type the parameter — as side-table metadata, not as a ctype.** The doc
offered two routes and rejected the first: "the change cannot live there
unconditionally — the ordinary path would then put a `std::function` in a
plain C signature whose call sites would all have to construct one". The
`void *`-plus-a-registered-kind option was not needed either, because the
codebase already has this exact shape one table over:
`gen._callable_param_gen_api` (`{param: generator api}`, per function, reset
in `_reset_func`) for a parameter whose default names a compiled generator.

`gen._callable_param_ret_types` (`{param: the callee's return C type}`) is its
ordinary-function twin, and `calls_shared._callable_param_ret_types` is its
reader: a bare-name default only, so the answer is the DEFINING function's
own `func_return_types` entry and nothing is guessed. `void` is excluded — a
void callee's box is not a value.

`_lower_fnptr_call_value` consults it at the point where it already consults
`_callable_ret_types`, because the runtime helper's own return type is what
every consumer below dispatches on. `double` and every pointer kind are cast
there; `int64_t` is left alone.

**2. Call through it — the `_d`-twin treatment, keyed on the callee's
declared return type.** That is what the consult above IS: the existing
`ret_type == 'double'` arm already had the `_d`-twin shape, and the new one
returns the declared pointer type directly instead of the box.

**3. Carry it into a coroutine body.** `_callable_param_ret_types` reads
`fn_node.param_defaults`, which a lowered `__mgco_<g>_body` no longer has.
The body therefore carries the FACT —
`body_fd._mojo_coro_callable_param_fns` (`{param: the function name}`),
attached by `coro._mark_coro_callable_param_fns` — and `gen_func` resolves
it. Names, not return types, and that is not a stylistic choice:
`coro.register` runs as an AST PRE-PASS, before `gen_module_impl` has
registered any module-level function's `func_return_types` entry, so a return
type looked up there is not there yet. The doc's warning about
"a new side table whose writes happen while a function body is generated
needs a reset point" is honoured: `_callable_param_ret_types` is reset in
`_reset_func` alongside its generator twin, which is also what a lifted
closure's body runs.

`_mark_coro_param_elem_kinds` is the established idiom this follows, and its
docstring is what said it: "the evidence is available here and nowhere
downstream … the generator's own FunctionDef is GONE".

## Deliberately still unanswered

`_callable_param_ret_types` answers only for a default that is a BARE NAME.
A `lambda` default, a bound-method default, an imported default and a `None`
default are all absent, and an absent parameter is exactly today's behaviour
— i.e. the box. The reasons are already written down elsewhere and are not
this document's to re-litigate:

* a **lambda** default's return type lives in `_callable_ret_types`, keyed by
  the temp `_lower_LambdaExpr` mints when the value is MATERIALISED — and in
  a parameter default it is never materialised at this point, which is the
  same "create and consume in one lowering" problem
  `CODEGEN_closure_env_and_boxed_local_never_freed.md` OPEN 1 records. A
  shared answer means either materialising the default (a real allocation
  per call) or re-running the lambda's return inference, and the doc's own
  warning about a "SECOND implementation of what `_lower_LambdaExpr` does" —
  which CLAUDE.md's no-duplicates rule forbids — is exactly that;
* a **bound-method** default (`_f=m.truthy`) needs the receiver, which a
  parameter slot does not carry: the same split as
  `CODEGEN_callable_return_type_lost_at_more_hops.md`'s #3, and the fix there
  (`_actual_types` overlay for a global) does not transfer to a slot;
* an **imported** default is the padding-site question
  `CODEGEN_unresolved_imported_callable_default_null_pointer` is
  about, which the original write-up already names as a different bug.

## Two adjacent defects found while measuring, both filed or already claimed

**A generator that iterates a STRING parameter and yields its characters
produces nothing** — new, filed as
`bugs/CODEGEN_generator_iterating_a_string_parameter_yields_nothing.md`. It
is what the doc's own repro hits once the callable's value is right, it
reproduced on `bc17a62b` with every edit of this session reverted, and the
same program with the string in a LOCAL (`s = 'ab'.upper(); for it in s:`) is
already correct — so it is the generator's untyped parameter slots, not
iteration and not string yields.

**A `MojoList *` returned through a callable parameter gets its length right
but its elements wrong** — `def parts(s): return s.split(','); def use(s,
_f=parts): r = _f(s); for p in r:` gave `3` then three pointer decimals. The
value's KIND is now recovered (that is this fix) and the element type is the
remaining half, which is the container-element-type family rather than the
callable one. Not filed as its own doc yet because it is very likely the same
underlying gap as the string case above — a value crossing the callable
boundary whose ELEMENT type nothing recovered — and merging them is the
cheaper next step.

## The original report follows, unchanged, for its mechanism analysis
## and its rejected first option

`def f(x, _f=<a function>)` with `_f` **called** in a generator body compiles
clean, links, exits 0, and produces **nothing**.

```python
def upper(s):
    return s.upper()

def apply_to(items, _f=upper):
    for it in _f(items):
        yield it

def go():
    for v in apply_to('ab'):
        print(v)

go()
```

Distinct from `CODEGEN_unresolved_imported_callable_default_null_pointer`,
which is about the **padding** site (what symbol gets passed for a callable
default). This is about the **call** site inside a body the ordinary GIMPLE
generator path lowered, and it is reached by a default that this compile CAN
resolve — so that doc's fix does not cover it and its repro does not hit it.

## Why the generated C did nothing (the original analysis, re-measured)

`apply_to` is lowered by the ORDINARY GIMPLE generator path (A3,
`__mgco_apply_to_body`), not by the C++20-coroutine emitter. Its parameter
`_f` is typed `int64_t`, so:

```c
_t6 = mojo_fnptr_call_1 (_t5, items);   /* the call through _f */
_t7 = mojo_is_registered_dict (_t6);    /* ...then a runtime guess */
```

The value came back as the box, and the consumer asked a runtime registry
what it was. No diagnostic, exit 0, no output.

## Why the obvious fix is not the obvious fix (original, still true)

There are two generator emitters and they disagree about callable-valued
parameters: the **C++20 coroutine** path has a first-class callable type
(`_CPP_CALLABLE_CTYPE` / `_CPP_CALLABLE_CTYPE_1ARG`) that both stores and
calls a callable value; the **ordinary GIMPLE** path (`__mgco_*_body`) types
the same parameter `int64_t` via the shared `_param_ctype`, which has no
callable category, and `_lower_call`'s indirect-call branch then boxes the
callee's real return value into `int64_t` with nothing recording that it was a
pointer.

A lambda assigned to a LOCAL inside the body (`g = lambda: None`) works on
the ordinary path — `_callable_ret_types` and the `_funcptr_` machinery
cover it. Only the *parameter* spelling fell through, because nothing typed
the parameter. That is what this change fixes, with the same machinery the
local spelling already used.

## Note the interaction the original doc recorded, still open

`CODEGEN_next_generator_value_truncated_in_return_position`: that
one is the *same class* one level up — a value of a non-`int64_t` kind
travelling through an `int64_t` slot in a compiled generator context. Both
are "this scalar body model has no way to say what KIND of thing this is", in
different positions, and this change removes one position of it.

## Regression test (landed with the fix)

`test_gimple_runner.py`'s `gimple_callable_param_result_keeps_its_type` and
`test_gimple_generator_runner.py`'s
`generator_callable_param_result_keeps_its_type`. Both assert on the built
binary's **stdout against CPython**, not on a successful compile — this bug
compiles, links and exits 0. The control in each is the same value reached by
a direct call (`'ab'.upper()`), which was always right, so a fix that
broadened something else instead of narrowing the parameter path would turn
it red.
