# FORMAL_variable_exponent_is_zero_on_arm64: `2 ** n` answers 0, where the same source answers 1024 on x86-64

**Status: found, NOT fixed. Measured on this tree, both architectures.**
Found from the x86-64 sweep slice (`sweep:x86-a`, work map
`bugs/FORMAL_sweep_work_map_2026-10-02_x86-a.md`), while building the probe
corpus that turned up the two x86-64 defects fixed in `f89f9622`. **It is an
arm64 bug and it is the mirror image of one of those**: the direction that makes
this one worse is that arm64 is the architecture the suite runs its positive
cases on.

## The measurement

Three sources, built with `--formal --no-prove` on both backends and run. Every
one of them is a program CPython answers, so this is not a construct either
machine declines.

```mojo
def main():
    y = 3
    printf("%d %d %d", 3 ** y, 2 ** y, 2 ** 4)
    return 0
```

| source | CPython | **arm64** | x86-64 |
|---|---|---|---|
| `3 ** y`, `y = 3` | `27` | **0** | 27 |
| `2 ** y`, `y = 3` | `8` | **0** | 8 |
| `2 ** 4` (literal exponent, same function) | `16` | 16 | 16 |
| `b ** n` with `b = 2`, `n = 10` | `1024` | **0** | 1024 |
| `3 ** -1`, `2 ** -2` (literal, negative) | `0` | 0 | 0 |

So the arm64 lowering has the **literal** exponent and not the **computed** one,
and it answers **0** rather than refusing: the image builds, runs, exits 0, and
prints a number. Nothing in the run distinguishes 0 from an answer.

## Why it is worse than the x86-64 gaps fixed alongside it

`test_formal_run.py`'s `run_case` builds **the host's architecture** for a
positive case, which on an arm64 machine is arm64. So every positive case in
this repository's largest formal suite runs the backend that gets this wrong,
and a case for `x ** n` would have caught it — there is none.
`test_formal_x86_64_parity.py` would have caught it too (it builds BOTH and
compares against CPython), and it has no `**` case with a variable exponent
either: its `**` rows, added in `f89f9622`, are all literal exponents, because
that is what the x86-64 defect was.

## Where to look

`formal/arm64_codegen.py`'s `_emit_div_shift_pow` — the helper the augmented
`/= //= %= **=` path and the binary `**` path both route through. x86-64's twin
(`formal/x86_64_codegen.py`'s `_emit_pow`) has two paths: a literal unroll for
`0 <= lit <= 8` and a **binary-exponentiation loop** for anything else, and that
loop is what answers `2 ** 10` and `2 ** y` correctly (both measured). If
arm64's helper has only the unroll, then every non-literal exponent falls off
the end of it and the emitter leaves RAX at 0 — which is exactly the observed
answer and is worth checking first, because it is one `if` rather than a
design.

Two constraints on the fix, both measured here:

* **`0` must not become the answer by accident.** The negative-literal rule
  (`x ** -1` → 0) is deliberate on both backends — formal's integer lattice has
  no fractions — so a fix that routes the non-literal case through a path that
  returns 0 would look finished and be wrong in the same way. `2 ** y` with
  `y = 3` is 8 and that is the case to assert.
* **The literal path must not change.** It is correct on both backends today
  (`2 ** 4` → 16), so any fix that rewrites the unroll has to keep it.

## The case that keeps it from coming back

One row in `test_formal_x86_64_parity.py`, which is where a two-architecture
disagreement about a *value* belongs and where the oracle is CPython:

    def main():
        n = 10
        printf("%d %d", 2 ** n, 3 ** n)      # 1024 59049

with the CPython source identical apart from `sys.stdout.write`. A second row
with the exponent in a parameter (`def main(k: Int)` calling a helper) is what
distinguishes "the exponent is a local" from "the exponent is a literal", which
is the distinction this defect turns on.