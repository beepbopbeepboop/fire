# the `shift_imm8:*` successors set only ZF and SF, and `x86_shift_post` sets four

**Area:** FORMAL — `formal/x86_64_endtoend_test.py`'s `_SUCCS` rows for
`shift_imm8:shl` / `:shr` / `:sar`. **Status: OPEN, measured, and REPORTED BY A
CHECK — `formal/x86_64_model_coverage_test.py`'s successor comparison is red on
exactly these three rows.** Found 2026-10-05 on `work/formal42-5`, by the corpus
sweep that pass ran; see §"What I ran" for both measurements.

## What it is

`x86_step_shl_imm8`, `x86_step_shr_imm8` and `x86_step_sar_imm8` all conclude

```lean
{ x86_shift_post s (rm + x86_rex_b rex) <digit>
    (x86_get_reg s (rm + x86_rex_b rex)) ((code (m + 3)).toNat &&& 63)
  with rip := m + 4 }
```

and `x86_shift_post` writes **four** flags: `zf` and `sf` from the result, `cf`
from the last bit shifted out, and `of` (defined for a count of one).  The
emitter's successor rows write **two**:

```python
"shift_imm8:shl":
    "{ x86_set_reg $s ($rm + x86_rex_b $rex) ((x86_get_reg $s "
    "($rm + x86_rex_b $rex)) <<< $sh) with rip := $next, "
    "zf := ($fl).zf, sf := ($fl).sf }",
```

— and the row's own comment states the difference as a fact about the
instruction:

> `# The shifts write ZF and SF and LEAVE CF and OF ALONE — the whole difference
>  from every other flag-setting row, and the reason a `jcc` after a shift is
>  decided from the flags the shift did NOT touch.`

**That is false of this model.**  `x86_shift_post` computes both, and the
CPU agrees with the model and not with the comment: `formal/x86_64_model_fuzz.py
--census` reports `shift_imm8:<<` / `:>>` / `:>>signed` **AGREE** on all three
states each, and the fuzzer's rules even have to *special-case* shifts, because
a `jcc` after one reads flags this file's comment says are untouched.

So each of these three steps is a proof about an instruction that does not set
`CF`/`OF`, and the generated file says `Type mismatch | x86_step_shl_imm8 sN`.

## What I ran, what I saw

**1. The corpus sweep**, `python3 formal/x86_64_endtoend_test.py`, 58 min on a
machine shared with seven other workers:

```
shift_by_var  terminates: FAIL lean exited 1: error: Type mismatch | x86_step_shl_imm8 s18
shiftlr       terminates: FAIL lean exited 1: error: Type mismatch | x86_step_shl_imm8 s16
```

**2. The successor check**, which is where the row now lives.
`formal/x86_64_model_coverage_test.py::SUCCESSOR_FORMS` grew the three shift rows
and two ALU families on this pass, **and its probe grew all four flags and every
row's state grew `zf := true, sf := true, cf := true, of_ := true`** — because a
probe of `rip` and one register cannot see a flag, and a state whose flags are
CLEAR cannot see one either (`x86_shift_post` writing `cf := false` and a
successor leaving `cf` alone are the same state when `cf` was already false).
With the flags in the probe the rows report by name:

```
emitted successor vs the model: 13 form(s) — 3 of 13 FAILED
  shift_imm8:shl  the emitter's successor for shift_imm8:shl disagrees with the
                 model's step at 48 c1 e0 02 on rip or on the field this
                 instruction writes — the end-to-end proof of this step is about
                 a different instruction than the one the model runs   [50]
  shift_imm8:shr  … at 49 c1 ec 03 …                                   [53]
  shift_imm8:sar  … at 48 c1 f8 3f …                                   [56]
```

**The four ALU rows added beside them are green**, so this is the shift and not
the rows that were added with it.

## Why the exact next step is the one the other two rows already took

