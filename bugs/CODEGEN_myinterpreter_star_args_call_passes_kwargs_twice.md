# `f(a, b, *args, **kwargs)` lowers to a four-argument call of a three-parameter `__call__`, and five gimple conversions in `myinterpreter`'s own methods

## Status: OPEN. Found 2026-10-03 while working
## `bugs/hard/CODEGEN_dispatch_globals_list_forces_every_name_to_a_dict.md`;
## pre-existing, and reachable only through the rollback that bug removed.

## What I ran

    python3 tools/suite.py selfhost
    # FAIL  selfhost  (110s)  exit 1

and the generated-C error inventory described in that doc's "How it is measured
now" section, which reports 7 of the 11 remaining errors, all inside
`myinterpreter.py`'s own compiled bodies:

    fire_nl.ci:1118971:1: error: non-trivial conversion in 'var_decl'
        in myinterpreter_MojoFunction___init__
    fire_nl.ci:1119038:1: error: non-trivial conversion in 'component_ref'
        in myinterpreter_MojoFunction___call__
    fire_nl.ci:1123893:1: error: non-trivial conversion in 'component_ref'
        in myinterpreter__MojoBoundComptimeFunction___call__
    fire_nl.ci:1123923:1: error: non-trivial conversion in 'var_decl'
        in myinterpreter_MojoOverloadSet___init__
    fire_nl.ci:1124568:1: error: non-trivial conversion in 'component_ref'
        in myinterpreter_MojoOverloadSet___call__
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
a function rather than a line. Each is a method of one of `MojoFunction`,
`_MojoBoundComptimeFunction` or `MojoOverloadSet` — the three classes whose
`__call__`/`__init__` are written in exactly this `*args`/`**kwargs` shape — so
they are the same defect's other half: the star-args/keyword lowering of a
method on a struct whose fields carry a `MojoList *`/`MojoDict *`.

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

For the five conversion errors, the next diagnostic step is to get gcc to name a
line: compile the stripped `.ci` with `-fdiagnostics-show-caret` and one
function at a time (delete the other bodies), or reproduce one of the three
classes in a small `.mojo` file so the emitter's debug notes apply.