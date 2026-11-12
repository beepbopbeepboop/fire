# SUITE_silentnoop-part2: Make the `silentnoop` job pass

**Parent BUG:** bugs/hard/SUITE_silentnoop.md  
**Depends on:** bugs/SUITE_silentnoop-part1.md  
**Class:** mid

*Filed under `bugs/mid/` (the class this part argues it needs).*

`make check` reported the `silentnoop` job (test_silent_noop_iter.py) failing with
exit 1 / timeout. Part 1 establishes the failure mode; this part makes the job green.

## Scope
Act on the failure mode part 1 names:

- **If it is a timeout:** confirm the registration in `tools/suite.py` (`silentnoop`,
  `timeout=`) is sized for the job's measured wall time (the comment there records
  ~18m42s / 1122s alone, and `timeout=1500` as the fix). Align the registration or the
  `extra`/cache key so the job is not re-flagged red for a clock-bound reason.
- **If a specific case diverges:** fix the compiled path so the diverging case's
  stdout matches the CPython reference (or, if the construct is a known unmodelable
  one, pin the refusal by name in the case, per the file's own `expect_refusal_substring`
  mechanism). Keep the change minimal and behavior-preserving everywhere else.

## Not in scope
- Rewriting the silent no-op suite or its oracle.
- Deleting the parent bug doc (the parent stays at its class; it carries SPLIT).

## Acceptance
- `python3 tools/suite.py silentnoop` passes (its verdict is PASS, not TIMEOUT / FAIL).
- If a case was fixed: that case's narrow command
  (`python3 test_silent_noop_iter.py <case>`) passes, and the compiled stdout equals
  the reference CPython stdout.
- The parent doc is not deleted by this task; if this closes the parent, say so in the
  commit rather than removing the doc.

## Escalation
If part 1 shows the diverging case is a deep compiler defect (not a timeout, not a
one-line lowering fix), stop and file the specific defect as its own `bugs/<AREA>_<slug>.md`
(see `bugs/hard/` for the class) rather than forcing a shallow fix here.