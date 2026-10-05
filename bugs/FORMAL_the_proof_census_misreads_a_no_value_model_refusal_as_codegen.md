# FORMAL: the proof census files `_no_value_model`'s refusal as `codegen-refused`, so the largest class is under-counted

**Area:** `tools/formal_proof_breadth.py` (`run_item`'s two refusal arms) and
`formal/build.py` (`compile_formal`'s `except NotImplementedError` re-wrap).
**Status: OPEN, measured, PRE-EXISTING on `master` (`86af1b44`) — not caused by
any of the six branches this merge brought together.** Found 2026-10-05 while
running the narrow `test_formal_*.py` files that merge touched.

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_proof_breadth.py
FAIL: test_a_call_to_a_second_function_is_a_proof_refusal (__main__.TestClassifier.test_a_call_to_a_second_function_is_a_proof_refusal)
FAIL: test_a_list_literal_is_a_proof_refusal_not_a_crash (__main__.TestClassifier.test_a_list_literal_is_a_proof_refusal_not_a_crash)
  AssertionError: 'codegen-refused' != 'proof-refused'
Ran 25 tests in 18.917s
```

Both reds are **byte-identical on `master`**, which is why this is a pre-existing
defect and not a merge artifact. On `master` the file is 22 tests; this merge's
branches took it to 25 and the two reds came with it unchanged:

```console
$ (in a `git archive master` tree) python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_proof_breadth.py
Ran 22 tests in 17.785s
FAILED (failures=2)
```

## What the refusal actually is

Probed through the census's own `run_item`, on both architectures, so the
classification is read rather than inferred:

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 -   # B.run_item directly
list-literal   arm64    -> codegen-refused  detail='no proof was generated: the semantic model has no value for something in this program, and'
list-literal   x86_64   -> admitted        detail=''
second-call    arm64    -> codegen-refused  detail='no proof was generated: the semantic model has no value for something in this program, and'
second-call    x86_64   -> admitted        detail=''
```

So the backend refused NOTHING. `--no-prove` builds and runs the same bytes on
arm64, and x86-64 admits the same two programs outright — which is what the
first failing case asserts in its own second line. The refusal is the proof
generator's, it NAMES itself (`formal/arm64_proof_gen.py::_no_value_model`), and
the census is filing it in the wrong column.

## Why: the wrapping arm cannot be reached

`tools/formal_proof_breadth.py::run_item` has two refusal arms, and they are
ordered so that the second is dead for this shape:

1. line 969, `except (FB.CodegenError, FB.FormalBuildError)` → `_refusal_class`
   → `codegen-refused` (or the `refused-builtin` refinement);
2. line 987, `except NotImplementedError` → `proof-refused if
   _PHASE.generate_entered`. Its own comment is right that only the generator
   raises this.

But `formal/build.py` line ~1907 catches the generator's `NotImplementedError`
and **re-raises it as a `FormalBuildError`**:

```python
raise FormalBuildError(
    f"no proof was generated: the semantic model has no value for "
    f"something in this program, and refusing is what it does "
    f"rather than state something false about the source. …") from e
```

By the time `run_item`'s handler sees it, it is arm 1. `_PHASE.generate_entered`
is set and correct (the wrap at line 904 sets it and deliberately does not clear
it on the way out), so the information the classifier needs EXISTS and is thrown
away one arm too early.

This is the same `codegen-refused` column the file's own line 1051 warns about
("toward `codegen-refused`, which is the class a reader must not under-count")
and the same one its line 573 calls "a `codegen-refused` row about a name rather
than about the proof layer".

## Exact next step

One arm, in `tools/formal_proof_breadth.py::run_item`. Do **not** un-wrap
`formal/build.py`'s `FormalBuildError` — that re-wrap is right (it is what turns
a generator traceback into `build: <message>` for `fire.py`, which the comment
there documents), and removing it would give every driver a traceback again.

Instead make arm 1 consult the flag it already has:

```python
except (FB.CodegenError, FB.FormalBuildError) as e:
    if _PHASE.generate_entered and str(e).startswith(
            "no proof was generated: the semantic model has no value"):
        # `formal/build.py` re-raises the generator's own `NotImplementedError`
        # as a `FormalBuildError` (its `except NotImplementedError` around
        # line 1907), so this shape arrives as arm 1 and cannot reach arm 2
        # below. The re-wrap is right — it is what `fire.py build --formal`
        # prints — so the fix is here and not there.
        return verdict("proof-refused", str(e), phase="generate")
    ...
```

Prefer a marker the wrapper controls over a prefix match on prose: the exact
next step is to give `formal/build.py`'s `FormalBuildError` an attribute (say
`proof_refused = True`) set only on that one `raise`, and have arm 1 test
`getattr(e, "proof_refused", False)`. A prefix match on an English sentence is a
second thing to re-word.

Then re-measure the census: `test_a_call_to_a_second_function_is_a_proof_refusal`
is the largest single cause in the census (4 of 22 reachable items), and if both
reds move to `proof-refused` the `codegen-refused` count falls — which is the
outcome, and the direction to check, because this class is the one a reader must
not under-count.

## Why it is not fixed here

`formal/arm64_proof_gen.py` and the proof-breadth census are another lane's
(`formal28-2` / `formal28-6-r2` hold the arm64 proof-gap claims;
`formal28-6-r2`'s own `tools/formal_model_fuzz.py` edits show the tooling there
is live). This merge's claim is `merge:gate29` and its subject is six branches
landing together. Filing is the honest move per the merge's own rules, and the
two reds are pre-existing so nothing this merge did caused them.