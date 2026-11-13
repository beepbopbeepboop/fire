# Gate: formal-doc-truth is red on master

**Job:** `formal-doc-truth`. Filed by the full gate at `77937cfa22`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py formal-doc-truth`), then fix the cause.

## Gate ledger

- **Last known working:** none recorded (no earlier full-gate run covered this job)
- **First known not working:** not bisected: no earlier full-gate run had this job green
- **Seen red in the full gate at:** `77937cfa22` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-77937cfa.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-formal-doc-truth.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.

## Status (2026-11-12, branch work/bug-gate-formal-doc-truth-3)

- **Cause:** the census figures in `FORMAL.md` (§1, §2.2, §5, §6) and the quoted copies in `formal/build.py`, `formal/model/builtins.py` and `build_stdlib_dylib.py` are hand-typed. Every runtime-header change moves them, and nothing regenerates them. `test_formal_doc_truth.py` catches the drift, but while the job was `disabled=` nothing ran it.
- **Landed on this branch (base `0e616f372`):** the resync for `mojo_box_from_list`, `mojo_box_from_bytes`, `mojo_word_subscript` (936 / 428 / 508, header 826, `fire_runtime.c` 790 KB). On that base `python3 test_formal_doc_truth.py` gives PASS=441 FAIL=0. On current master `7848c87eb` it gives 15 FAILs, and master's `c1790b33c` already carries this same resync.
- **Still red on master `7848c87eb`:** the runtime moved again after `c1790b33c` (commits `364787542`, `9d97fb1d9` and later). Measured on master: `fire_runtime.h` declares 829 entries, `runtime_abi()` 939, word-shaped 430, non-word 509, `fire_runtime.c` 793 KB. `FORMAL.md` still says 936 / 428 / 508 / 826 / 790 KB.
- **Not done:** the doc stays open and the job stays `disabled=`. Deleting the doc needs a pass on master's tree. That pass is: `python3 test_runtime_header_scan.py --fix`, then fix the prose copies the `--fix` does not reach (§6 rows), then `python3 test_formal_doc_truth.py` → PASS, then remove `disabled=` and `git rm` this doc in the same commit, then `python3 tools/dangling_doc_refs.py --ratchet`.
- **Blocker for that pass:** it has to run against master's runtime, and this worktree's base predates it. Do it on a branch that contains master.
