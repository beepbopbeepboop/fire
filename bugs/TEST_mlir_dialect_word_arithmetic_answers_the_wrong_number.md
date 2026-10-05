# `a_dialect_arithmetic_lowers_when_its_operand_declares_a_word` answers `-4` where the row pins `-3`

**Area:** TEST (a case pinning a number, against a lowering). Found 2026-10-04 on
`work/formal26-float` while running `test_formal_mlir_precedence.py` as a
regression check for the binary64 work. **NOT FIXED, and not mine** — MLIR dialect
arithmetic is outside the `project26:float` claim. Filed because it is the FOURTH
pre-existing red this session attributed to itself and then had to prove was not
its own, and because it is the only one of the four that is not a stale NEEDLE: it
is a wrong NUMBER, which is the outcome that file's own failure text calls "the
worse outcome, not a refusal".

## What was run

```
$ python3 test_formal_mlir_precedence.py
  FAIL  a_dialect_arithmetic_lowers_when_its_operand_declares_a_word:
        stdout '-5 -4 0 -2\n1 0 1\n' != '-5 -3 0 -2\n1 0 1\n' — a wrong value is
        the worse outcome, not a refusal

MLIR refusal precedence: PASS=31 FAIL=1
```

Five of the six printed numbers agree and the second does not: `-4` where the row
pins `-3`.

## Why this is not the binary64 change

Measured, the same way as the other three. `formal/model.py`,
`formal/types.py`, `formal/arm64_codegen.py` and `formal/x86_64_codegen.py` — the
whole write set of the float change — were restored from the commit before it and
the single case re-run:

```
$ python3 test_formal_mlir_precedence.py a_dialect_arithmetic_lowers_when_its_operand_declares_a_word
  FAIL  a_dialect_arithmetic_lowers_when_its_operand_declares_a_word: (identical)

MLIR refusal precedence: PASS=0 FAIL=1 (1 case)
```

Byte-for-byte the same wrong number on the tree the float work started from.

## Why the binary64 work is the wrong place to look, specifically

The change touches three things a dialect-arithmetic case could plausibly reach:
`ValueKinds` (a `FLOAT_KIND` vocabulary added), `declared_type_kind` (a
`float_names` branch), and `_kind_of_elements` (an optional resolver for NAME
elements). None of them can produce a `-4` from a `-3` for a case whose operand
declares a WORD, and none of them is reached by an MLIR dialect spelling — those
lower through `model.mlir_*`, which the change does not touch. The measurement
above settles it rather than the argument.

## What it actually is

Two possibilities and they are distinguishable in one run:

- **The row is stale** — the dialect's word-typed arithmetic has always answered
  `-4` and the `-3` was a hand-written expectation. Then the fix is to the row, and
  the case is asserting a number rather than a semantic.
- **The lowering is wrong** — the row is right and a dialect operation computes
  something other than the operation the source spells. Then this is a REAL
  numerical defect on the formal path and belongs with
  `formal/model.py`'s `mlir_*` tables, which is a different owner than a test row.

Which one it is turns on whether the `-3` was ever produced by a build of this
program. `git log -S` over the case's own text, and reading what
`model.mlir_operand_clause` computes for a word-typed operand, answers it: a case
whose expected value no build has ever produced is a transcription, and one that a
build produced and then changed is a regression with a commit to bisect.

The five agreeing numbers matter as much as the sixth: a single wrong value in a
six-number output is a WIDTH or a SIGN on one operation, not a broken dialect
lowering. If it is the width, `-3` truncating toward zero from `-3.x` is the
reading; if it is the sign, the source spells a negation the dialect path drops.

## The exact next step

1. Read the case's source out of `test_formal_mlir_precedence.py` and build it
   with `python3 fire.py build --formal --no-prove` on BOTH backends.
2. Diff the two backends' answers before anything else. This suite exists because
   they can disagree, and a case that pins one constant across both cannot see
   that — if only one architecture says `-4`, it is a per-backend lowering bug and
   the OTHER number is the one that is wrong, which no single-constant row would
   ever report.
3. Then either correct the row (transcription) or file the numerical defect
   against the dialect tables (regression), with the bisect range from step 2.