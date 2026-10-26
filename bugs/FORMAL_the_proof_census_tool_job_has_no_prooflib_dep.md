# `formal-proof-census-tool` declares no `prooflib` dep, so its `lib/*.olean` assertion fails whenever it is scheduled before the shared library build

**Area:** FORMAL proof ratchet, `tools/suite.py`'s registration of
`test_formal_proof_census.py`. **Status: OPEN, measured 2026-10-13 on
`work/formal411-docs`.** The stale committed `fact` row that made this ratchet
red is FIXED — `f3833519` re-seeded it after `ffe27e1a` changed the example, and
the baseline is now 93 rows with 0 stale — so the bug doc for that row is
deleted. What remains, and what no other doc covers, is this separate
registration defect, which the same doc also recorded.

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_proof_census.py
...
FAIL: test_library_state_agrees_with_the_question_it_asks
AssertionError: ['IEEE754', 'ProofLib', 'X86', 'work', 'Refine', 'Contracts',
                'Peephole', 'Specs'] != []
  : lib/ is missing [...]; every key would miss and the report would be
    reporting the wrong thing
Ran 63 tests in 0.167s
FAILED (failures=1)
```

The `fact` row is no longer stale (the only other failure the old doc reported
is gone). This failure is the one that remains, and it is environmental: the
test asserts every `lib/*.lean` module appears in `lib/` as a built `.olean`,
and a fresh worktree has none until the `prooflib` build has run.

## Why it is a real gate red rather than a local artefact

`formal-proof-census-tool` is registered at `tools/suite.py:3802` with
`deps=['preflight']` and NOT `['prooflib']`:

```
test('formal-proof-census-tool', [PY, 'test_formal_proof_census.py'],
     mem='tiny', deps=['preflight'], ...)
```

The runner's `deps` are strict ("test names that must pass first"), so this job
waits only for `preflight`. It is in the `proofs` bucket
(`tools/suite.py:4280`), where `prooflib` runs as a dependency of the OTHER jobs
(`formal-call-proofgen`, `formal-proof-census`, …) but is not a dependency of
this one, so this job may be scheduled concurrently with — or before — the
`prooflib` build and fail on any machine whose `lib/*.olean` is not current.

The registration's own comment is stale about this and is the reason the dep was
never added: `tools/suite.py:4405` calls it "the cheap half (46 assertions, no
Lean, no build) that keeps that baseline honest". The file has 63 tests now and
one of them DOES read a build artifact, so the "no build" premise is false of it.

## The exact next step

Add `prooflib` to that registration's `deps`, exactly as its sibling
`formal-proof-census` already has it (`deps=['preflight', 'prooflib']`):

    deps=['preflight', 'prooflib'],

That is the class `CLAUDE.md`'s "Shared expensive dependencies: build once, then
depend on it" section describes: the `.olean` build is a shared artifact, and a
job that asserts on it must depend on it rather than race it. A skip-when-absent
is NOT the fix: the assertion is the only thing that checks the baseline's keys
against real built artifacts, so skipping would turn a real coverage check into
a silent hole.

**NOT taken here:** this is a `tools/suite.py` registry change, and this task's
rules forbid editing the gate registry ("Do not register anything in
`tools/suite.py` unless your task says so"). It is one word in one registration
for whoever owns the registry.

## Reproducing

    export PATH=/opt/homebrew/bin:$PATH
    python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_proof_census.py
    # 1 failure: test_library_state_agrees_with_the_question_it_asks (no lib/*.olean)
    # 0 failures where prooflib has run.
