# Gate: rthdrscan is red on master

**Job:** `rthdrscan`. Filed by the full gate at `a69c095251`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py rthdrscan`), then fix the cause.

## Gate ledger

- **Last known working:** none recorded (no earlier full-gate run covered this job)
- **First known not working:** not bisected: no earlier full-gate run had this job green
- **Seen red in the full gate at:** `a69c095251` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-a69c0952.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-rthdrscan.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.

## Done when

`python3 tools/memslot.py --gb 8 --label rthdrscan -- python3 tools/suite.py rthdrscan`
reports `1 passed, 0 failed` (the job itself, not a subset of it), with the
census the tree quotes matching the live scan — `test_runtime_header_scan.py`'s
own checks (`test_every_declaration_is_seen` and
`test_the_quoted_census_is_the_live_census`) are the evidence for the figures.
Then this doc is deleted in the same commit (`git rm`, then
`python3 tools/dangling_doc_refs.py --ratchet`).

## Status

- **2026-11-12 (bug-gate-rthdrscan-3):** the earlier attempt on
  `work/bug-gate-rthdrscan-2` had already deleted this doc; that deletion was
  not proof, so the doc is back on this branch until the named test in
  `## Done when` is run and green here. What the earlier attempt landed: the
  822 -> 826 rung in `test_runtime_header_scan.py` (four declarations that
  landed unledgered: `mojo_box_from_bytes`, `mojo_word_subscript`,
  `mojo_box_from_list`, `mojo_csv_reader_vf`), `--fix` rewriting the quoted
  figures (total 932 -> 936, word 426 -> 428, box 506 -> 508) in FORMAL.md,
  formal/build.py, formal/model/builtins.py and build_stdlib_dylib.py,
  `disabled='bugs/gate-rthdrscan.md'` removed from the job's registration, and
  the doc deleted. Measured on this tree: `python3 test_runtime_header_scan.py`
  reports 60 passed, 0 failed, and `python3 tools/suite.py rthdrscan` reports
  1 passed. The `**Skipped:**` line above describes the state at filing time;
  the registration no longer carries `disabled=`. The doc is deleted again in
  the commit where the named test is green.
