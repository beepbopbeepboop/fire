# `f(a, b, *args, **kwargs)` lowers to a four-argument call of a three-parameter `__call__`

## Status: OPEN. Two of the eleven errors `selfhost` now reports. Found 2026-10-03 while working
## `bugs/hard/CODEGEN_dispatch_globals_list_forces_every_name_to_a_dict.md`;
## pre-existing, and reachable only through the rollback that bug removed.

## What I ran

    python3 tools/suite.py selfhost
    # FAIL  selfhost  (110s)  exit 1

and the generated-C error inventory described in that doc's "How it is measured
now" section. Of the eleven remaining errors, TWO are this one; the other nine
are four docs of their own.

    fire_nl.ci:1125288:10: error: too many arguments to function
        'myinterpreter_MojoFunction___call__'; expected 3, have 4
        in myinterpreter_BoundMethod___call__
    fire_nl.ci:1125476:10: error: too many arguments to function
        'myinterpreter_MojoFunction___call__'; expected 3, have 4
        in myinterpreter_BoundClassMethod___call__

## What I saw

The definition, at `fire_nl.ci:1118973`, has THREE parameters:

    int64_t __GIMPLE myinterpreter_MojoFunction___call__
        (MojoFunction * self, MojoList * args, MojoDict * kwargs)

matching `myinterpreter.py:212`:

    class MojoFunction:
        def __call__(self, *args, **kwargs):

The two bad call sites, in `BoundMethod.__call__` (`myinterpreter.py:1232`) and
`BoundClassMethod.__call__` (`myinterpreter.py:1266`), are both

    return f(self.interpreter, self.instance, *args, **kwargs)

and lower to FOUR arguments — the packed `*args` list, the `**kwargs` dict, and
the kwargs dict AGAIN as a trailing positional:

    _t29 = (MojoList *)_t22;              # the packed (interpreter, instance, *args)
    _t30 = (MojoDict *)_t24;              # the **kwargs dict
    _t28 = myinterpreter_MojoFunction___call__ (f, _t29, _t30, kwargs);

So a callee whose signature is `(self, *args, **kwargs)` receives its `**kwargs`
materialisation twice, and the duplicate is passed positionally rather than as
the keyword slot.

The five "non-trivial conversion" errors are all reported at a function's
closing `}` (gcc has no better position for a gimple-body error), so they name
a function rather than a line — but `bootstrap-stage2-cc` prints the construct
itself, and they are NOT part of this defect:

    int64_t
    struct MojoFunction *
    _t2 = func->_interp;

i.e. a struct FIELD whose declared type is the receiver's own struct pointer.
That is `bugs/CODEGEN_selfhost_class_field_type_comes_from_the_receiver.md`
(four errors of its own) and it is a different fix. What is left here is the
`too many arguments` pair.

## Exact next step

In `mojo/backend_gimple/emit_calls.py`'s call lowering, the argument list for
`f(a, b, *args, **kwargs)` must be exactly:

  * the positional prefix `a, b`,
  * one `MojoList *` for the materialised `*args` tail,
  * one `MojoDict *` for the materialised `**kwargs`,

and the callee's `(self, *args, **kwargs)` signature maps onto the last two.
The bug is that the `**kwargs` tail is BOTH packed into the keyword dict AND
emitted as a positional. Check the shape
`f(x, *args, **kwargs)` and `f(*args, **kwargs)` in that emitter, and check
whether the receiver is a METHOD (the three classes above) or a free function —
every reported instance is a method, which is the narrower thing to look at.

Reproduce the shape in a small `.mojo` file first — a two-field struct whose
`__call__` is `(self, *args, **kwargs)` and another whose method calls it as
`f(a, b, *args, **kwargs)` — so the emitter's own debug notes apply and the
four-argument emission is visible without a self-host build.