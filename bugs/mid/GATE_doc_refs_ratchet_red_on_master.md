# GATE_doc_refs_ratchet_red_on_master: `dangling_doc_refs.py --ratchet` fails on master

**Area:** GATE (`doc-refs` job, which is in the `check` bucket).

**What I ran** (on the merge of master into
`work/fix-merge-bug-formal-formal-stack-floor-does-not-g`, which is master's tree
plus TASK.md):

    python3 tools/dangling_doc_refs.py --ratchet

**What I saw** (exit 1). Files that cite MORE deleted docs than
`tools/dangling_refs_baseline.py` allows:

- `test_formal_run.py`: 7 (baseline 4)
- `formal/model/methods.py`: 4 (baseline 1)
- `formal/model/types.py`: 3 (baseline 2)
- `bugs/formal/FORMAL_x86_64_end_to_end_proof.md`: 2 (baseline 0)
- `bugs/OPEN_WORK.md`: 8 (BARE baseline 6)

Plus two stale ledger entries that the ratchet says to drop:
`bugs/formal/FORMAL_pointer_value_model.md` (baseline 9, now 0) and `TASK.md`
(baseline 1, now 0).

**What I expected:** exit 0. The ratchet is supposed to fail only when a file GAINS
a citation, so a green master should stay green.

**Why I think it happened:** master deleted several formal docs (for example
`FORMAL_pointer_value_model.md`, `FORMAL_metamorphic_ledger.md`,
`FORMAL_model_fuzz_ledger.md`, `FORMAL_no_exceptions.md` changes) and cited
`formal/FORMAL_*.md` paths, but the baseline was not regenerated in the same
commits. The stack-floor doc is not the cause: its restore keeps it present on
this tree.

**Exact next step:** on master, run `python3 tools/dangling_doc_refs.py`
(no flag) and read which citations are new. Either rewrite each to name the
bug (symptom or fixing commit), or, if the citations are right, regenerate the
ceilings deliberately with `python3 tools/dangling_doc_refs.py --write-baseline`
and check the printed diff before committing. Do not raise a ceiling without
reading the diff.
