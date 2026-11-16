# SUITE: the doc-refs ratchet is red on master (a land Status line cites 5 now-deleted docs)

**Job:** `doc-refs` (registered in `tools/suite.py`, bucket `check`; the `expect=` marker it
carried 2026-11-09 was dropped when the citation campaign landed, so this red is currently
UNDECLARED in the everyday bucket).

## What I ran

`python3 tools/dangling_doc_refs.py --ratchet` on clean master (`80f4ebe4c`, 2026-11-15,
worktree work-7372, `git status --short` empty).

## What I saw

    ratchet: 1 file(s) cite MORE deleted docs than tools/dangling_refs_baseline.py allows:
      bugs/mid/LAND-codegen-nested-bracket-generic-call-4.md: 5 (baseline 0)

All 5 sit on ONE line (line 36), the auto-generated Status line of that doc, the
"Uncommitted entries: ... Commit what belongs to the change, discard the rest." line.
Of the doc names it lists, 5 no longer exist (now deleted by their own fixes):

- GATE_selfhost_closure_cannot_compile.md (now deleted)
- SUITE_comptime_bracket_params_stale_link_mode_message.md (now deleted)
- SUITE_doc_refs_ratchet_two_preexisting_gains.md (now deleted)
- CODEGEN_simd_and_array_values_erase_to_int64-part4.md (now deleted; lived in hard/)
- COMPILE_FAIL_Tools_cases_generator_analyzer-part3.md — the Status line cites its old
  mid/ spelling, which is gone; the file itself still exists, under that name, in hard/
  (the line's own rename note `mid/ -> hard/` is what the citation predates)

Verified against `existing_docs()` after each deletion; the other names on that line
(`OPEN_WORK.md`, `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md`, ...) still
exist, which is why the count is 5 and not 12.

## What I expected

The ratchet green on clean master, as it was when the `expect=` marker was dropped.

## Why I did not fix it

The offending line lives in `bugs/mid/LAND-codegen-nested-bracket-generic-call-4.md`, claimed by
`bug:LAND-codegen-nested-bracket-generic-call-4` (a separate live worker per
`tools/control.py claims`). Editing it is that lane's work, so this doc is filed per the
one-doc-per-bug rule and its fix lands in that lane (or the next claim of the same area).
Searching `bugs/` first: no open doc covers this red — the now-deleted doc that covered
an earlier, DIFFERENT set of ratchet gains is gone with that campaign.

## Exact next step

In the owning branch (or a new claim of `bug:LAND-codegen-nested-bracket-generic-call-4`):
rewrite line 36 of that doc to name the BUGS the uncommitted entries were filing (the
symptom, or the commit that fixed them), not the doc paths — the rewrite is the sanctioned
fix, per the ratchet's own message ("The fix for one of these is to name the BUG rather
than the doc"). Do NOT bank a ceiling with `--write-baseline`: that would freeze 5 stale
citations in `tools/dangling_refs_baseline.py` forever instead of removing them. Then
`python3 tools/dangling_doc_refs.py --ratchet` must be green, and THIS doc is deleted in
that commit. (If instead the landing process should not emit doc paths into Status lines at
all, that generator lives in the landing tooling — say so in the fix commit and note it
here first.)
