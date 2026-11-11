# ORCHESTRATION_doc_deleted_on_branch_lands_unverified

## Summary
A worker can delete a bug doc on its branch and report DONE, and nothing checks that the doc's named test passes.
The branch is a normal landing candidate, so landing it would close the bug on master with no proof.

## Evidence
- `work/bug-codegen-class-rebind-late-binding-4223`: one commit that deletes the class-rebind doc (since retired),
  state `exited-ok`, verdict DONE, NOT held. The doc had no named test, and the bug was not fixed.
- Round 31 of the same chain also lacks the doc on its branch: every round deleted it.
- The planner (`task_text.py`) now treats a deleted doc as "not proof", but landing has no such check.

## Repro
Make a branch that deletes an open bug doc and commit it. Run the integrator: the deletion is a normal candidate.

## Status
Open. Not started. Landing needs to refuse a doc deletion unless the doc's named Done-when test is part of the
same commit and passes.

## Done when
Landing refuses a branch whose only effect is deleting an open bug doc, unless its Done-when test passes, with a test.
Then delete this doc in the same commit.
