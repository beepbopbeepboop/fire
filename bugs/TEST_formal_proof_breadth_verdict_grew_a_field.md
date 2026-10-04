# `test_formal_proof_breadth.py` errors on `master`: `Verdict` grew a `cached`
# field and the classifier test still constructs it positionally

**Area:** FORMAL — `tools/formal_proof_breadth.py`'s `Verdict` against
`test_formal_proof_breadth.py`'s `TestClassifier`.
Found 2026-10-04 on `work/formal16-4` while landing the `hprior` sharing, by
running the proof-generation tests that generation touches. **NOT fixed here: the
area is `sweep14:proofs-breadth`'s** (`formal14-proofs-breadth`). Filed because
the failure is a `TypeError` at test-construction time, so the test that was
meant to say "the report must tell the two architectures apart" says nothing at
all, and a `TypeError` in a census tool reads like a broken tool rather than a
stale call.

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_proof_breadth.py
test_the_report_says_when_the_two_architectures_mean_different_things
  (TestClassifier) ... ERROR
TypeError: Verdict.__new__() missing 1 required positional argument: 'cached'
  File "test_formal_proof_breadth.py", line 481, in test_the_report_says_when_the
    _two_architectures_mean_different_things
  V("x.py:1:f", "arm64", "codegen-refused",
    "'A' has no home: this module declares no module-level name",
    "build", 0.1, None, 0),

Ran 16 tests … FAILED (errors=1)
```

The other 15 pass. `Verdict`'s field list ends in `cached`, which is what
`formal/lean.py`'s verdict cache needs to report honestly ("this verdict was
replayed"), and the test still passes `0` in the last position — which is
`n_sorries` under the old field order and `None` under the new one, so the call
is off by one field rather than by a wrong value.

**Next step:** add the missing argument at the call site (or construct the row
with keywords, which is what stops the next added field from breaking it again),
and check whether any other caller of `Verdict` in `tools/formal_proof_breadth.py`
or its test is positional — a field added to a dataclass that is built
positionally in tests is a break waiting for the next one. `grep -n "V(" tools/
formal_proof_breadth.py test_formal_proof_breadth.py` is the whole inventory.