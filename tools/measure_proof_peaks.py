#!/usr/bin/env python3
"""Measure the peak memory of the three memory-ceiling x86_64 endtoend proofs.

    python3 tools/measure_proof_peaks.py --dry-run     # print the argv per stem, start nothing
    python3 tools/measure_proof_peaks.py               # run every stem, record into the JSON

For each stem in `STEMS` the harness generates the termination proof the way
`formal/x86_64_endtoend_test.py` does (`formal.build.compile_formal` followed by
`emit_terminates`), then runs `lean` on it with an EXPLICIT Lean ceiling of
`MEM_LIMIT_MB` (through `formal.lean.lean_flags(mem_mb=...)`, never by editing
`LEAN_MEMORY_MB`). The `lean` process is wrapped in `tools/memslot.py --gb 8`,
which reserves 8 GB from the machine-wide budget before starting and kills the
job if its process tree goes over 8 GB.

The peak is read from the wrapper's own record of the run: memcap prints
`memcap: done, peak X GB` (or `peak observed before the kill: X GB` on a breach),
and `tools/procrun.memcap_verdict` parses that line. It is the footprint memcap
measured, not an estimate, and it is converted to whole MB. A run whose output
carries no peak line is an error, not a zero: the harness refuses to record a
figure it did not measure.

A stem that the ceiling kills, or that Lean refuses (`excessive memory
consumption`), is recorded with its real returncode and the peak as reached.

Each record is `{stem, returncode, peak_rss_mb, wall_s, lean_version,
mem_limit_mb, ran_at}`, keyed by stem, in `formal/proof_memory_peaks.json`.
`lean_version` and `ran_at` let a later reader tell whether the numbers are stale.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import formal.lean as L  # noqa: E402
import procrun            # noqa: E402

STEMS = ("wide_expr", "wide_recv", "list_literal_index")
MEM_LIMIT_MB = 8192
MEMSLOT_GB = 8
RECORD = os.path.join(ROOT, "formal", "proof_memory_peaks.json")
RECORD_FIELDS = ("stem", "returncode", "peak_rss_mb", "wall_s",
                 "lean_version", "mem_limit_mb", "ran_at")


def job_argv(stem, lean, proof_path):
    """The full command for one stem: the memslot wrapper around `lean`.

    The argv is built here and nowhere else, so the dry run and the real run
    cannot disagree about what is started.
    """
    wrapper = [sys.executable, os.path.join(HERE, "memslot.py"),
               "--gb", str(MEMSLOT_GB), "--label", "measure-%s" % stem, "--"]
    return wrapper + [lean] + L.lean_flags(mem_mb=MEM_LIMIT_MB) + [proof_path]


def validate_record(key, rec):
    """Raise ValueError unless `rec` is a well-formed record for stem `key`."""
    if not isinstance(rec, dict):
        raise ValueError("record %r is not an object" % key)
    missing = [f for f in RECORD_FIELDS if f not in rec]
    if missing:
        raise ValueError("record %r lacks %s" % (key, ", ".join(missing)))
    if rec["stem"] != key:
        raise ValueError("record %r names stem %r" % (key, rec["stem"]))
    peak = rec["peak_rss_mb"]
    if not isinstance(peak, int) or isinstance(peak, bool) or peak < 0:
        raise ValueError("record %r: peak_rss_mb must be a non-negative int, got %r"
                         % (key, peak))
    if rec["mem_limit_mb"] != MEM_LIMIT_MB:
        raise ValueError("record %r: mem_limit_mb must be %d, got %r"
                         % (key, MEM_LIMIT_MB, rec["mem_limit_mb"]))
    rc = rec["returncode"]
    if rc is not None and (not isinstance(rc, int) or isinstance(rc, bool)):
        raise ValueError("record %r: returncode must be an int or null" % key)
    if not isinstance(rec["wall_s"], (int, float)) or isinstance(rec["wall_s"], bool):
        raise ValueError("record %r: wall_s must be a number" % key)


def _generate(stem):
    """The termination proof text for one stem, as `x86_64_endtoend_test` emits it."""
    import formal.x86_64_endtoend_test as E
    path = os.path.join(ROOT, "formal", "examples", stem + ".mojo")
    E.B.compile_formal(path, prove=False, check=False, arch="x86_64")
    return E, E.emit_terminates(path)


def measure(stem, lean):
    """Run one stem under the ceiling and return its record."""
    E, text = _generate(stem)
    E.ensure_lean_ready()
    env = dict(os.environ, LEAN_PATH=E.LEAN_PATH)
    with L.scratch_dir("measure-" + stem) as d:
        proof = os.path.join(d, stem + ".lean")
        with open(proof, "w") as f:
            f.write(text)
        argv = job_argv(stem, lean, proof)
        with tempfile.TemporaryFile(mode="w+b") as out:
            started = time.monotonic()
            proc = subprocess.Popen(argv, cwd=d, env=env,
                                    stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=subprocess.STDOUT,
                                    start_new_session=True)
            try:
                rc = proc.wait(timeout=L.PROOF_WALL_S)
            except subprocess.TimeoutExpired:
                procrun.kill_group(proc)
                rc = None
            wall = time.monotonic() - started
            out.seek(0)
            text_out = out.read().decode("utf-8", "replace")
    _breached, peak_gb = procrun.memcap_verdict(text_out)
    if peak_gb is None:
        raise RuntimeError(
            "%s: the memslot/memcap run printed no peak line (rc=%r, %.1fs); "
            "refusing to record a figure that was not measured" % (stem, rc, wall))
    rec = {
        "stem": stem,
        "returncode": rc,
        "peak_rss_mb": int(round(peak_gb * 1024)),
        "wall_s": round(wall, 2),
        "lean_version": L.lean_version(lean),
        "mem_limit_mb": MEM_LIMIT_MB,
        "ran_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }
    validate_record(stem, rec)
    return rec


def write_records(recs):
    """Merge `recs` (stem -> record) into RECORD, atomically, keeping other stems."""
    data = {}
    if os.path.exists(RECORD):
        with open(RECORD) as f:
            data = json.load(f)
    for stem, rec in recs.items():
        validate_record(stem, rec)
        data[stem] = rec
    tmp = RECORD + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, RECORD)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="print the argv each stem would run; start no process")
    ap.add_argument("stems", nargs="*", choices=STEMS, default=list(STEMS),
                    help="which stems (default: all three)")
    a = ap.parse_args(argv)
    lean = L.find_lean(ROOT) or "lean"
    if a.dry_run:
        for stem in a.stems:
            print("%s: %s" % (stem, " ".join(
                job_argv(stem, lean, "<generated %s.lean>" % stem))))
        print("(dry run: nothing started, nothing written)")
        return 0
    if not L.find_lean(ROOT):
        print("lean not found (see ./lean-toolchain)", file=sys.stderr)
        return 1
    recs, failed = {}, []
    for stem in a.stems:
        try:
            recs[stem] = measure(stem, lean)
            print("%s: rc=%r peak=%d MB wall=%.1fs"
                  % (stem, recs[stem]["returncode"], recs[stem]["peak_rss_mb"],
                     recs[stem]["wall_s"]))
        except Exception as exc:  # noqa: BLE001 -- reported, and the run fails
            failed.append(stem)
            print("%s: NOT RECORDED: %s" % (stem, exc), file=sys.stderr)
    if recs:
        write_records(recs)
        print("wrote %s" % os.path.relpath(RECORD, ROOT))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
