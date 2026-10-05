# FORMAL: a nested `def` handed back to its caller is refused as an UNPLACED NAME, not as a function read as a value

**Area:** FORMAL (both backends' shared name-placement check,
`formal/build.py::check_module_symbols`, reached through
`model.unresolved_name_refusal`).

**Not mine to fix in the round that found it** — the same round implemented the
generator-function, capturing-lambda, `nonlocal`-write and unapplied-decorator
refusals around it, and this one needs a decision about where a lifted
function's name is registered, which is the question
`bugs/FORMAL_function_value_calls_are_not_proved_to_be_calls.md` is already
about. Filed rather than papered over, and pinned by a case in
`test_formal_closures.py` so the gap is visible rather than assumed.

## What was run

    $ cat .tmp/probe/nd.mojo
    def make(n):
        def add(x):
            return x + n
        return add
    def main():
        a = make(10)
        r = a(5)
        print(r)
        return 0
    $ python3 fire.py build --formal --no-probe -o nd nd.mojo
    $ # same with --backend=x86_64

`python3 nd.mojo` answers `15`. CPython makes `make` return a closure object and
`a(5)` calls it.

## What was seen

Both backends, the same sentence:

    build: make: 'add' has no home: the module-level symbol table is empty for
    this unit, and the reading function declares no local or parameter by that
    spelling. This path places a name in a register or a spill slot allocated
    for THIS function, a receiver field's frame, or a module-level constant the
    build folded \u2014 and a name in none of them is refused rather than read out of
    whatever register the allocator left behind, which is how one program
    returned 10 on arm64 and 0 on x86-64 where the source says 5

## What was expected

`model.function_value_refusal`, which exists and is the right sentence:

> `'add' is a FUNCTION, and a function is not a value on this path: it has no
> representation here \u2014 a value is one 64-bit word and a function is a code
> address, so there is nothing for that word to hold, and passing one as an
> argument, storing one in a container, or returning one is refused rather than
> answered with a number that means nothing. \u2026 Call it directly, or move the
> work into a `def` and pass its results

Its own docstring records that a bare name read as a value used to reach
`unresolved_name_refusal` and was corrected \u2014 but only for the shape it was
written about, `call2(dbl, 5)` / `var g = dbl` with `dbl` a TOP-LEVEL function.
A **nested** `def` is not reached, and the reason is the order of two passes:

1. `_lift_lambdas` / `_flatten_closures` RENAME a nested `def` to its lifted
   symbol (`make_add`, from `mojo/middle/closures.py::closure_lifted_name`) and
   strip it from the enclosing body. `make`'s own `return add` is NOT rewritten,
   because `_rewrite_closures_in_expr` only rewrites a CALL to a closure name.
2. `check_module_symbols` then asks about the read of `add`. `add` is no longer
   any function's name \u2014 the function is `make_add` \u2014 so it is not in
   `_callee_defs(functions)`, not a parameter, not a local, and not a folded
   module constant. Every arm declines and the generic message stands.

So the construct is a **lifted** function read by its PRE-LIFT spelling, and no
table in the build holds that spelling. The two things that would fix it:

- publish each lifted nested `def`'s ORIGINAL name alongside its lifted symbol, as
  a name that resolves to a function (a third entry in the function-name table,
  next to `_callee_defs` and the module symbols), so the read is recognised as a
  function read and `function_value_refusal` answers it; or
- rewrite the pre-lift read to the lifted symbol AND mark it as a function read,
  which is the same fact from the other side and would additionally have to
  decide what `make_add` as a VALUE means (a code address in a word \u2014 which the
  emitters can materialize with `ADRP`+`ADD`, so it would build and print an
  address, which is why the refusal and not a materialization is the right answer
  until the callee side is settled).

## The next step

Read `bugs/FORMAL_function_value_calls_are_not_proved_to_be_calls.md` first: it
is the doc for the open question of whether a word holding a code address may be
called, and this refusal is the same question one step earlier. The
implementation question here is narrow and decidable \u2014 "is this read of a name
that a lift renamed?" \u2014 and the answer is a name table, not a proof.

## Test coverage

`test_formal_closures.py`'s two `a_nested_def_handed_back*` rows, pinned on both
backends with the needles `('add', "make")` and `('inner', "make")`. They PASS
today \u2014 as refusals naming the name and the enclosing function. The row fails
if the diagnostic regresses to something that names neither, and the comment
above each states that `unresolved_name_refusal` is the wrong sentence for it, so
whoever closes this sees the better one is already written.