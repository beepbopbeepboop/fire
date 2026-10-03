# FORMAL_floor_division_on_a_signed_operand_is_truncated

**Area:** FORMAL, both backends — `formal/arm64_codegen.py`'s
`_emit_div_shift_pow`, `formal/x86_64_codegen.py`'s `_emit_div_mod`, the
source-level model in `lib/ProofLib.lean`, and `formal/arm64_proof_gen.py`'s /
`formal/x86_64_proof_gen.py`'s `_expr_go` / `_expr_go_t`.
**Status: NOT FIXED. Measured, minimised, localised to five places, and NOT a
patch — the Lean model has to change with the emitted code and that is the whole
of why.**

Found 2026-10-03 on `work/formal14-fuzz-arm64` by `tools/formal_fuzz.py`, which
puts `%` and `//` in its operator pool precisely because a generator that cannot
emit them cannot notice the day they are fixed. It is the single largest source
of divergence in a 1000-seed sweep (37 of 300 seeds blamed `modulo` and 15 on
`floordiv` in the first 300).

## What is wrong

`//` truncates toward zero and `%` takes the sign of the DIVIDEND. Python's (and
Mojo's) rule is that `//` FLOORS and `%` takes the sign of the DIVISOR, so the
two disagree exactly when the operands' signs differ:

```console
$ python3 tools/memslot.py --gb 8 --label probe -- \
      python3 fire.py build --formal --no-prove -o .tmp/x .tmp/probe/div.mojo
```

| source | CPython 3.14 | arm64 | x86-64 |
|---|---|---|---|
| `print(0 - 7 // 2)` | `-3` | `-3` | `-3` |
| `print(7 // (0 - 2))` | **`-4`** | **`-3`** | **`-3`** |
| `print(0 - 8 // 2)` | `-4` | `-4` | `-4` |
| `print((0 - 7) % 3)` | **`2`** | **`-1`** | **`-1`** |
| `print(7 % (0 - 3))` | **`-2`** | **`1`** | **`1`** |
| `print((0 - 7) % (0 - 3))` | `-1` | `-1` | `-1` |
| `print(7 % 3)` | `1` | `1` | `1` |
| `print(1 if (0 - 8) % 2 == 0 else 0)` | `1` | `1` | `1` |
| `print(1 if (0 - 7) % 2 == 1 else 0)` | **`1`** | **`0`** | **`0`** |

Every one builds, runs and exits 0. The last row is the one that matters: `x % 2
== 1` is the standard odd-number test and it answers the wrong thing for every
negative odd `x`.

`/` between two ints is a SEPARATE and already-documented limit (the model is
int-only, `FORMAL.md` §6 Phase 7): `0 - 7 / 2` is `-3` here and `-3.5` in CPython
because there is no float. It is in this document only so a reader does not
assume `/` was measured and missed.

## Why it is not a patch

The emitted code and the Lean model have to move together, and they are five
places in three languages' worth of files:

1. **`formal/arm64_codegen.py::_emit_div_shift_pow`** emits `SDIV` + `MSUB` (and
   `UDIV` for an unsigned type). The floor correction is, on arm64,
   `q = SDIV(n, d); r = n - q*d; if r != 0 and (r < 0) != (d < 0): q -= 1` —
   four instructions the model would have to learn (`CMP` with the register
   form, `CSET`/`CSINC`, and a conditional `SUB`), on top of the existing
   divide.
2. **`formal/x86_64_codegen.py::_emit_div_mod`** emits `CQO` + `IDIV`. The same
   correction on x86-64 is `CQO; IDIV; …` plus a sign test and a `SUB`, and
   `FORMAL_x86_64_cqo_step_lemma_contradicts_the_model` shows that area's step
   lemmas are already delicate.
3. **`lib/ProofLib.lean`'s `sdiv64` / `srem64`** are the SOURCE-level model, and
   their own comment states the decision: "`sdiv64`/`srem64` truncate toward
   zero and `asr64` propagates the sign bit, and those are the very terms the
   machine's SDIV/MSUB/ASR steps compute … so the source model and the value
   flow cannot drift." That is a good reason for the model to be truncating while
   the machine is `SDIV`, and it becomes a bad one the moment the machine stops
   being `SDIV`: the two have to become `fdiv64` / `frem64` over `Int.fdiv` /
   `Int.fmod`, in **two** places (`evalExpr` and the `_`-parameterised evaluator
   beside it).
4. **`formal/arm64_proof_gen.py` and `formal/x86_64_proof_gen.py`** choose
   `sdiv64` vs `/` and `srem64` vs `%` from `cmp_signed`, which is right. What
   changes is that they must now name the FLOORED terms, and the per-instruction
   step for the new correction instructions must exist. `srem64_sub` /
   `u64_div_msub` are the identities the generator already reaches for; the
   correction has no analogue.
