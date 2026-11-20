# Suite: module-loader-stdlib job is a no-op (the test file has no __main__)

**Job:** `module-loader-stdlib` (`tools/suite.py`: `test('module-loader-stdlib', [PY, 'test_module_loader_stdlib.py'], mem='tiny', ...)`).

## What I ran

Landing work/bug-gate-red-recover-land-2026-11-02-par (2026-11-20) needed an
existing test that covers `module_loader.py` (the `.py` export scanner I
changed). The registered job for that file is `module-loader-stdlib`, whose
command is `python3 test_module_loader_stdlib.py`.

Ran: `python3 tools/memslot.py --gb 8 --label module-loader-stdlib -- python3 test_module_loader_stdlib.py`

## What I saw

Exit 0, zero output — no PASS line, no test line, nothing. The file defines
two pytest-style test functions (`test_stdlib_checkout_prefers_new_modular_
when_both_exist`, `test_call_initialized_global_export_takes_callee_return_
type`, the latter taking the `tmp_path` fixture) and has NO `if __name__ ==
'__main__':` block, so `python3 file.py` only executes the top level (imports
+ defs) and exits 0 without running either test. The job therefore always
passes and has never run either of its two tests. It was registered by the
estate audit ("registered by the estate audit (every test file runs)") —
"runs" in the sense that the interpreter exits 0.

Ran the same two tests through pytest instead:
`python3 -m pytest test_module_loader_stdlib.py -v` → 2 passed (0.08 s).
Both pass with the imported-global fix landed; the no-op is about the job,
not about the tests.

## What I expected

`python3 test_module_loader_stdlib.py` to run its two test functions and
report, like the other `reg-*` pins, so the job has teeth.

## Exact next step

Either (a) add a `__main__` block that runs both functions, substituting a
tempdir path object for `tmp_path` (the only fixture used;
`test_formal_reproducible.py` is the other pytest-style file in the tree and
already does this: it HAS a `__main__`), or (b) register the job as
`[PY, '-m', 'pytest', 'test_module_loader_stdlib.py']` — but suite.py's
drivers are `cmd`/`mem`/`make` with no pytest driver, so (a) is the pattern
the tree already uses. After landing, confirm the job prints two test lines
and still passes. Note this is the same no-op class CLAUDE.md warns about
("a stale test ... is a coverage hole"); an audit for other registered jobs
whose file has test functions but no `__main__` would find whether this is
the only one (I checked only the two `tmp_path` files; a whole-tree scan of
`test(` registrations against `__main__` presence is the general form).

Filed 2026-11-20 by the worker landing work/bug-gate-red-recover-land-2026-11-02-par.
Not fixed here: touching `tools/suite.py` or this test file's runner is
outside that landing's scope (and the suite-self-test gate lane is claimed
by another worker).
