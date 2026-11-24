# Gate: bootstrap-stage1-transitive is red on master

**Job:** `bootstrap-stage1-transitive`. Created when branch `master` (task `master`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `master`: reproduce it there (`python3 tools/suite.py bootstrap-stage1-transitive`), then fix the cause. Do not skip or mark the test.

## Status (2026-11-20): partial fix landed, not verified

**Landed on master** (`2a5b22587`, merged as `ef9a22c6f`), without any checks, at the owner's request:

- **Cause 1, false positive (`fire.py`).** The closure check flagged any closure whose text contained the phrase
  "unavailable in compiled mode". `fire.py` carries that phrase as a string literal, so every closure matched. The
  check now matches a real stub definition (`{ mojo_print ((char *)"<name>: unavailable in compiled mode`).
  `test_dump_full_reports_closure_stubs.py` passed for this change before the merge.
- **Cause 2, real stub (`mojo/backend_gimple/module_gen.py`).** The util table emitted an unconditional `sort` weak
  stub into every module, so every artifact carried one whether or not anything called `sort`. That entry is removed.

**Not verified, and still open:**

- The unimported `sort(p)` build: it must still link. The prelude-sort work (`bugs/hard/CODEGEN_prelude_sort_is_not_resolved.md`)
  depends on this exact behaviour, so the two must be checked together.
- `python3 tools/suite.py bootstrap-stage1-transitive` has not been re-run on master since the merge. This doc stays
  until it is green. Delete it in the same commit that shows it green, then run `python3 tools/dangling_doc_refs.py --ratchet`.
- Measured after the fix (`2a5b22587`, on the fix's own branch): `compile_stdlib.py` reports `FAILED: 0 (0 expected,
  0 unexpected)` with no skips; `test_dump_full_reports_closure_stubs.py` passes; a program calling unimported `sort(p)`
  carries exactly one weak `sort` stub, in its own TU, and a program with no `sort` call carries none.
- The link of the unimported `sort(p)` program now succeeds: `fire.py build` links it, and the binary prints
  `sort: unavailable in compiled mode` and exits 0. That is the documented prelude-sort behaviour (an honest weak stub
  until `std.builtin.sort` compiles), not a regression.
- Still NOT done: the named job `tools/suite.py bootstrap-stage1-transitive` has not been rerun green on master. The
  doc stays until it is. Two earlier `fire.py build` runs (pids 36526 and 72861) are still alive; they are no longer
  needed for this check, and their owner should stop them.

## Gate ledger

- **Last known working:** `7b29b4f689` integrate bug-interp-positional-bracket-on-bound-m
- **First known not working:** `1010277e6f` Merge remote-tracking branch 'origin/master'
- **Seen red in the full gate at:** `77c157bb07` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-77c157bb.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-bootstrap-stage1-transitive.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
