# INTERP: a list/set/dict comprehension has no scope of its own, so its loop variable leaks into the enclosing function

**Area:** INTERP — `myinterpreter.py::eval_Comprehension`. Found on
`work/formal8-1` (2026-10-02) by a case in `test_formal_globals.py` that
compares two images against CPython, where the third engine (the interpreter) is
the one that is wrong.
**Status: OPEN, measured, NOT fixed here** — it is the reference-semantics file
that the self-host compiles, and a light worker must not change it without the
gate behind it. The fix is four lines and is written down.

## What I ran

```console
$ cat ci.py
G = 5

def f(rows):
    var out = [G for G in rows]
    return G + out[0]

def main(n):
    print(f([1, 2]))
    return 0

$ python3 fire.py run ci.py
3
$ python3 -c "…the same text, with `var out =`…"
6
```

CPython gives **6**: a comprehension is its own scope in Python 3, so its `for
… in` target binds nothing in the enclosing body, and the trailing `G` is still
the module's 5 — `5 + 1`.

Both formal images give 6 (arm64 and x86-64, measured through
`test_formal_globals.py`'s runner). **Only the interpreter is wrong, and it is
wrong in the direction that makes it useless as the reference**: a program whose
comprehension shadows a module global computes a different number under
`fire.py run` than it does compiled, with no diagnostic.

## The cause, and it is documented as a known gap

`myinterpreter.py::eval_Comprehension`'s docstring, in this file's own words:

> Real Python list/set/dict comprehensions get their own scope; this
> interpreter evaluates those in the *current* scope instead (same
> simplification execute_ForStmt already makes for a plain `for` loop) — their
> loop variables leak into the enclosing scope, a known minor fidelity gap.

So this is not a NEW defect, it is a documented one that this measurement puts a
number on. It is filed because "known" without a reproducer is the kind of note
that outlives its reason, and because `eval_Comprehension`'s neighbour
`_generator_expression` — twenty lines above — already does the right thing:

```python
scope = Scope(parent=self.scope)      # a real Python genexp's variables are
                                      # scoped to it, and names it READS stay
                                      # live through the parent chain
```

## The fix, and the two things to check before landing it

In `eval_Comprehension`'s non-generator branch, around the `run(expr.generators)`
call — save, push a child, restore. No new `return`, which matters because that
docstring's one-return discipline exists for the self-host's return-type
inference:

```python
saved = self.scope
self.scope = Scope(parent=self.scope)
try:
    run(expr.generators)
finally:
    self.scope = saved
```

Two things to check, and they are the reason this is filed rather than done:

1. **The outermost iterable is evaluated in the ENCLOSING scope.** With a child
   scope as parent it still resolves through the chain, so the common case is
   unchanged — but `[… for x in y for y in x]` (pathological, but the tree is
   full of comprehensions over names) evaluates `y` before `y` is bound, which is
   Python's rule, and the child scope makes that structural rather than
   accidental. Worth a case either way.
2. **Something may DEPEND on the leak.** This is the real risk, and it is why
   the change wants the gate rather than a light worker's test run: the
   interpreter evaluates this repository's OWN sources (`fire.py run`,
   `test_interp_oracle.py`, `test_runtime_diff.py`) and the whole tree's Mojo
   corpus goes through it. A comprehension whose loop variable is read after the
   comprehension would have been working by accident and would now raise
   `NameError`. That is the correct Python answer becoming a build failure
   somewhere, so the sweep to run is `tools/formal_sweep.py` (the integrator's
   job over every branch) and NOT a single narrow test.

The self-hosted `stage2`/`stage3` builds are the other reader: the interpreter is
compiled by `mojoc` in the self-host, so a change here wants a `make bootstrap`
behind it rather than beside it.

## Why the test case that found it does not use the interpreter

`test_formal_globals.py` requires three engines to agree (interpreter, arm64,
x86-64) because a module global's correctness depends on a second module
agreeing about where a slot lives. Its own rule for a case with no interpreter
reference is `printf` — "`printf` is not a name the interpreter resolves, so the
case's expected value stands on its own" — and
`a_comprehension_target_does_not_shadow_a_module_constant` uses it for exactly
this reason, with the interpreter's wrong answer (3) written into the case's
comment so nobody reads the green as an all-clear. When this is fixed, the case
loses its `printf` and regains the third engine, which is the anti-rot.