# Three reds in `test_formal_call_proof_gen.py` are stale rows after the CMP/SP fix, and one of them cannot be read

**Area:** `test_formal_call_proof_gen.py` (`TestRegister31`,
`TestTheRecursionFamiliesStillGenerate`) against `lib/ProofLib.lean`'s
`CMP Xn, Xm (register)` arm and `formal/arm64_proof_gen.py`'s `_step_rhs`.
**Status: OPEN, filed 2026-10-05 on `work/formal27-2` at `20f12f68`, measured
pre-existing on that tree and on `master` (`ccb157ed`). NOT fixed here — the
rows encode a reading of the architecture that its own table no longer supports,
and that reading is not mine to change.**

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_call_proof_gen.py
Ran 86 tests in 133.980s
FAILED (failures=3)
  FAIL  TestRegister31.test_the_generator_keeps_its_own_spelling_and_why
  FAIL  TestRegister31.test_the_model_reads_rn_as_sp_exactly_where_the_assembler_allows_it (form='cmp sp, x16')
  FAIL  TestTheRecursionFamiliesStillGenerate.test_the_one_that_refuses_says_why (stem='sum_range')
```

`formal-call-proofgen` is a registered gate job with `deps=['preflight',
'prooflib']`, so these are a real red and not a scratch observation.

**Proved pre-existing**: the same three, with the same subTest parameters, on a
tree with this branch's whole diff reverted (`git apply -R` of
`git diff ccb157ed..HEAD`, then re-applied):

```console
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_call_proof_gen.py TestRegister31 TestTheRecursionFamiliesStillGenerate
Ran 6 tests in 0.990s
FAILED (failures=3)
```

## Why they are stale: the CMP/SP change was correct and the table was not

`lib/ProofLib.lean`'s `CMP Xn, Xm (register)` arm (0xeb000000) now reads `Rn`
with `arm64_reg` — the ZERO register for `Rn == 31` — and its comment carries
the measurement that decided it:

> `as` accepts the text and encodes `Rn = 31`, which SUBS (shifted register)
> reads as XZR. So `cmp sp, x16` is a comparison against ZERO with the SP
> spelling ignored, and the model was computing a comparison against the stack
> pointer. Measured against the CPU (`tools/formal_model_fuzz.py`): `cmp sp,
> x16` with sp = 0 and x16 = 0 sets Z=1 on the hardware and N=1 on the model.

`bugs/FORMAL_model_fuzz_ledger.md`'s table carries the same row as **FIXED**,
and the sibling row it was measured beside — a NEG reading as `sp - Xn` where
the assembler wrote `-Xn`, deleted with its fix in `471e0e5b` — is that
measurement. So the LIBRARY is right, and these two rows still assert the
pre-fix world:

1. **`test_the_model_reads_rn_as_sp_exactly_where_the_assembler_allows_it`** is
   built on a two-valued classification — "the assembler accepts `sp` in `Rn`"
   versus "31 is the ZERO register here" — and `SP_IN_RN_FORMS` puts `cmp sp,
   x16` in the first group. **The architecture has a third value**: the assembler
   accepts the text and the hardware ignores the SP spelling. A form that
   assembles is not thereby a form that reads SP, and this row's own oracle
   (`_assembler_accepts`, one `clang -c` per form) cannot see the difference
   because it only asks whether the text assembles. The repair needs a third
   column and a different oracle for it — a case that runs the word, which is
   what `tools/formal_model_fuzz.py` already does.
2. **`test_the_generator_keeps_its_own_spelling_and_why`** asserts
   `_step_rhs(0xeb1003ff, 6)` is the CMP spelling with no register write:

   ```
   some { s with nzcv := arm64_subs_flags (arm64_reg 31 s) (arm64_reg 16 s) }
   ```

   and the generator emits the uniform SUBS form instead:

   ```
   some { (arm64_set_reg 31 s (arm64_reg 31 s - arm64_reg 16 s)) with
          nzcv := arm64_subs_flags (arm64_reg 31 s) (arm64_reg 16 s) }
   ```

   **The two are the same term**: `arm64_set_reg 31 s v = s` by its own
   definition (`lib/ProofLib.lean:1516-1528`, the catch-all case is `_ => s`), so
   the generated step lemma still closes by `exact`ing the library's — which is
   what this row's docstring says the whole asymmetry is about. What changed is
   the generator's spelling, deliberately (its own comment: "`arm64_set_reg 31 s
   v = s`, so this is the CMP spelling exactly and `subs xd, xn, xm` (which
   `encode_subs_xd_xn_xm` emits) with it"), and the row still pins the old
   literal text. So this one is a string assertion that outlived a change that
   made it unnecessary, not a disagreement.

   Note what is NOT wrong here, because it looks wrong at a glance: the
   generator's `arm64_reg 31 s` for `Rn` AGREES with the library now. Before the
   CMP fix it would have been the disagreement.

## The third one cannot be read, which is a finding of its own

`TestTheRecursionFamiliesStillGenerate::test_the_one_that_refuses_says_why`
fails for `stem='sum_range'`, and **its assertion message embeds an entire
generated Lean proof** — 39 `have hN : … := by native_decide` blocks and their
`all_goals simp [...]` tails, thousands of lines, in one `assertIn`. Reading it
costs more than the bug is worth: the first thing any reader does with a red in
this file is open the log, and this row fills it.

The repair is the message shape, not the row: a refusal assertion should carry
the needle it wanted and a BOUNDED window of the text (the first and last line
around the miss), the way `test_refusal_taxonomy.py` truncates its samples at a
clause boundary. Whether the row also needs re-pointing is not determinable
without reading the needle, which the flood hides.

## The exact next step

1. Decide the third column for `SP_IN_RN_FORMS` and say it in the table's own
   comment: *assembles and reads SP* / *assembles and reads ZERO* / *refused*.
   `cmp sp, x16` is the second, and the neg row (`add w0, sp, #16`) is a fourth
   case worth naming — an SP DESTINATION, which the current table has no column
   for either.
2. Re-point row 2's assertion at the uniform spelling, or add the `rd == 31`
   special case to `_step_rhs`. The second is a behaviour change to a generator
   every arm64 proof goes through and buys nothing (the terms are equal), so the
   first is the honest repair — with the `arm64_set_reg 31 s v = s` fact quoted
   in the row, since that is the whole argument.
3. Bound row 3's assertion message (needle + a window), then re-run and read what
   it says. Do that one FIRST: it is the row that makes the other two readable,
   and it is a two-line change.
4. `python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_call_proof_gen.py`
   is the whole check (134 s here, and it TYPECHECKS the generated proofs, so it
   is also the thing that would catch a wrong reading of the architecture in
   step 1).

## Whose

The CMP/SP fix is recorded FIXED in `bugs/FORMAL_model_fuzz_ledger.md`
(`formal27-4` holds that doc's claim) and was measured by the same session that
fixed the neighbouring NEG/shadowed-register defect (`formal25-2`, whose own doc
is gone with its fix).
Neither test row was updated with it. Neither claim is mine, and step 1 is a
statement about the architecture rather than a mechanical repair, which is why
this is filed rather than applied.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_call_proof_gen.py
$ python3 -c "
import sys; sys.path.insert(0, '.')
import formal.arm64_proof_gen as G
print(G._step_rhs(0xeb1003ff, 6))"
$ grep -n "arm64_set_reg 31\|_ => s" lib/ProofLib.lean | head -3
```
