# SUITE: the gate ledger cannot tell "did not run" from "passed", so it invents last_good and first_bad

Found 2026-11-21 while clearing the gate doc for
`bootstrap-stage2-dumps:class_jit.mojo` (deleted in the previous commit, whose
message records that item's c0182fd3 red as the disabled-producer cascade fixed
by `416ed660c`). The ledger's per-item numbers for that whole family are
fabricated, and they are what dispatched fifty workers after one root cause.

## What I ran

    python3 - <<'EOF'
    import json, subprocess, os
    cd = subprocess.check_output(['git','rev-parse','--git-common-dir'], text=True).strip()
    json.load(open(os.path.join(cd,'control','gate_ledger.json')))['jobs']
    EOF
    git show --stat 828e356ae        # "gate ledger: 50 red, 0 recovered at c0182fd365"
    git log -1 --format=%B 828e356ae | head -20
    python3 tools/suite.py bootstrap-stage2-dumps:class_jit.mojo ; echo "exit=$?"

    python3 - <<'EOF'
    import sys; sys.path.insert(0, 'tools')
    import gate_ledger as G
    st = {"jobs": {}}
    G.reconcile(st, "c0182fd3...", ["bootstrap-stage2-dumps:class_jit.mojo"], [],
                {"sha": "d0c0a1cc...", "failed": ["bootstrap-stage2-cc"]})
    st["jobs"]["bootstrap-stage2-dumps:class_jit.mojo"]["last_good"]
    # -> 'd0c0a1cc...', although that run's log SKIPped the item
    EOF

## What I saw

