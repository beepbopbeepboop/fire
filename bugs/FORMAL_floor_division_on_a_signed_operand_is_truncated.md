# FORMAL_floor_division_on_a_signed_operand_is_truncated

**Area:** FORMAL, both backends — `formal/arm64_codegen.py`'s
`_emit_div_shift_pow`, `formal/x86_64_codegen.py`'s `_emit_div_mod`, the
source-level model in `lib/ProofLib.lean`, and `formal/arm64_proof_gen.py`'s /
`formal/x86_64_proof_gen.py`'s `_expr_go` / `_expr_go_t`.
**Status: NOT FIXED, and NOT attempted by a light worker — re-measured
2026-10-03 (the table below is unchanged), the emitted shape is now DERIVED and
written down in §"The emitted shape", and the blocker is named with its number:
the `lib/ProofLib.olean` build peaks at 7.82 GB, which does not fit under the
8 GB a light worker here is given, and the emitted code and the model cannot
move apart. §"Why this was not attempted" says what a worker with the ceiling
should do first.**

Found 2026-10-03 on `work/formal14-fuzz-arm64` by `tools/formal_fuzz.py`, which
puts `%` and `//` in its operator pool precisely because a generator that cannot
emit them cannot notice the day they are fixed. It is the single largest source
of divergence in a 1000-seed sweep (37 of 300 seeds blamed `modulo` and 15 on
`floordiv` in the first 300).

## Re-measured 2026-10-03, unchanged

One program, eight of the rows below, both backends, `build --formal
--no-prove` and then the image (CPython through a `printf` shim, since these
sources are the ones the formal entry point takes):

```
            CPython   arm64   x86-64
a=-3           -3       -3      -3
b= 7//(0-2)    -4       -3      -3     ← wrong
c=-8//2        -4       -4      -4
d=(-7)%3         2       -1      -1     ← wrong
e= 7%(-3)      -2        1       1     ← wrong
f=(-7)%(-3)    -1       -1      -1
g= 7%3          1        1       1
h=(-7)%2==1     1        0       0     ← wrong
```

Four of eight, both architectures, all of them the sign-mismatch rows. Nothing
in this tree has moved since the table below was taken.

## The emitted shape

Derived rather than guessed, because the obvious correction is not the only one
and the choice is load-bearing for the proof side.

**No encoding that contains `SDIV` can express a floor.** `SDIV` truncates, so
every `q = ±tdiv(±n, ±d)` with at most a negation of one side is a truncating
quotient; only a CONDITIONAL correction reaches `Int.fdiv`. That kills the
cheap-looking options (negate one side, negate both, negate the quotient) and it
means `lib/ProofLib.lean`'s `arm64_step` case for `SDIV` — which computes
`sdiv64` — is correct as the model of ONE INSTRUCTION and simply no longer
describes the whole block. The source model and the value flow cannot drift
apart; they have to move together, which is §Why this is not a patch below.

**The correction, and the identity that makes it need neither `n` nor a
multiply.** With `q = tdiv(n, d)` and `r = n - q*d`:

    q_floored = q - c        where  c = 1 if r ≠ 0 and sign(r) ≠ sign(d) else 0
    r_floored = r + d*c

so the correction is decided from `r` and `d` alone — the dividend is not needed
after the divide, which is what makes the x86-64 side possible at all (`IDIV`
leaves `q` in RAX and `r` in RDX and the dividend nowhere). Both identities are
the reason the two backends can be given the SAME shape, which is the property
this tree wants of them.

| step | arm64 (all modelled: `_STEP_CONDS` 43, 47, 8, 13, 30, 7, 12, 5) | x86-64 (all modelled in `lib/X86.lean`: cqo, idiv, xor, test, setcc, and, sub, neg, add) |
|---|---|---|
| `q = tdiv(n, d)` | `SDIV X2, X0, X1` | `CQO ; IDIV R11` |
| `r = n - q*d` | `MSUB X3, X2, X1, X0` | (already in RDX) |
| `t = r XOR d` | `EOR X4, X3, X1` | `MOV RCX, RDX ; XOR RCX, R11` |
| `c1 = (r ≠ 0)` | `CMP X3, #0 ; CSET X5, ne` | `MOV R9, RDX ; TEST R9, R9 ; SETNE R9D` |
| `c2 = (t <s 0)` | `CMP X4, #0 ; CSET X6, lt` (code 11) | `TEST RCX, RCX ; SETL R8D` |
| `c = c1 & c2` | `AND X5, X5, X6` | `AND R8, R9` |
| `//` | `SUB X2, X2, X5 ; MOV X0, X2` | `MOV R9, R8 ; SUB RAX, R9` |
| `%` | `NEG X5 ; MSUB X3, X1, X5, X3` (which is `r + d*c`) | `MOV R9, R8 ; NEG R9 ; AND R9, R11 ; ADD RDX, R9` |

