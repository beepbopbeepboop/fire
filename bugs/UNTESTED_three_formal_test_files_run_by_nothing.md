# Three formal test files are run by nothing, and the estate check says so

Found 2026-09-30 while working `ab-native-tempfiles`. **Not caused by that
work, not fixed by it** — the runner change here was verified against a tree
where this was already red, and it is recorded because it is a real coverage
hole that a red test is currently reporting correctly and nobody is reading.

## What I ran

    $ python3 test_suite.py
    ...
    FAIL  the estate: every test file is run by something, or says why not:
          not run by any registered spec and not in UNREGISTERED:
          test_formal_os.py, test_formal_sys.py, test_struct_formal.py
    Results: 135 passed, 1 failed

`test_every_test_file_is_registered` is the check that found this, and it is
doing its job: these three files are in the repo, are named by no registered
spec in `tools/suite.py`, and have no entry in the `UNREGISTERED` table in
`test_suite.py` explaining why not.

Confirmed pre-existing, not introduced by the fan-out work in this branch: I
extracted `HEAD:test_suite.py` to a scratch file, ran it against the same tree
(so the same three files, plus my scratch copy, are undeclared), and got the
identical failure.

## Why it is there

All three arrived in the 2026-09-29 formal work — `43d0ca09` ("formal: move the
backend's own os/sys/struct modules out of the repo root") and `bba49bfa` ("os:
the `os` and `os.path` modules for the formal backend"). That commit added
tests; nothing added a spec naming them, and the `UNREGISTERED` table in
`test_suite.py` was not updated to say "not run yet". So the estate check has
been red on `main` since, and `suite-self-test` — which is in the `smoke`
bucket and therefore in every `gate` — is red for this reason alone.

Check: `rg -n "formal-os|formal-sys|struct-formal" tools/suite.py` finds
nothing; the registered formal tests are `formal`, `formal-run`,
`formal-call-proofgen`, `formal-dylib`, `formal-imports`, `formal-sweep`,
`formal-sweep-truth`, `formal-link-accounting`, `formal-runtime-link`,
`formal-x86*`. `test_formal_os.py` / `test_formal_sys.py` /
`test_struct_formal.py` are covered by none of them. Note `formal-imports`
(`test_formal_imports.py`) is a different file from `test_formal_imports`-style
naming and does not cover them either.

## Expected

Either

1. each of the three is registered in `tools/suite.py` (they are formal-backend
   tests, so `proofs` or `formal-sweep` is where they belong; `test_formal_os.py`
   and `test_formal_sys.py` at least need `deps=['preflight']`, and if they
   build real images they need `excl`/a memclass like the other formal tests), or
2. each gets an `UNREGISTERED` entry in `test_suite.py` saying why it is not
   run, which makes the estate check green while recording the gap honestly.

Option 1 is the one worth doing. The failure mode is the one CLAUDE.md calls
out for `coro`: a suite that reports 0/N because nothing runs the cases is
indistinguishable from a suite where the cases pass. These three are not even
being reported as 0/N — they are simply absent from the run.

## Exact next step

    rg -n "def main|unittest.main" test_formal_os.py test_formal_sys.py test_struct_formal.py

then add three `test(...)` registrations in `tools/suite.py` next to the other
formal entries, and confirm with

    python3 test_suite.py          # the estate check goes green
    python3 tools/suite.py --list  # each of the three is named

No gate is needed for the diagnosis; running the three suites themselves is a
`proofs`-bucket run, which is the integrator's.
