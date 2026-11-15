# Clear bootstrap gate OFF entries in gates.json (replan part 3 of 5)

## Goal

Update `tools/gates.json` so `bootstrap-stage1-transitive`, `bootstrap-stage2-dumps`, and `bootstrap-stage3-dumps` are no longer turned OFF by any entry.

In particular: remove or narrow the entry keyed `^(bootstrap\-stage1\-transitive|bootstrap\-stage2\-dumps|bootstrap\-stage3\-dumps)$` (the one documented by `bugs/hard/GATE_red_recover-land_2026-11-02.md`), and ensure the 23-job OFF entry documented by `bugs/mid/GATE_recover_land_remainder.md` no longer matches `bootstrap-stage1-transitive` (narrow that pattern to drop the bootstrap name, or split/delete the entry as appropriate) without re-enabling other jobs that entry legitimately owns. Use `python3 tools/control.py gate on/off` as the writer; do not hand-edit the JSON except as `control.py` requires.

## Acceptance

- `python3 tools/control.py gate list` shows no OFF entry whose pattern matches `bootstrap-stage1-transitive`, `bootstrap-stage2-dumps`, or `bootstrap-stage3-dumps`.
- The 23-job OFF entry for `bugs/mid/GATE_recover_land_remainder.md` remains valid (still names its doc and still owns the jobs it is meant to own, minus `bootstrap-stage1-transitive`).
- `python3 test_gates_off_entries_name_a_doc.py` still passes (every OFF entry names an existing doc).

## Done when

File: `tools/gates.json`
Command: `python3 -c "import json, re, sys; d=json.load(open('tools/gates.json')); pats=[p for p in d.get('off',{}) if re.search(p,'bootstrap-stage1-transitive') or re.search(p,'bootstrap-stage2-dumps') or re.search(p,'bootstrap-stage3-dumps')]; sys.exit(1 if pats else 0)"`
