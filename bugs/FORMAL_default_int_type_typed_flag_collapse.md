# `formal/`: `DEFAULT_INT_TYPE` became signed `Int`, and the `typed` model flag went vacuous with it

**Status: OPEN, not fixed, and deliberately not fixed by the agent that found
it** (`19bc0dd` is the owner; the merge `ae9877d` is how it arrived). It is not
one of the two regressions agent G1 was given, and it is not a string problem,
but it is the reason `make check-formal` does not read `41/4/0` even with
`@spec` parsing again. Written down rather than fixed because the fix is in
`formal/`, which four agents were editing concurrently when this was found.

The two regressions this *was* found through are fixed and recorded at the
bottom of `FORMAL_string_value_model.md`: `@spec(name; …)` no longer parses
(`19bc0dd`, `fire_compiler.py`'s decorator-argument reader) and
`gimplerunner`'s two string cases were one `runtime/fire_runtime.c` predicate
(`e7fc3ec`).

## The numbers, measured, with the `@spec` fix in place

| | at `1824fa2` | at `4b9dd2a` before this fix | with the `@spec` fix |
|---|---|---|---|
| `test_formal.py` (arm64) | `PASS=41 KNOWN-GAP=4 FAIL=0` | `PASS=26 KNOWN-GAP=6 FAIL=13` | **`PASS=29 KNOWN-GAP=6 FAIL=10`** |
| `test_formal.py --backend x86_64` | `PASS=45 KNOWN-GAP=0 FAIL=0` | `PASS=40 KNOWN-GAP=0 FAIL=5` | **`PASS=44 KNOWN-GAP=0 FAIL=1`** |
| `formal/x86_64_model_test.py` | `agree 45 WRONG 0 NO-RUN 0 build-fail 0` | `agree 40 WRONG 1 build-fail 4` | **`agree 44 WRONG 1 NO-RUN 0 build-fail 0`** |

Every `formal/examples/*.mojo` (45 of 45) parses. The 5 x86-64 `build-fail`s
and 4 of the arm64 FAILs were `fact`/`fib`/`sum`/`count` and are gone. What is
left is this document.

The residual sets, by name:

- **arm64, 10 FAIL**: `absval`, `bigconst`, `condassign`, `condassign2`,
  `deepif`, `elif3`, `ifonly`, `ifonly2`, `ifparam`, `twoifs`.
- **arm64, 6 KNOWN-GAP**: `both`, `countdown`, `either`, `fib`, `subscript_var`,
  `wge`. (Two of these — `subscript_var`, `wge` — were already gaps; the other
  four are new, and `fact`/`sum`/`count` now pass only with a `sorry` each,
  per the census.)
- **x86-64, 1 FAIL**: `wide_recv`.
- **`x86_64_model_test.py`, 1 WRONG**: `udivmod`
  (`real=4 model=7905747460161236410`).

## Mechanism 1: `typed` is computed by comparison against `DEFAULT_INT_TYPE`,
and that comparison is now always true

`formal/x86_64_proof_gen.py:528-537` (and its arm64 twin) decide whether to use
the **typed** source model:

```python
call_types = {g.name: resolve(parse_type_name(g.return_type) or DEFAULT_INT_TYPE)
              for g in functions}
vtypes = function_var_types(fn, call_types)
rt = resolve(parse_type_name(getattr(fn, "return_type", None)))
all_t = list(vtypes.values())
if rt != DEFAULT_INT_TYPE:
    all_t.append(rt)
typed = any(t != DEFAULT_INT_TYPE for t in all_t)
```

`19bc0dd` changed `formal/types.py`:

```
-DEFAULT_INT_TYPE = IntType(64, False)
+DEFAULT_INT_TYPE = IntType(64, True)
```

which is the right change — an unannotated `int` is signed, and modelling it as
unsigned made `a = 0 - 3; if a < 2:` false. But `typed` uses
`t != DEFAULT_INT_TYPE` as its proxy for "this function has a non-default type,
so the untyped model is not enough", and after the flip the proxy is vacuous
for **every** function whose locals and return type are all plain `Int` — which
is nearly the whole corpus. Measured on `formal/examples/wide_recv.mojo`:

```
at 1824fa2:  DEFAULT IntType(width=64, signed=False)
              vtypes {'n': IntType(64, False), 'p': IntType(64, False)}
              typed = True
at 4b9dd2a:   DEFAULT IntType(width=64, signed=True)
              vtypes {'n': IntType(64, True),  'p': IntType(64, True)}
              typed = False
```

So the *untyped* model generator (`_stmts_go` / `_expr_go`) is now what runs,
almost everywhere.

## Mechanism 2: the untyped model generator returns a WRONG model instead of
raising, so the "documented gap" fallback never fires

`formal/arm64_proof_gen.py`'s `_expr_go` answers `(0 : UInt64)` for a `Call` and
for any expression kind it does not model. That is a legitimate leaf answer for
an unmodellable *sub*-expression; at statement level it is a lie about the
whole function.

`formal/x86_64_proof_gen.py:543-559` wraps the call in `try/except` and degrades
to a **stated** gap (`main_go n = n` plus a `NOTE:` saying the model is
meaningless) when the generator raises — and the typed generator *does* raise
(`_stmts_go_t`'s `raise NotImplementedError("typed model: while loops not yet
supported")`, `arm64_proof_gen.py:749`). It has a second, self-check for a model
that *mentions* a `<name>_go` it does not define (`x86_64_proof_gen.py:569-584`)
— but that only fires on a dangling reference, and `(0 : UInt64)` references
nothing.

The result is a silent `false`:

```
/-- Mojo semantics: direct Lean model of the source code. -/
def main_go (n : UInt64) : UInt64 :=
  (0 : UInt64)                      -- no NOTE. nothing says this is a gap.
```

`wide_recv`'s `main` is `Point(); p.set_x(3); p.set_x(4); return
p.get_x() + p.get_y()` — every statement is a `Call`, so every operand is
`(0 : UInt64)` and the model is 0 for every input. The real answer is 4, the
real x86-64 binary returns 4 (`./wide_recv.aout 2; echo $?` → 4), and the Lean
machine model agrees — so the proof is *correct* to fail:

```
main_runs_2 : main_result 2 = mojo 2
  error: Tactic `native_decide` evaluated that the proposition is false
```

At `1824fa2` the same example reached the same `0`, but the *typed* path raised
first, so the emitted model was the identity `main_go n = n` with its `NOTE` —
and `main_result 2 = mojo 2` then read `2 = 2` and passed. **That pass was an
accident**: the compiled image is byte-identical between the two trees (424
bytes, verified by comparing the emitted `main_code_bytes` lists), and it
returns 4. So `1824fa2` "passed" `wide_recv` because the identity model
happened to agree with a *wrong* Lean machine model, and the merge's 281-line
`lib/ProofLib.lean` change made the machine model right. This is a **true
positive that an improvement exposed**, not a new machine bug.

## Mechanism 3: the arm64 FAILs are the two halves of the model disagreeing
about signedness

The x86-64 side does not have this problem because it never had a typed/untyped
split of the same shape. The arm64 failures are all one family. Representative,
`condassign`:

```
  n ^^^ 9223372036854775808 ≤ 9223372036854775808      -- the by_cases hypothesis
⊢ (match
      (if sKey 0 < sKey n then (some 1, …) else (some 0, …)).fst with
    | some v => v
    | none => 0)
    = 0
```

`19bc0dd` added `_cmp_go` precisely so that "the `by_cases` hypothesis and the
model's own `if` are the same term" — its own docstring says a mismatch "is not
a proof that fails, it is a proof of something FALSE — and Lean accepts it as
long as the generator can find a closing tactic". The `by_cases` side and the
`sKey`-based model side now agree with each other; the `MojoExpr` evaluation
side (the `match (if sKey 0 < sKey n then (some 1, …) …)` term, which is the
step-certificate/environment shape from `lib/ProofLib.lean`) does not reduce to
the same branch, and `native_decide` finds the counterexample. The same shape
appears in `absval`, `bigconst`, `condassign2`, `deepif`, `elif3`, `ifonly`,
`ifonly2`, `ifparam`, `twoifs`. `formal/lean.py`, `formal/types.py` and
`formal/arm64_proof_gen.py` all changed in the same commit; the `by_cases` /
model / `MojoExpr` triple is where the remaining disagreement is.

## Next step, in order

1. **Decide what `typed` is for.** It is a proxy for "the untyped model is not
   enough", and after the `DEFAULT_INT_TYPE` flip the proxy is vacuous. Either
   (a) compute it from something that is not `!= DEFAULT_INT_TYPE` — the
   presence of a *type annotation* in the source, not the resolved type of a
   value — or (b) drop the flag and always use `_expr_go_t` / `_stmts_go_t`,
   which is the path that actually models the source and the one that raises
   when it cannot. (b) is smaller and is the direction the code has been
   moving; measure it before committing, because the typed generator has more
   `NotImplementedError`s and this will move the KNOWN-GAP count.
2. **Make the untyped model generator refuse rather than lie.** A `Call` in a
   `return` position is not `(0 : UInt64)`; it is a shape the generator does not
   model. Raise, exactly as `_stmts_go_t` does, so `x86_64_proof_gen.py`'s
   existing `except` produces the stated gap. This alone converts `wide_recv`
   from a false FAIL into a documented gap, and it is the guard that stops the
   next function with a call in it from producing a false proof silently.
   **This is the cheap half and it is worth doing first** — it is a correctness
   guard, not a coverage improvement, and it is independent of (1).
3. Then take the arm64 signedness triple (`by_cases` hypothesis / `_cmp_go`
   model term / `MojoExpr` step evaluation) in `formal/arm64_proof_gen.py` and
   `lib/ProofLib.lean`. That is the 10 arm64 FAILs, and it is real work.
4. `udivmod`'s `x86_64_model_test.py` WRONG is very likely the same
   `DEFAULT_INT_TYPE` flip seen from the Python machine model rather than the
   Lean one — `def udivmod(n): return (n / 7) + (n % 7)` is all-unannotated, so
   signed-vs-unsigned `SDIV`/`UDIV` is decided by the default type. Check it
   against (1) before treating it as separate.

## Why the agent that found this did not fix it

`formal/` was explicitly another wave's lane, with four agents live in
`formal/model.py`, `formal/build.py` and both backends. A wrong edit there is
expensive to untangle and the fix is not a one-liner. Everything outside
`formal/` that this regression touched has been fixed and is recorded in
`FORMAL_string_value_model.md`.
