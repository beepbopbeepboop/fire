# SUITE_silentnoop-part2: Make the `silentnoop` job pass

**Parent BUG:** bugs/hard/SUITE_silentnoop.md  
**Class:** mid

*Filed under `bugs/mid/` (the class this part argues it needs).*

`make check` reported the `silentnoop` job (test_silent_noop_iter.py) failing with
exit 1 / timeout. Part 1 established the failure mode; this part makes the job green.

## Failure mode (part 1, closed 2026-11-13)

NOT a timeout: `tools/suite.py silentnoop` runs 644 s against the registered
`timeout=1500` and still reports `1 passed, 1 failed`. Run direct, exactly two
cases fail and they share one build-time refusal:

```
FAIL  parameter_rebound_to_one_container_kind_is_not_multi_kind
FAIL  sorted_two_string_set_pinning
RuntimeError: parameter 'box' of 'pick' is passed a container at one call
site and a str or number at another, and the body uses it as a container;
the compiled path has no representation for that yet
```

Part 1's Escalation says a deep compiler defect gets its own doc rather than a
shallow fix here, so the defect (a parameter passed mixed literal container/str/
`None` kinds at different call sites and used as a container, refused at build
time) was filed and has been fixed: the per-kind literal clone pass now
recognizes `None` and container iteration in comprehensions/generators. Part 1
is deleted with its acceptance met.

## Scope

- Fix the container-kind handling the filed defect describes. Do NOT pin the
  refusal: `parameter_rebound_to_one_container_kind_is_not_multi_kind` is
  written as a pin for a fix (its own comment argues the name is rebound to
  ONE container kind and must not go through `_multi_kind_locals`), so an
  `expect_refusal_substring` marker here would hide the bug the case names.
- Keep the change minimal and behavior-preserving everywhere else.

## Not in scope
- Rewriting the silent no-op suite or its oracle.
- Deleting the parent bug doc (the parent stays at its class; it carries SPLIT).
- Plumbing or removing `_case`'s dead `expect_refusal_substring` parameter
  (recorded in the filed defect, not required for this job).


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
## Status

- **Landed 2026-11-14.** The job is green: `python3 tools/suite.py silentnoop`
  -> 2 passed, 0 failed. Part 1's refusal was already fixed (`e4a2cc2ed`);
  the remaining case, `zip_nested_tuple_target`, was a second and unrelated
  defect — `gen._zip_bind_slot` passed a Python int loop index into
  `_rt_call`, whose `_rt_args` joins its arguments with `', '.join(...)`
  while `_as_str` is deliberately identity, so the transactional zip branch
  swallowed `sequence item 1: expected str instance, int found` and fell
  back to the zero-iteration `mojo_unsupported_iter` path. Fixed in
  `6461fdf4c`. Per this doc's own Acceptance the parent is not deleted; its
  Status records the closure.
