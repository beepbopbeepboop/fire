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
   not merely absent from FAILED.

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

`tools/verify_landed.py::passed_jobs` already reads the log for PASS lines;
the same reading, extended to the requested job's verdict, is what both sites
need.

## Cost of not fixing it

`c0182fd3` filed 50 `bugs/gate-bootstrap-stage2-dumps:*` docs from one red
producer, all with a fabricated bisect, and one worker per doc was dispatched
to re-derive the same cascade. Every one of those workers pays a
`python3 tools/suite.py bootstrap-stage2-dumps` run to discover the SKIP.

## Exact next step

1. `tools/verify_landed.py`: add `job_verdict(job, sha)` next to
   `passed_jobs`, parsing `build/suite.log` for the job's own verdict
   (`[ i/n] ok|skip|DISABLED|FAIL|TIMEOUT|RESOURCE <job>`), and have
   `job_is_red_at` return a tri-state. `bisect_job` stops with
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