The fix is not to transcribe `x86_shift_post`'s `cf` and `of` into the successor
— it is to **quote `x86_shift_post` itself**, which is what `setcc` and
`imul_r64_r64` were both corrected to on this pass and what
`bugs/FORMAL_x86_64_end_to_end_proof.md`'s B3 states as the rule.  In the
successor table:

```python
"shift_imm8:shl":
    "{ x86_shift_post $s ($rm + x86_rex_b $rex) 4 "
    "(x86_get_reg $s ($rm + x86_rex_b $rex)) $k with rip := $next }",
```

with `$k` the model's own `((code (m + 3)).toNat &&& 63)` — **not** the
`if n >= 64 then 64 else n` clamp the row uses today, which is the VARIABLE
count's `x86_shift_cl` semantics and is a different function again.  That is the
second half of this bug and it is independent of the flags: the clamp and the
six-bit mask agree only for a count below 64, and a count of exactly 64 is the
case the clamp was written for.

Then three follow-on places, all named by the passes that needed them for the
other two wrappers:

1. **`x86_shift_post_mem` in `lib/X86.lean`,** beside `x86_set_reg_narrow_mem`
   and `x86_set_flag4_mem` from this pass.  `_concrete_read` projects `.mem`
   down the whole chain and `x86_shift_post` is an opaque `def`, so without it
   the closing read stops at the first shift and the guard admits — which is
   precisely the failure `bugs/FORMAL_x86_64_end_to_end_proof.md` records for
   `const2`.
2. **`x86_shift_post` in `_WRAPPER_DEFS`** and in `_SIMP_FORMS["shift_imm8:*"]`**
   (`_path_simp` cannot fold a state written by a definition it does not name,
   and this pass measured that on `x86_set_flag4`).
3. **`test_formal_sweep_truth.py::TestX86EndToEndEmitter`'s `_GUARD`** moves with
   the rip side condition's `simp` set, as it did on this pass for the second
   time.

**And `formal/x86_64_endtoend_test.py`'s `_abs_step` shift arms** set only `zf`
and `sf` too, with the same false comment.  That one is not a proof failure —
it is a *decision* failure, and it is the dangerous direction: the constant
propagation would report `cf` and `of` as whatever they were, so a `jcc` after a
shift could be DECIDED from a flag the machine overwrote.  A decided branch is
emitted as a proof (`hdec{k}` with no `sorry` in it), so a wrong decision makes
Lean reject the file rather than admit a claim — which is why this is fixable
without new machinery, and also why it must not be left.

## The state this leaves the tree in, stated plainly

* `formal-x86-model` (the registered job for
  `formal/x86_64_model_coverage_test.py`) is **RED on three rows**, by name and
  by line.  It is not in the `gate` bucket, it costs ~2 s, and per
  `CLAUDE.md`'s own rule a cheap job with a real finding is a real red that
  should be fixed rather than absorbed with an `expect=`.  **No marker is
  proposed here**, and the red is left visible on purpose.
* `formal-x86-endtoend` goes from **7 failing to 5** when this lands (or to 4
  if `shift_by_var` and `shiftlr` are the only two it fixes; `wide_expr` at
  1500 s wall and `wide_recv` at `lean::memory_exception` are the two
  heavyweight ones and belong to
  `bugs/FORMAL_x86_64_endtoend_chain_times_out_past_a_hundred_steps.md`).
* `test_formal_sweep_truth.py` is **not** a check for this class — it asks about
  `_FORMS`/`_SUCCS` key agreement, side-condition counts and wrapper coverage,
  and a row can be in both tables and still disagree with its lemma, which is
  what happened here.  The successor check in the coverage test is the check,
  and this doc is why it exists.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 formal/x86_64_model_coverage_test.py
$ python3 tools/memslot.py --gb 8 --label t -- python3 formal/x86_64_endtoend_test.py \
      formal/examples/shift_by_var.mojo formal/examples/shiftlr.mojo
```