1. `control/gate_ledger.json` gives all fifty
   `bootstrap-stage2-dumps:<file>.mojo` entries the SAME
   `last_good: d0c0a1cc57` and `first_bad: 0b0316114e`, while their producer
   `bootstrap-stage2-cc` at that same run had `last_seen_bad: d0c0a1cc57`
   (i.e. the producer FAILED in the run recorded as the items' "last good").
   A dependent cannot be green while its producer is red at the same sha.
   Commit `828e356ae`'s own message prints the fifty identical
   `first bad 0b0316114e, last good d0c0a1cc57` lines.

2. `python3 tools/suite.py bootstrap-stage2-dumps:class_jit.mojo` ->
   `suite.py: no such bucket or test: 'bootstrap-stage2-dumps:class_jit.mojo'`,
   exit 1. A fanout ITEM is not selectable; only the parent is.

## Expected

A job that did not run (SKIP) is not a pass and not a red: it is NO EVIDENCE.
It must not become anyone's `last_good`, and a probe that cannot run the job
must stop the bisect instead of answering "red" (or "green") for every commit.

## The sites, and why each fabricates a number

1. **`tools/gate_ledger.py::reconcile`** — a newly red job with no `last_good`
   takes `prev["sha"]` when it is "not in `prev['failed']`". A job that SKIPped
   in the previous run (the normal state of every dependent of a disabled
   producer, and of every platform-gated test) is in neither `failed` nor
   `passed`, so it is taken as green. That is how all fifty items inherited
   `last_good: d0c0a1cc57` from a run whose gate log shows
   `skip bootstrap-stage2-dumps:<item>` and a red producer. It should require
   the job to be in `prev`'s PASSED set (or carry an explicit "unknown" flag),
   not merely absent from FAILED. Measured on the real function: with the
   previous run's `failed` naming only the producer, the item comes back newly
   red with `last_good` = that run's sha — the same value a genuine previous
   PASS produces, so nothing downstream can tell the two apart.

2. **`tools/verify_landed.py::job_is_red_at`** (used by `bisect_job`) and
   **`tools/autointegrate.py::probe`** — both decide from an exit code alone:
   `returncode != 0` is "red", and `probe` accepts `rc == 0`. For a fanout item
   the suite rejects the name (exit 1 at EVERY commit, see measurement 2), so
   `first_bad` collapses to the first commit after `last_good` — exactly
   `0b0316114e` for all fifty. In the other direction, a selection that SKIPs
   behind a disabled dep exits 0 (`python3 tools/suite.py
   bootstrap-stage2-dumps` -> 0, `1 skipped, 2 disabled`), so `probe` scores a
   right-track ... for a job that never ran. Both need a tri-state read of the
   run: PASS / RED / NO EVIDENCE, where the evidence comes from the suite log's
   per-job verdict line (`[ n/m] ok|skip|FAIL ...`), not from the process exit
   code.

`tools/verify_landed.py::passed_jobs` is NOT the working reader this was first
described as — it matches `^\[\s*\d+/\d+\] PASS\s+(\S+)` in `build/suite.log`,
while the runner's tag for a pass has been `ok` since the one runner landed
(`tools/suite.py:6473`, `_TAG = {PASS: 'ok', ...}`). Measured on this worktree's
own log, which contains
`[ 76/101] ok       bootstrap-stage1-dumps:class_jit.mojo`:

    $ python3 -c "import sys;sys.path.insert(0,'tools');import verify_landed as V;print(V.passed_jobs('.'))"
    []

3. **`tools/verify_landed.py::passed_jobs`** — the dead reader is a site of its
   own, and the first one to fix: `reconcile`'s `passed` loop is fed from it
   (`verify_landed.py:248`), so no job has ever been recorded as recovered and
   every `last_good` the ledger holds came from the fabrication in site 1 rather
   than from a run that saw the job pass. The tri-state reader below must share
   this one parser; a second regex over the same log is how the two answers
   drifted apart in the first place.

## Cost of not fixing it

`c0182fd3` filed 50 `bugs/gate-bootstrap-stage2-dumps:*` docs from one red
producer, all with a fabricated bisect, and one worker per doc was dispatched
to re-derive the same cascade. Every one of those workers pays a
`python3 tools/suite.py bootstrap-stage2-dumps` run to discover the SKIP.

## Exact next step

1. `tools/verify_landed.py`: add `job_verdict(job, sha)` next to
   `passed_jobs`, parsing `build/suite.log` for the job's own verdict
   (`[ i/n] ok|skip|DISABLED|FAIL|TIMEOUT|RESOURCE <job>`), and fix
   `passed_jobs` itself to the runner's `ok` tag (site 3), so both readers share
   one parser. Have `job_is_red_at` return a tri-state. `bisect_job` stops with
   `bisect_note = "job did not run at <sha>; cannot bisect"` on no-evidence
   rather than picking a commit.
2. `tools/autointegrate.py::probe`: require a PASS verdict for every requested
   job, not `rc == 0`.
3. `tools/gate_ledger.py::reconcile`: take `prev["sha"]` as `last_good` only
   when the job is in the previous run's PASSED set; otherwise leave
   `last_good` None and say so in `bisect_note`.
4. Tests in `tools/test_gate_ledger.py`: a skipped-in-prev job gets no
   `last_good`; a job whose probe is not selectable records
   `did not run`, not a `first_bad`. A test in `tools/test_integrate_probe_loop.py`
   for a probe whose jobs all SKIP (it must be PROBE REFUSED/NO EVIDENCE, never
   "right track"). Both use a synthetic `build/suite.log`, no gate run.

## Relationship to the archived work-7804 note (2026-11-21)

A parallel lane (work-7804, branch
`work/fix-gate-bootstrap-stage2-dumps-bootstrap-validate-mojo`) reached the same
three findings independently while chasing the same fifty-doc fanout, in a note
named `SUITE_gate_ledger_phantom_bisect_and_per_item_docs` on that branch. It
was never landed and is now dropped: sites 1-3 above cover its first three
sections in more detail, `SUITE_fanout_item_red_is_misreported` covers the
item-name half, and the false "Skipped" paragraph and the silent `set_disabled`
no-op are fixed on master: `tools/gate_ledger.py::report_text` emits that
paragraph only for the `disabled=` marker the ledger actually wrote (`marked`)
and names the parent fanout for an item that has no registration of its own,
pinned by `tools/test_gate_ledger.py::ReportText`. Its only other change
edited the per-item doc `gate-bootstrap-stage2-dumps:bootstrap-validate.mojo`,
which master deleted (8d5b63bb1) once 416ed660c made a disabled producer's
dependents SKIP instead of dying on the missing artifact. So nothing in it is
missing from this tree, and this paragraph is the record of the drop.
