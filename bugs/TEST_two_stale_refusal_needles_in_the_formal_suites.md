# TEST: two stale refusal needles in the formal suites, and the check that would have caught them

**Area:** the test suites' own needles — `test_formal_run.py` and
`test_formal_x86_64_parity.py`, one row each. **Not** the compiler: in both cases
the refusal is correct, identical on both machines, and worded more accurately
than the needle expects.
**Status:** OPEN, measured 2026-10-04 on `work/formal26-unicode` at `f9ffd4c0`.
Both pre-existing on that branch's base — the measurement that proves it is §2.

## 1. What was run

```console
$ python3 test_formal_run.py            # 982 rows
  FAIL  constr_refuse_an_undeclared_base_by_name: --backend=arm64 refused, but
        not with the expected words "derives from 'Widget', which this image
        does not declare": …
formal run: PASS=981 FAIL=1

$ python3 test_formal_x86_64_parity.py  # 63 rows
  FAIL  a_subscript_on_a_type_value_faulted_identically: --backend=arm64
        refused, but not with the expected words 'is a TYPE value': …
x86-64 formal parity: PASS=62 FAIL=1 (63 cases)
```

## 2. Both are the NEEDLE, not the compiler — measured, not argued

**Neuter the branch's only two additions** — `formal/build.py`'s
`M.publish_non_ascii_strings(M.non_ascii_strings_in(stmts))` and its
`M.clear_non_ascii_strings()`, replaced with `pass` and then restored — and the
first row fails with the same message:

```console
$ python3 test_formal_run.py constr_refuse_an_undeclared_base_by_name
  FAIL  constr_refuse_an_undeclared_base_by_name: … same message …
formal run: PASS=36 FAIL=1
```

Neither program contains a non-ASCII string literal, so neither could have
reached the encoding block's condition at all.

### The two, and what each is actually asserting

| row | file | its needle | what the build says |
|---|---|---|---|
| `constr_refuse_an_undeclared_base_by_name` | `test_formal_run.py` | `derives from 'Widget', which this image does not declare` | *"constructing MyErr with 1 argument(s) does not match its fields (no fields at all), and MyErr declares no `__init__` for it to call instead"* |
| `a_subscript_on_a_type_value_faulted_identically` | `test_formal_x86_64_parity.py` | `is a TYPE value` | *"is a struct field declared to hold a TYPE TAG — a hash of a type's name — which is a number, and a tag has no elements and no count"* |

**The first is the more interesting one, because the new message may well be the
BETTER refusal and the old needle may have been pinning a worse one.** The case
is `class MyErr(Widget)` with a `Widget` this image does not declare, and what
the build now says is about the thing that actually stops the program: the class
has NO FIELDS, so there is nowhere to put the one argument `MyErr("the message")`
passes, and no `__init__` to call instead. Both readings are true — the undeclared
base and the empty field list — and a reader told only the first has to work out
the second themselves before they can act. **So this one is a judgement about
which fact the message should lead with, not a stale string to fix**, and the
next step says so.

**The second is a stale string.** Its two sibling rows in the same table
(`subscript_of_a_dtype_slot_refused_identically` and
`subscript_of_a_constructor_established_dtype_slot_refused_identically`) already
assert the current wording, and the three programs differ in ONE thing — how the
field is established — which is the difference those three rows exist to hold
down. Two of the three agree; the third kept an earlier wording, and its own
comment still describes the defect it was created for accurately.

## 3. The next step, and the thing worth more than either fix

1. **The dtype needle: one string.** Change `'is a TYPE value'` to the wording
   its two siblings assert.
2. **The undeclared-base needle: decide which fact leads.** Either restore the
   undeclared-base clause into `formal/model.py`'s construction refusal — it is
   the more specific diagnosis and a reader who is told only "no fields" does not
   learn that the class was never going to work — or accept the field-list
   reading and change the needle. Whichever is chosen, it belongs to
   whoever owns `construction_mismatch_refusal`, and it is a one-line change
   either way.

3. **The thing worth more than both: a refusal needle is a CONTRACT, and nothing
   checks it.** A reworded message silently invalidates the needle in the one
   place where the reword cannot be noticed by reading the program — the program
   still refuses, for the right reason, by a different sentence. Two mechanisms
   would have caught both of these at the moment they were introduced, and
   neither is in place:
   * a needle set SHARED between sibling rows rather than spelled once per row
     (the dtype table's three rows would then have moved together); and
   * a check that **every needle in these files is a substring of some message
     the tree actually produces** — the property `test_formal_doc_truth.py`
     already enforces for the documents, with no equivalent for the suites.

   The second is the one to build. It is a walk of the refusal tables plus a
   build per distinct program, which is what these suites already do, so it
   costs one pass and it converts "someone reworded a message" from a silent
   loss of coverage into a FAILURE that names the row.