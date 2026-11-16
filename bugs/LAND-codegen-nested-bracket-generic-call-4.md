# Land: should finished branch fix-merge-bug-codegen-nested-bracket-generic-call-4 land?

**Branch:** `work/fix-merge-bug-codegen-nested-bracket-generic-call-4` (task `fix-merge-bug-codegen-nested-bracket-generic-call-4`; if the branch is gone, its tip is `refs/archive/work/fix-merge-bug-codegen-nested-bracket-generic-call-4`).
**Age:** last commit 2026-11-13, first unlanded commit 2026-11-13; 11 commit(s) ahead of master, 625 behind it; task started 2026-11-13 15:40:25
**Original work:** Branch work/bug-codegen-nested-bracket-generic-call-4 (a finished, verified worker branch; original task: An earlier attempt left 10 commit(s) on branch work/fix-merge-bug-codegen-nested-bracket-gener
**Original claims:** bug:CODEGEN_nested_bracket_generic_call_stubs_to_zero

This branch holds finished work that is not on master, and nothing is landing or continuing it. Sort it out:
decide what it is worth now, then act on the decision. Use your judgment; landing is one outcome of three.

Assess first (record the findings in Status):
- Does the branch's own test still fail on master and pass on the branch? If master already passes it, the bug
  may be fixed another way.
- Does master now solve the same problem differently or better (same files rewritten, the doc's subject gone,
  the function replaced)? Then the branch is obsolete.
- Is the change still correct and wanted against today's master, or was it written for a design that moved on?
- How stale is it, and how much of it merges cleanly?

Then do ONE of:
- **LAND**: start from master, bring in the NEWEST branch named in Status (`git merge <it>`, or cherry-pick), resolve
  conflicts keeping both sides' intent, make the result coherent, run the narrow tests that cover the files
  involved plus the branch's own tests, and commit.
- **ADAPT**: land only the part that is still right, rewritten against master, and say what you left out and why.
- **DROP**: land nothing. The reason goes in the commit message that deletes this doc.
In every case, `git rm` this doc in your commit (then `python3 tools/dangling_doc_refs.py --ratchet`). If the
original bug is still open, leave its own doc alone.

## Done when

A commit exists that records the decision: the change (LAND/ADAPT) or the reason it was dropped
(DROP), and this doc is gone.

## Status
- 2026-11-15 10:31:54: DONE, but its worktree /Users/mrs/net/chatgpt/claude/work-7059 has uncommitted work (last commit 2026-11-13, first unlanded commit 2026-11-13; 11 commit(s) ahead of master, 625 behind it; task started 2026-11-13 15:40:25)
  Branch: work/fix-merge-bug-codegen-nested-bracket-generic-call-4
  Uncommitted entries: CLAUDE.md, FORMAL.md, bugs/CODEGEN_nested_bracket_generic_call_stubs_to_zero.md, bugs/GATE_selfhost_closure_cannot_compile.md, bugs/OPEN_WORK.md, bugs/SUITE_comptime_bracket_params_stale_link_mode_message.md, bugs/SUITE_doc_refs_ratchet_two_preexisting_gains.md, bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64-part4.md, bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64.md, bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md, bugs/mid/COMPILE_FAIL_Tools_cases_generator_analyzer-part3.md -> bugs/hard/COMPILE_FAIL_Tools_cases_generator_analyzer-part3.md, bugs/hard/COMPILE_FAIL_Tools_cases_generator_analyzer.md .... Commit what belongs to the change, discard the rest.