**Zero new instruction steps on either side**, which is the one piece of good
news in this document and the reason the model change is smaller than it looks:
`MSUB`, `EOR`, `AND`, `CMP` (register and immediate), `CSET`, `SUB` (immediate)
and `NEG` are all in `arm64_step`'s table and all in `lib/X86.lean`, and
`_STEP_CONDS` already routes each of them. The generator's per-instruction steps
are emitted mechanically from that table, so the new instructions cost nothing
there. What they do NOT cost nothing is the FINAL goal: the block's value now has
to be shown equal to the source model's term for `//`, which today is `sdiv64`.

**The shape the model should take, and why it is not `Int.fdiv`.** Point
`evalExpr`'s `//` and `%` at new `fdiv64` / `frem64` and define them over the
machine's OWN terms rather than over `Int.fdiv`:

```lean
def fdiv64 (a b : UInt64) : UInt64 :=
  if b = 0 then 0 else
    let q := sdiv64 a b; let r := srem64 a b
    if r = 0 ∨ sKey a = sKey b then q else q - 1
def frem64 (a b : UInt64) : UInt64 := a - b * fdiv64 a b
```

That is `Int.fdiv` mathematically — the correction condition is exactly "the
remainder is non-zero and the operands' signs differ", and `frem64` is
`a - b*floor(a/b)`, which is Python's `%` — but it is built from `sdiv64` /
`srem64` / `sKey`, the terms the machine's own steps already compute. The
property `sdiv64`'s comment claims for the model ("the source model and the value
flow cannot drift") is then preserved by construction instead of by a bridge
lemma, which is the difference between a change that needs one new theorem and a
change that needs a theorem about `Int.fdiv` over two's-complement words
(`srem64_sub` is 60 lines of exactly that, and it is the shape a second one
would take). The price is that "this is Python's floor division" becomes a fact
to be argued rather than a definition, so the honest version states both and
proves the equality where it can be afforded.

## Why this was not attempted

**The blocker, with its number.** `lib/ProofLib.lean` is the source of the 27 MB
`ProofLib.olean` every proof-checking path links against, and `formal/lean.py`'s
own measured table (top of the file) records the build at **112 s wall and a
7.82 GB peak** — against the 8 GB ceiling a light worker on this task is given
(`memslot --gb 8`), and against a budget the whole machine shares. So:

* the runtime half alone (both emitters, `test_formal_run.py`'s `neg_div_rem` /
  `neg_mod` rewritten, the fuzzer's two `KNOWN_DIVERGENCES` rows deleted) would
  leave every existing proof RED on any program that divides, silently, because
  the model would still say `sdiv64` — which is the doc's own step 1 and is
  correctly described there as "the honest intermediate state";
* the model half needs the library rebuilt, which does not fit, and cannot be
  checked by a proof run either — the slowest proof in the corpus is
  `formal/examples/udivmod.mojo` at 297 s and 2.30 GB, and it would need the
  rebuilt library first.

Landing a change that makes the proof path quietly wrong for every dividing
program, with no way to check it, is worse than the divergence, which is loud in
a fuzz sweep and attributed. So the work is written down instead, and the next
worker should take it with the ceiling the library build needs (`MEMLIMIT_GB`
above 8, or the `prooflib` step's own class) rather than under this one.

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

**As of 2026-10-03 step 1 is wrong as written and should be read with §The
emitted shape above.** Landing the source model ALONE, with both backends still
emitting `SDIV`, is not the honest intermediate state — it is a tree in which
every proof of a dividing program is wrong and no gate can see it, because the
Lean-checking tests are disabled. The model and the emitters move in ONE commit
or not at all, and the order inside that commit is: model first (so the
definition the generator will name exists), then arm64, then x86-64, then the
generator's `_expr_go` / `_expr_go_t` (`sdiv64` → `fdiv64`, `srem64` →
`frem64`), then the tests.

0. **Get a ceiling the library build fits under** (§Why this was not attempted).
   Everything below is blocked on it and nothing below is blocked on anything
   else. `MEMLIMIT_GB=16` for the session is enough; the build's measured peak
   is 7.82 GB.
1. Define `fdiv64` / `frem64` in `lib/ProofLib.lean` over `sdiv64` / `srem64` /
   `sKey` — the shape in §The emitted shape, not `Int.fdiv` — and point
   `evalExpr`'s `//` and `%` and the `_`-parameterised twin's at them. **No new
   theorem in this step**: a definition that elaborates cannot break the library,
   and an unproven theorem in `ProofLib.lean` would. Rebuild, then run
   `test_formal.py`'s example corpus and count what goes red: that number sizes
   the rest, and it is not knowable without doing it.
2. arm64's `_emit_div_shift_pow`: emit the correction from the table above.
   **No new step to teach** — every instruction it adds is already in
   `_STEP_CONDS` — so what this step actually buys is the residual goal, and
   `fdiv64`'s definition is shaped to be the same expression the block computes
   so `simp`/`grind` has a chance rather than a bridge lemma to cross.
3. x86-64's `_emit_div_mod`, mirroring it, with `cond_negated`'s new sibling for
   the sign test (`SETL`, which `lib/X86.lean` already routes).
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
6. **Re-enable the Lean-checking tests for the division corpus**, or add one
   narrow proof case that divides a negative. Without it, step 1's red is
   invisible and step 2's residual goal is unproven — which is how this document
   would have been written twice.

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
