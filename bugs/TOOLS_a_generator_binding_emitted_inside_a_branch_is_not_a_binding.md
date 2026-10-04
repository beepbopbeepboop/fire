# TOOLS_a_generator_binding_emitted_inside_a_branch_is_not_a_binding: `formal_fuzz` can emit a program whose name is still its declared `0`

**Area:** `tools/formal_fuzz.py` · **found by:** `--mix limits`, seed `sweepG`
8000-8009 · **filed 2026-10-03, FIXED for `limits` only**

## What I ran

    python3 tools/memslot.py --gb 8 --label limits -- \
        python3 tools/formal_fuzz.py --mix limits --seed sweepG \
            --seeds 8000-8009 -j 3 --work .tmp/fz4/limits

## What I saw

Two of ten programs came back `generator-error`, both with CPython's own
traceback as the detail:

    AttributeError: 'int' object has no attribute 'items'
    TypeError: 'int' object is not iterable

The second was my own arity bug (`sum(a, b)`), and it is fixed. The first is the
real one and it is pre-existing: every helper in `Gen` that needs a list, a dict
or a string binds it **at the statement's own indent**

    def limits_stmt(self, indent, kind):        # what I wrote
        if not self.dicts:
            self.limit_bind_dict(indent)        # emits `D = {10: 100}` HERE

so a binding emitted under `if (w3 <= w4):` is not a binding for any path that
does not take the branch. `self.dicts` remembers the name, so a `d.keys()` two
statements later is emitted against a name CPython still has bound to its
declared `0`. `strmeth_stmt` (`t = "ab"`), `list_stmt` (`L = [1, 2, 3]`) and
`dict_stmt` (`D = {…}`) all bind this way and can hit it the same way; `limits`
hit it on 1 program in 10 because it is the only mix that puts a statement
inside a `try` arm as well as inside `if`s.

## Why it matters more than it looks

A `generator-error` is `check_one`'s early return: the program is never built,
so **every construct in it goes unmeasured**, and the sweep's tally reports the
program as a failure of the generator rather than as coverage. A corpus can be
quiet for that reason and look clean.

## The fix, for `limits`

`declare(name, value)` puts the initialiser in the preamble, which is emitted
once at the top of `main` before any branch runs — so `limits`' three binders now
return the name and emit nothing. That is the whole fix.

## The exact next step

Apply the same change to `strmeth_stmt`, `list_stmt` and `dict_stmt`: each should
register its binding through `declare` with the container's real literal rather
than emitting it at `indent`. The property to assert afterwards is the one
`check_generator` cannot see today, because it only COMPILES: **every name the
body uses is assigned on every path**, which is a control-flow question rather
than a syntax one. The cheap version is to run each generated program under
CPython's `-W error` with `if`/`while`/`try` intact — i.e. `check_one`'s oracle
already does it, so the assertion is "a sweep of every mix reports zero
`generator-error`", and `check_run` already fails on that verdict. What is
missing is a check that a mix REACHES the failure: today a generator bug that
made every program an error would still be caught by `check_mix_builds`'s
`answers == 0` only if the mix has no other shape, which is a weaker signal than
it looks.
