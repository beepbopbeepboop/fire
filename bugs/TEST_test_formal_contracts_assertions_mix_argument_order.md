# TEST_test_formal_contracts_assertions_mix_argument_order: half of `test_formal_contracts.py`'s `check()` rows cannot fail

**Area:** `test_formal_contracts.py`, `check()` at the top of the file. **Found
2026-10-13** while landing the ladder's sign-bit cancellation
(`lib/work.lean::work_u64_sign_zero_of_le`).

## What I ran and what I saw

The file's helper is

```python
def check(ok, what, detail=""):
    RESULTS.append((bool(ok), what))
    if not ok:
        print(f"FAIL  {what}" + ...)
    ...
```

so the convention is `check(CONDITION, LABEL)`, and `main` counts

```python
passed = sum(1 for ok, _ in RESULTS if ok)
```

Measured, in one line:

```console
$ python3 -c "import test_formal_contracts as T; T.check('LABEL', False); print(T.RESULTS[-1])"
(True, False)
```

**A row written `check("the_thing_is_right", condition, detail)` stores
`(True, condition)`** — the string label becomes `ok`, so the row can never
print `FAIL` and `main` counts it as passed whatever `condition` was. Wrapping
`check` to report the argument TYPES over the non-Lean run:

```
{'str': 165, 'bool': 175, 'other': []}
```

**165 of the 340 rows pass a string first** (the label, i.e. the `what`
parameter) and are dead; the other 175 pass a condition first and are live. The
Lean rows (`test_lean_closes_a_true_contract_and_refuses_a_false_one`) are in
the live half, which is why the file's only real signal today is the Lean one.

## What it hides, measured with the order corrected

Running the same `ALL` list with `check(label, condition)` gives **2 rows that
were passing and are in fact red**:

* `a_bare_requires_is_refused` — the row asserts `"took the clause" in str(exc)`
  but the reader says `"takes the clause"`; the assertion has a typo and the
  message is right. One-character fix.
* `the_reader_reads_floordiv_as_the_IRs_division` — the row expects a 3-tuple
  `(Op.CMP, "==", (Op.ARITH, "/", ...))`; the reader emits
  `('cmp', '=', ('var', 'result'), ('arith', '/', ...))`, and has for as long
  as the row has existed. The row's shape is stale (the `==` spelling and the
  third element), not the reader. Fix the expectation to the emitted shape.

(The ladder rows this session touched — `the_script_spellings_one_*`,
`the_EMITTED_theorem_uses_the_listed_rungs` — were also dead and were fixed in
the same commit as this filing; they pass.)

## Why it is filed and not fixed here

The fix is a 165-call-site change, and it is safe but NOT a find-and-replace:
the first argument of a dead row is a string and the first argument of a live
row is a condition, so the repair is "for every `check(...)` whose first
argument is a string literal or f-string, swap the first two arguments". That
touches almost every row in the file, and doing it in the same commit as a
one-lemma ladder change would put 165 unrelated edits between the reader and
that change. It is the class of change that wants its own commit and its own
review, which is why it is a doc rather than part of the ladder fix.

## The exact next step

1. Rewrite the 165 dead calls to `check(condition, label, detail)` — the order
   the helper already implements and the order the 175 live calls already use.
   A robust way to find them, rather than reading 340 calls, is to wrap the
   helper, run `ALL`, and record `type(arg0)` per call site (the measurement
   above); a source pass keyed on "first argument is a `Str`/`JoinedStr` node"
   is equivalent.
2. Then fix the two rows in "What it hides": the `took`/`takes` typo, and the
   stale IR shape in `the_reader_reads_floordiv_as_the_IRs_division`.
3. `python3 test_formal_contracts.py` must then report those as `FAIL` before
   the fixes and `0 failed` after — i.e. its exit status should finally depend
   on its rows, which is the whole of what is broken.
4. Consider the same helper elsewhere: `grep -n 'def check(' test_formal_*.py`
   is the census, and a second file with this helper and this mix would explain
   any other always-green row.

The file is registered in no `tools/suite.py` bucket today, so the gate has
never seen it go red either way; it is run by hand and by the doc-pinning habit
of whoever touches `formal/contracts.py`.