5. **`test_formal_run.py`'s `neg_div_rem` and `neg_mod`** PIN the truncating
   answers as expected values — `a / 2 == 0 - 3 and a % 2 == 0 - 1` for
   `a = -7`. Those two rows are the discovery cost of the fix and they have to be
   rewritten to CPython's answers in the same commit, which is also the check
   that the fix landed.

**The cost nobody should under-estimate**: `lib/ProofLib.lean` is the source of
the 27 MB `ProofLib.olean` every proof-checking path links against
(`formal/lean.py::ensure_library`), so editing it invalidates that build for
everybody and re-proves the library. That is a heavy-worker job, not a patch a
light worker can land and verify, and the rule this repository already follows —
"no gate for formal; anything of ours over 3-4 GB is a bug" — is why it is filed
here rather than attempted.

## The next step, in order

1. Land the **source model** change alone: `fdiv64` / `frem64` over
   `Int.fdiv` / `Int.fmod` in `lib/ProofLib.lean`'s `evalExpr` and its
   `_`-parameterised twin, leaving both backends emitting `SDIV`. Every existing
   proof then goes red on exactly the programs that divide a negative, which is
   the honest intermediate state and it is also the measurement of how much
   depends on it: run `test_formal.py` and count. That number is what sizes the
   rest of the project, and it is not knowable without doing it.
2. arm64's `_emit_div_shift_pow`: emit the correction, and teach
   `formal/arm64_proof_gen.py` the step for each instruction it adds. `CMP`
   (register form), `CSET` and a predicated `SUB` are the candidates to check
   against `ProofLib`'s instruction table first — `SUB` (immediate and register)
   and `CMP` are already there, so the count of genuinely new steps may be one.
3. x86-64's `_emit_div_mod`, mirroring it, with `cond_negated`'s new sibling for
   the sign test.
4. Rewrite `neg_div_rem` and `neg_mod` to CPython's answers and add the eight rows
   of the table above as `BOTH_ARCH_CASES`, including the `x % 2 == 1` idiom that
   no amount of reading the spec would have found.
5. `tools/formal_fuzz.py`: delete `floordiv` and `modulo` from
   `KNOWN_DIVERGENCES` **in the same commit**, which is the anti-rot: a known
   construct left in that table stops being measured the day it is fixed — and
   which is only true while `--mix signed` still generates a signed-over-signed
   division. That is what the two generators were merged into one for
   (`work/merge-formal15`): the arm64 generator produced this construct from its
   default mix and the x86-64 one deliberately avoided it, and keeping the
   avoiding half would have left both rows of this table UNREACHABLE — a quiet
   generator, and a green run that measures nothing. `test_formal_fuzz.py` now
   asserts that `--mix signed` reaches `floordiv`, so deleting the row without
   deleting the mix fails there instead of in a two-thousand-program sweep
   nobody reads.

## What the corpus looks like once this is accounted for

A 500-seed arm64 run with this divergence and the other known ones classified
(`tools/formal_fuzz.py --seeds 1000-1499 -j 2`, 2026-10-03): **238 agree, 64
refused, 198 diverged — every one of the 198 attributed — 0 errors, 0
unexplained.** The attribution split is 89 `%`, 28 `//`, 74 `s[i]`, 7 pairs.

That was the arm64 generator, which emitted all three known constructs from its
default mix. It is `--mix signed` in the consolidated tool, so `--seeds` and
`--arch` are unchanged and the MIX is not: a rerun of exactly that command
measures a different population. The command below is the one that reproduces
this section.

That number is the argument for doing this first. Two thirds of the corpus's
disagreements with CPython are `%` and `//` between them, so fixing them is what
turns the fuzzer from a machine that reports the same three known divergences
into one that can find the next one — and the next tier is `s[i]`, which is
`bugs/FORMAL_string_value_model.md`'s to answer, not this file's.

The x86-64 arm over 200 of the same seeds is the same picture with the same
counts scaled (86 agree, 33 refused, 81 diverged, all attributed), which is the
result to expect from a rule both backends read from `formal/model.py` and
`formal/types.py`.

## Reproducing

```console
$ python3 tools/memslot.py --gb 8 --label fuzz -- \
      python3 tools/formal_fuzz.py --arch arm64 --mix signed --seeds 0-299 -j 2
  … 37  modulo: `%` takes the sign of the DIVIDEND instead of the divisor
  … 15  floordiv: `//` truncates toward zero instead of flooring
$ python3 test_formal_run.py neg_div_rem neg_mod     # the two rows that PIN it
```

`--mix strings` is the other half of this table's corpus (`s[i]`), and
`--mix core` is the quiet one: it divides only by a positive divisor over a
non-negative dividend precisely so the word-size model and this floor/truncate
decision are not reported as miscompiles hundreds of times. Run all three when
you want the corpus the sections above describe.
