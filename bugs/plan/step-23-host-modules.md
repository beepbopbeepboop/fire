# plan/step-23: the Mojo-side host modules

**Source:** `bugs/FORMAL_known_limits.md` §6.3 and §6.4
(`not-answerable/host-import` is 166 files, 160 actionable, `os` 79).
**Master plan:** `doc/finish-formal.md` §"Step 23".

## Goal

These are not limits: "a module a Mojo-side implementation could in principle
provide". `formal/hostmods/` already carries `os`, `json`, `hashlib`, `math`,
`time`, `pathlib`, `fnmatch`, `re`, `struct`, `shlex`, `stat`, `glob`,
`tempfile`, `textwrap`, `random`, `shutil`, `posixpath`, `sys`, `io` and the
`@admitted` contracts.

## What to add

- Grow `formal/hostmods/os` (the 79) and the next-largest modules, each function
  with its own failure convention (see step-26) and an `@admitted` contract only
  for the host's ANSWER.
- `formal/admitted.py`'s rule is exacting: a contract may constrain the host's
  answer and may not assert anything about mechanism. `test_formal_admitted.py`'s
  `SCOPE_PROBES` and `truth` group are the instrument; a FALSE contract is the
  worst outcome (`FORMAL_trust_audit_2026-10-04.md`).
- Rank the modules by file count from a fresh sweep and work the top down.

## Structure-only rule

This step is open-ended. Each function answers CPython differentially on both
backends, or refuses with the host limit named. Do not invent a status where
CPython has no failure to report.

## Files

`formal/hostmods/**`, `test_formal_hostmods_*.py`,
`test_formal_admitted.py`, `test_formal_hostmods_census.py`.

## Verification

The hostmods suites, differential against CPython on both backends;
`test_formal_admitted.py`; a sweep delta.

## Done when

- [ ] each targeted module's functions answer CPython or refuse with the host
      limit named
- [ ] the sweep class count falls
- [ ] admitted contracts are true of the real host

## Dependencies

step-26 (the convention) for new modules.
