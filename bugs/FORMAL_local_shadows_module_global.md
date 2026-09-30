# A local that shadows a module global is resolved against one home, not two

## Status

**Open.** Not covered by any test, and deliberately so — see "What is asserted"
below. The case that would expose it is named in
`test_formal_globals.py` next to the control that *is* asserted, so the next
session does not have to rediscover it.

## The gap

    G = 5

    def bump():
        G = G + 1

CPython: the right-hand `G` resolves in **module** scope (nothing local is bound
yet), so it reads 5, computes 6, and binds 6 as a **local**. The module's `G` is
untouched.

This backend: the name is in the function's local set, so `_module_global`
returns `None` for it, so *both* the read and the store go to the local home —
the read has no value to give, because the local has never been initialised.
Measured: `main` printed the local as 11 where the interpreter says 6.

## Why it is one home and not two

`_module_global` (both backends) is asked "is this name a local of the function
being emitted?", and answers with the slot or `None`. That is correct for the
overwhelming majority and it is what makes the common cases right:

  * `global G; G = G + 1` — declared global, so not in the local set, so the
    slot. Correct, and it is the case the capability exists for.
  * `var G = 99` — a local, never read, so the store must not reach `__DATA`.
    Correct, and it is the regression the asserted control in
    `test_formal_globals.py` pins: before the gate was drawn at the local set
    rather than at "does the name have a slot", this store landed in `__DATA`
    and a function silently wrote a variable it had never declared.

What neither asks is the question Python's scoping actually asks, which is
*order-dependent*: a name is local from the point it is first **assigned**, and
module-scoped before that. So the read of a self-assigned name has no local home
yet and must come from the module.

## What is asserted, and what is not

Asserted (`assign_without_global_is_local`): `var G = 99` in a function that
does not read `G` leaves the module's value alone. That is the leak, and it is
regression-tested on both backends against the interpreter.

Not asserted: `G = G + 1` with no `global`, for the reason above — it needs two
homes for one word within one function, and until that is modelled the case
would either enshrine the wrong answer or sit red in the tree.

## Next step

Make the gate order-dependent rather than function-wide. The information is
already available: the emitter walks statements in order, so the question
"has this name been assigned in this function *yet*" is answerable at the point
of use if the emitter carries a set of names bound so far in the current
function, updated as assignments are emitted.

1. In each backend's `_emit_function`, seed `self._fn_bound_now = set()` from
   the parameters, and add to it as each assignment is emitted.
2. `_module_global(name)` returns the slot when `name` is in
   `_fn_bound_now` **only if** it is not one of the function's declared
   `global` names, and returns the slot otherwise.
3. The first thing to check is that the declared-global case still wins: the set
   has to be seeded from the locals and the declared globals have to be excluded
   from it, or `global G; G = G + 1` regresses to reading the module and
   writing a local.

The check that decides it is right is the case above run on both backends
against the interpreter, and then the whole of `test_formal_globals.py`, because
the two orders interact and the asserted control is the one most likely to
break while fixing this.
