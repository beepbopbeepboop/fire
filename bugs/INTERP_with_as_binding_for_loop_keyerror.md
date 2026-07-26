# INTERP: `with X() as file: for line in file:` raises KeyError, unrelated to generators

## Discovery context

Found while manually verifying Milestone 2 (real generator execution,
commit `58a0ecb`) against a reconstruction of `Tools/unicode/makeunicodedata.py`'s
actual generator shape (`records()`, which wraps `with open_data(...) as
file: for line in file: ...` in a generator). Confirmed via `git stash`
that this reproduces identically on the pre-Milestone-2 baseline with
**no generator or `yield` involved at all** — a `with`-bound name used as
a `for`-loop iterable mis-binds regardless of generators.

## Repro (needs reconstruction — write a minimal case before fixing)

Roughly:
```python
class Ctx:
    def __enter__(self):
        return [1, 2, 3]
    def __exit__(self, *a):
        pass

def f():
    with Ctx() as file:
        for x in file:
            print(x)
f()
```
Reported symptom: a `KeyError` from `MojoInstance.__getitem__`, suggesting
the `with ... as file` binding produces something that iterates as if it
were a dict/mapping key-lookup rather than as the plain list `__enter__`
actually returned.

## Status

Not yet minimally reproduced/root-caused — this writeup is a placeholder
capturing what Milestone 2's verification pass found, so it isn't lost.
Next step: build the minimal repro above (or closer to it) directly, run
`python3 mojo.py run` on it, and trace where `MojoInstance.__getitem__`
gets invoked in `myinterpreter.py`'s handling of either `execute_WithStmt`
or `execute_ForStmt` when the iterated value came from a `with`-bound name.
