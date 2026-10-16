# `_is_recursive` does not recurse into a call's ARGUMENTS, so a self-call written `g(f(n-1))` is invisible and the model is emitted as a plain `def` that calls itself

**Area:** FORMAL (the proof layer's source model — `formal/arm64_proof_gen.py`,
shared by both backends through `x86_64_proof_gen.py`'s `AP._go_defs_for`).
**Status: OPEN.** Found 2026-10-12 (`work/formal320-docs`) while fixing the
sibling omission in `_callees_of`; that one is fixed, this one is not.

## What I ran

A source whose only self-call is written as another call's argument:

```
def g(x):
    return x

def f(n):
    if n == 0:
        return 0
    return g(f(n - 1))

def main(n):
    return f(n)
```

asked of the model generator directly (no Lean), and then built and checked:

```console
$ python3 -c "…G._is_recursive(fd['f']); G._count_self_calls(fd['f']); G._callees_of(fd['f'])…"
_is_recursive(f) = False          -- WRONG: f calls itself through g
_count_self_calls(f) = 1
_callees_of(f) = ['g', 'f']       -- correct after the sibling fix
```

## What I saw

`_is_recursive` returns `False`, so `_gen_go` chooses `kw = "def"` instead of
`"partial def"`, and the emitted model names itself:

```lean
def f_go (n : UInt64) : UInt64 :=
  (if (n = (UInt64.ofNat 0)) then (UInt64.ofNat 0) else (g_go (f_go (n - (UInt64.ofNat 1)))))
```

`formal/x86_64_proof_gen.py` builds a proof for it (it does not raise), and
`formal/lean.py::check_proof_cached` on the result fails at the definition:

```
selfnested_proof.lean:31:4: error: fail to show termination for
  f_go
…
failed to infer structural recursion:
Cannot use parameter n:
  the type UInt64 does not have a `.brecOn` recursor
```

## What I expected

`_is_recursive` is the "is this function recursive" question, and a self-call is
a self-call wherever it appears. `_count_self_calls` (`arm64_proof_gen.py`) is
the more complete walker — it recurses into `e.args` — and it finds the call; the
two disagree, on the same body, about the same fact.

## The root cause, and the exact next step

`_is_recursive`'s `in_expr` returns on the FIRST `Call` without descending into
its arguments:

```python
    def in_expr(e):
        if isinstance(e, Call):
            return _call_name(e) == fn.name      # ← no recursion into e.args
        if isinstance(e, BinOp):
            return in_expr(e.left) or in_expr(e.right)
        if isinstance(e, Unary):
            return in_expr(e.operand)
        return False
```

`_callees_of` had the identical omission and it is fixed (`for a in e.args:
in_expr(a)` beside `out.append(_call_name(e))`); `_count_self_calls` has always
had the recursion. The fix here is the same one-line shape — recurse into
`e.args` before returning the name test — so the three walkers agree.

**Why this is separate from the `_callees_of` fix and not folded into it:** the
two defects have the same shape and the same fix, but different symptoms and
different gates. `_callees_of`'s omission made the model generator REFUSE (or,
on x86-64, silently substitute the identity placeholder); this one makes it emit
a `def` that Lean rejects. A test for one does not catch the other — the
`_callees_of` test in `test_formal_call_proof_gen.py` asserts the callee's `_go`
exists and the call renders, which a self-recursive `def f_go` satisfies right up
to the point Lean runs.

**The test the fix owes:** a source of the shape above, `_is_recursive(f)` is
`True`, and the emitted model says `partial def f_go`; the shared walker means
one test covers both backends. There is a `formal/examples` gap here too — no
example in the corpus has a self-call in an argument position, which is why the
omission has never shown up as a red example.
