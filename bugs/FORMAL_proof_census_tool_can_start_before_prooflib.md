# `formal-proof-census-tool` declares `deps=['preflight']`, but one of its tests needs `lib/*.olean`, which is what `prooflib` builds

**Area:** FORMAL, `tools/suite.py`'s registration of
`test_formal_proof_census.py`. **Status: OPEN.** Found 2026-10-07 on
`work/formal132-docs` while checking the stale `fact` row (that row is fixed; its
doc is deleted), and it is the residual of that doc's own second failure note.

## What it is

`test_formal_proof_census.py::TestCommittedBaseline::test_library_state_agrees_with_the_question_it_asks`
asserts that `lib/` has no missing `.olean`:

```python
    def test_library_state_agrees_with_the_question_it_asks(self):
        import formal.lean as L
        absent, stale = C.library_state(L, os.path.join(HERE, "lib"))
        self.assertEqual(absent, [],
                         f"lib/ is missing {absent}; every key would miss and "
                         f"the report would be reporting the wrong thing")
```

The registered job is `test_formal_proof_census.py`:

```python
test('formal-proof-census-tool', [PY, 'test_formal_proof_census.py'],
     mem='tiny', deps=['preflight'],
     extra=['test_formal_proof_census.py', 'tools/formal_proof_census.py',
            'tools/formal_proof_census_baseline.json', 'formal/admitted.py',
            'formal/lean.py'],
     desc='the proof-regression ratchet: ranked statuses, no phantom timings, '
          'an honest committed baseline')
```

and it is in the `proofs` bucket, beside the Lean-driving jobs that DO declare
`deps=['preflight', 'prooflib']` (`formal-proof-census`, `formal`,
`formal-call-proofgen`, …). So under a parallel `proofs` bucket this cheap job
can be admitted before the shared `.olean` build, and its `library_state` case
then fails on a machine that has not built the library — a red that is about the
schedule and not about the baseline.

## What I ran, what I saw

On a warm tree the file is green (`Ran 61 tests … OK`). On the tree this was
found on, with no `prooflib` yet run, the same file reported

```
FAIL: test_library_state_agrees_with_the_question_it_asks
AssertionError: Lists differ: ['IEEE754', 'ProofLib', 'X86', 'work', 'Re[35 chars]ecs'] != []
First list contains 8 additional elements.
  : lib/ is missing ['IEEE754', 'ProofLib', 'X86', 'work', 'Refine',
    'Contracts', 'Peephole', 'Specs']; every key would miss and the report
    would be reporting the wrong thing
```

— every `LIBRARY_MODULES` name reported absent, because `prooflib` had not run
in that run's window. Once the library was present the file was `OK`, which is
the measurement that says the failure is ordering and not the assertion.

## The exact next step

One word in `tools/suite.py`: add `'prooflib'` to that registration's `deps`.

```python
test('formal-proof-census-tool', [PY, 'test_formal_proof_census.py'],
     mem='tiny', deps=['preflight', 'prooflib'],
     ...)
```

`prooflib` is in no bucket and is cheap on a warm tree (the CAS publishes the
27 MB `.olean`), so the dep costs `check`-class jobs nothing on the integrator's
tree and removes a real race. **Not done here:** this session is a light worker
and `tools/suite.py` is a shared file (a sibling branch is editing it), so the
one-line change is filed rather than made.
