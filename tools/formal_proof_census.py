#!/usr/bin/env python3
"""A RATCHET on the Lean side of the formal path: every `formal/examples`
program, and a committed record of what its proof did last time.

    python3 tools/formal_proof_census.py                  # measure + compare
    python3 tools/formal_proof_census.py --write-baseline # bank what it measured
    python3 tools/formal_proof_census.py --list           # the corpus, no builds
    python3 tools/formal_proof_census.py --only const2,udivmod
    python3 tools/formal_proof_census.py --remeasure --only udivmod \
        --write-baseline        # MEASURE udivmod's cost and bank just that row

THREE FLAGS, and the two that are not obvious
---------------------------------------------
`--only` narrows the WORKLOAD; `--write-baseline` MERGES what it measured over
the rows already in the file rather than replacing them, and drops only a row
whose example has been deleted. That pair is the documented way to re-seed one
row — `--only <stem> --remeasure --write-baseline` is how a row written from a
replayed verdict gets a measured time without re-elaborating the other 51, and a
replacing write would answer it by leaving the committed baseline a census of
one example.

`--remeasure` bypasses the proof-verdict cache (`formal/lean.py`'s CAS) for the
duration of the run, so every example it covers is elaborated for real and its
time is measured. It is the only way to put a timing into a baseline written on
a warm tree — and a warm tree is what every repeat run of this repository is,
because a verdict is content-addressed on the proof's exact bytes. It costs a
Lean run per example (seconds to ~300 s each, up to ~4 GB peak), which is why it
is a flag and not the default.

A replayed write KEEPS the timing a row already had, because an unmeasured
value is not a change; see `write_baseline`, which is where that and the merge
are one decision.

WHAT THIS IS, and what the two neighbours are not
-------------------------------------------------
`tools/formal_sweep.py` answers "does this FILE build", deliberately with
`--no-prove`, and says in its own docstring why: proof generation and Lean
typechecking are "a separate, much narrower capability with their own failures
— they are exercised by `test_formal.py` / `make check-formal`, not by this
sweep". So the Lean side exists, and `test_formal.py` exercises it.

**What exists nowhere else is a RECORD.** `test_formal.py` prints today's
pass/fail per example against a hand-maintained `EXPECTED_FAILURES` dict and
throws the rest away: no wall time, no CPU time, no peak memory, no count of the
`native_decide`/`bv_decide` sites the proof rests on, and no history. So a proof
that got five times slower, or a proof that started admitting holes, or a proof
that started needing 3 GB, is invisible — the suite stays green and prints
`PASS`. `tools/formal_proof_breadth.py` answers a different question again (how
much of THIS REPOSITORY's own source the proof layer can prove), over a sample
that moves whenever the tree's file list does, so its numbers are not a
before/after against anything.

This one is the ratchet: a fixed corpus (`formal/examples/*.mojo`, the whole
directory, 52 programs), one measurement per program, one committed JSON
baseline, and a comparison that **fails when a program gets worse** — a status
that moved down the rank below, a `sorry` or an admitted contract that appeared
or multiplied, or a proof that now costs more than twice what it cost.

THE MEASUREMENT, and why it is `compile_formal(prove=True, check=True)`
----------------------------------------------------------------------
It is exactly the call `fire.py build --formal` makes — `formal/build.py::
compile_formal` with `prove=True, check=True`, so the code generator runs, the
proof generator runs, and Lean is asked about the proof through
`formal/lean.py::run_lean`'s three bounds (wall, whole-tree CPU,
`maxHeartbeats`). Every Lean run in this tree goes through that launcher
(`formal/lean.py`'s module docstring), and this tool adds no launcher of its
own and no bound of its own. The per-proof bound is therefore `PROOF_WALL_S` /
`PROOF_CPU_S` = 1500 s, which `formal/lean.py` derived from the measured
slowest legitimate proof (`udivmod.mojo`, 297.8 s wall / 219.2 s CPU) with a 5x
margin, and which is deliberately NOT env-raisable. **`-j` is what bounds the
wall clock of the whole census, not this flag**, which is why the default is 1.

**The three figures are read out of the run, not estimated.** `run_lean` already
measures wall, whole-tree CPU and peak RSS for every `lean` it launches and
returns them on `LeanRun`; this tool records that `LeanRun` and reports its
fields. The instrumentation is a wrapper around `formal.lean.run_lean` (one
wrapper, installed once, per-thread) that keeps the runs belonging to the
thread measuring the current example. It filters to PROOF runs structurally —
a proof check is the one that hands `lean` a single `.lean` argument, while a
library build hands it `-o <tmp> <source>` and `lean_version` hands it
`--version` — so no message is matched and no message can drift.

Statuses
--------
One per example, and each is a different KIND of fact, so they are ranked
rather than alphabetised (`STATUS_RANK`):

| status | what it means | rank |
|---|---|---|
| `proved` | the proof typechecked, **zero** admitted holes, **zero** admitted host contracts | 0 |
| `admitted` | typechecked, and the file's `@admitted` host contracts are in it | 1 |
| `sorry` | typechecked and it admits `sorry` — the count is in `n_sorries` | 2 |
| `lean-rejected` | a proof was emitted and Lean did not accept it | 3 |
| `refused` | the backend or the proof generator refused the program (`reason` says which, `phase` says where) | 4 |
| `crash` | something was RAISED that is not a refusal — a bug | 5 |
| `too-large` | Lean's own memory ceiling refused the proof (`(kernel) excessive memory consumption detected`) | 6 |
| `bound-exceeded` | `run_lean` killed it — **not a verdict on the proof** | 6 |

`too-large` and `bound-exceeded` SHARE rank 6 on purpose. Both are the absence
of a measurement rather than a fact about the proof (`formal/lean.py` is
insistent that a breach is "NOT a verdict on the proof"), so a program moving
from one to the other has not regressed and must not be reported as having
done so — while a program moving from `proved` to either of them has, because a
proof that used to check no longer does. Same rank, same rule, both directions.

`admitted` and `sorry` are recorded as separate COUNTS as well as statuses,
because they are two ratchets rather than one: `n_sorries` may only go down and
`n_admitted` may only go down, and a program that stays at rank 2 while its
`sorry` count goes 2 → 4 has regressed. When both are non-zero the STATUS is
`sorry` (the weaker claim names the status) and both counts are in the record,
so nothing is hidden by the precedence.

The rank is a claim about DIRECTION and it is arguable at two edges, so both
are argued here rather than left to a reader:
`lean-rejected` → `refused` is a step BACK (the generator now refuses a program
it used to emit a proof for), and `refused` → `lean-rejected` is a step FORWARD
(it emits a proof again, one Lean declines). Neither is "the code generator got
better" — it is a refusal moving along the pipeline, which is what the ranks
say and what a reader of a `reason` has to read anyway.

WHY CPU SECONDS ARE THE GATE AND WALL SECONDS ARE REPORTED
----------------------------------------------------------
Both are recorded. Only CPU is compared, at 2x, and the reason is that a wall
clock on this corpus measures the machine as much as the proof: `lean` runs a
thread pool, `test_formal.py` runs up to 20 examples at once by default, and
these same numbers were taken while the box was at load 13-40. A 2x wall gate
on a 10 s proof is a 20 s threshold that a loaded neighbour crosses routinely,
so it is a gate that fires on load and therefore a gate that gets `expect=`
within a month — which is how a ratchet stops ratcheting. Whole-tree CPU
seconds are summed by `formal/lean.py::run_lean` from `ps` over the Lean
process tree, so they barely move with load. Wall is printed beside a CPU
REGRESSION and beside a bankable speedup — the two rows a reader acts on — and
a row that is merely within tolerance prints nothing at all, because 52 lines of
"12.0 s against 11.0 s (1.09x)" bury the one line that matters.

An UNMEASURED time is never compared, and never reported as zero
-----------------------------------------------------------------
`formal/lean.py`'s verdict cache is content-addressed on the proof's exact
bytes, every `.olean`'s digest and the toolchain version, so a repeat run of an
unchanged corpus **replays** every verdict in about a tenth of a second and
measures no time at all. A replayed row carries `cached: true` and a `null`
time; a baseline row written from a replay carries `null` too. `null` is not
`0.0` anywhere in this file, and the report says how many rows were replayed,
because "52 of 52 verdicts" read without that number is a claim about the
machine that was not made. (`tools/formal_proof_breadth.py` carries the same
`cached` field for the same reason: a replayed verdict once recorded an example
as a pass on a date it had never been checked.)

THE COMPARISON, and the three things it deliberately does not do
---------------------------------------------------------------
It compares one example to one baseline row, and it says:

* **REGRESSION** — rank went up; `n_sorries` or `n_admitted` went up; or the
  measured CPU exceeded `TIME_FACTOR` x the baseline's.
* **IMPROVEMENT** — the mirror image, which is a bankable result and is
  reported with the exact command that banks it. A ratchet that cannot be
  ratcheted in the other direction is a one-way ratchet, and one-way
  ratchets decay.
* **INFO** — the example's bytes changed (a new subject, not a regression, and
  not comparable), a stem appeared or disappeared, a refusal's reason changed
  inside one rank, or a time is unmeasured on one side.

Three things it does NOT do, each because doing them would produce a red that
is not a fact:

1. **It does not compare a changed example against its old row.** `source_sha256`
   is in the record precisely so the tool can say "this program is not the one
   the baseline measured" instead of comparing two different programs' times.
2. **It does not fail on `prove=True` refusing something new** inside a rank.
   A different `reason` at the same rank is INFO, printed in full. A refusal
   moving is how a value-model project makes progress (see
   `bugs/FORMAL_proof_coverage_census_2026-10-03.md` §0.4, where one false
   refusal closed and the corpus moved to the next row with the class count
   unchanged), and a gate that fired on it would be fired at every step of it.
3. **It does not have a memory gate.** Peak is recorded per example and the
   corpus maximum is printed, because `>3-4 GB` is a project debt standard
   (`bugs/PERF_memory_over_4gb_is_a_bug.md`) and a ratchet that watched it would
   be useful — but an unrequested fourth gate on a number this tool has only
   measured on one machine is not this change's business. The data is here for
   whoever wants it.

WHAT `decide_sites` COUNTS, and what it does not
------------------------------------------------
`native_decide` and `bv_decide` close a goal through a generated axiom rather
than through the kernel, so their count is the size of the trust boundary a
proof carries (`formal/admitted.py`'s `AXIOM_TACTICS` module docstring is the
long argument; `FORMAL.md` §7 is the policy). The count here is of SITES in the
generated proof, read off the emitted text through
`formal/admitted.py::lean_code_regions` — which blanks comments and string
contents first, so it is exact — and the tactic list is READ from
`formal/admitted.py::AXIOM_TACTICS` rather than spelled here, because a second
hand-kept list of two names is a list that goes stale the day one is renamed.

**A site count is not a transitive count.** Whether a theorem's proof term
reaches an axiom is elaboration, and the instrument for that is
`formal/admitted.py::theorem_axiom_census` (it asks Lean `#print axioms`), whose
own docstring records seven theorems whose text names one of these tactics and
whose proof term reaches no axiom, and ten that name none and reach one through
another theorem. This column is the cheap half; that is the sound one.

EXIT STATUS
-----------
`0` nothing regressed · `1` at least one regression, all of them printed ·
`2` the census could not be compared (no baseline, unreadable baseline, no
`lean`). A finding is not a failure; a REGRESSION is.
"""
import argparse
import collections
import concurrent.futures
import hashlib
import json
import os
import re
import sys
import threading
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

#: The whole corpus. `formal/examples/*.mojo`, every one of them, because the
#: unit that regresses is an EXAMPLE and a sample of examples would make the
#: ratchet blind to the one that moved — `tools/formal_proof_breadth.py`'s own
#: §0.6 is the measurement of how fast a sampled corpus stops being comparable.
EXAMPLES = os.path.join(HERE, "formal", "examples")

#: The committed record. Per architecture, because the two backends' proof
#: generators are independent implementations over different machine models and
#: a row from one says nothing about the other (`test_formal.py`'s own module
#: docstring: "their KNOWN-GAP lists are separate").
BASELINE_DIR = os.path.join(HERE, "tools")
# v2 added `timed_on` (the date a row's Lean timings were measured), and the
# version is in the VALUE as well as being implied by the schema, because a v1
# file read by a v2 tool would otherwise fail with "baseline row is missing
# timed_on" — which is a true sentence about a file whose only problem is that
# it was written before the field existed, and says nothing about what to do.
# Refusing on the tag says it: re-seed with `--write-baseline`.
BASELINE_TAG = "formal-proof-census-v2"

#: How much slower a proof may get before this is a regression.
TIME_FACTOR = 2.0

#: Rank, lower is better. The two no-verdict classes share a rank on purpose;
#: see the module docstring's table.
STATUS_RANK = {
    "proved": 0,
    "admitted": 1,
    "sorry": 2,
    "lean-rejected": 3,
    "refused": 4,
    "crash": 5,
    "too-large": 6,
    "bound-exceeded": 6,
}

#: The classes that report the ABSENCE of a measurement. Printed as such
#: wherever they appear, and never counted as "proved at all".
NOT_A_VERDICT = {"too-large", "bound-exceeded"}


#: Lean's first diagnostic line, `file:line:col: error: …`, searched for
#: ANYWHERE in the text rather than at the start of a line: a replayed
#: verdict's stored detail is `compile_formal`'s sentence followed by the
#: diagnostics, so anchoring at the line start found the header instead and
#: produced a different string from the same failure on the two paths. The
#: extension is required so `x30:16: error` cannot match.
#:
#: Chosen over "the
#: whole blob" for two reasons, both measured on this corpus: a `lean-rejected`
#: row's detail is otherwise several hundred characters of repeated goal state
#: (which is what bloats a committed baseline), and — the one that matters — a
#: MEASURED run and a REPLAYED one do not produce the same blob. A replay reads
#: the verdict `formal/lean.py` stored, whose detail carries the header Lean
#: prints first (`IEEE754 / ProofLib / Refine / X86 / work`) and then the same
#: diagnostics, so three of the corpus's rows reported "same status, different
#: reason" on every single run for no reason at all. One line, taken the same
#: way from both, is both smaller and stable.
_DIAGNOSTIC_RE = re.compile(
    r"[\w./+-]+\.(?:lean|mojo|py|c|h|m):\d+:\d+:\s*(?:error|warning)\b[^\n]*")


def first_diagnostic(text: str, limit: int = 300) -> str:
    """Lean's own first `file:line:col: error: …`, one line, or `""`.

    Falls back to the first non-blank line, because a refusal from the code
    generator is a sentence rather than a diagnostic and is still the finding.
    Cut at `limit` and at a line break, like `tools/formal_proof_breadth.py`'s
    `_first_line`, for the same reason: the full message is unreadable in a
    table and the first line is the part that names the subject.
    """
    text = str(text or "")
    match = _DIAGNOSTIC_RE.search(text)
    line = match.group(0) if match else next(
        (ln for ln in text.splitlines() if ln.strip()), "")
    line = " ".join(line.split())
    return line[:limit]

#: One example's measurement. A named tuple rather than a dict because the JSON
#: baseline is a RECORD of this and a schema that only one side can read is a
#: schema that goes stale; `as_dict`/`from_dict` are the only two places that
#: know the field names.
Record = collections.namedtuple("Record", (
    "stem",            # `formal/examples/<stem>.mojo`, by stem
    "arch",
    "status",          # a key of STATUS_RANK
    "reason",          # the refusal's own message, or Lean's
    "phase",           # build | generate | check | ""
    "n_sorries",       # declarations Lean reported as "uses `sorry`", or null
    "n_admitted",      # `@admitted` host contracts in the file's closure
    "decide_sites",    # {"native_decide": n, "bv_decide": n} in the proof
    "decide_total",
    "proof_lines",
    "source_sha256",   # the EXAMPLE's bytes: is this the same program?
    "lean_wall_s",     # null when the verdict was replayed from the CAS
    "lean_cpu_s",
    "lean_peak_gb",
    "timed_on",        # the date the figures above were MEASURED, or null
    "cached",          # this write replayed the verdict rather than re-running
    "wall_s",          # the whole example: codegen + generate + check
    "peak_gb",         # max(lean peaks, this process's own high-water mark)
))


def record_as_dict(r: Record) -> dict:
    return dict(r._asdict())


def record_from_dict(d: dict) -> Record:
    """A `Record` from a baseline row, with the fields a reader may have deleted.

    Every numeric field is re-checked against the rank table and the corpus:
    a baseline is a COMMITTED FILE, and a hand-edited one is a thing this tool
    has to survive rather than crash on. A row whose status is not in
    `STATUS_RANK` is a `crash` — the loudest class available — because an
    unreadable status must never be read as a good one.
    """
    fields = Record._fields
    missing = [f for f in fields if f not in d]
    if missing:
        raise ValueError(f"baseline row is missing {', '.join(missing)}")
    got = {f: d[f] for f in fields}
    if got["status"] not in STATUS_RANK:
        got["status"] = "crash"
        got["reason"] = (f"baseline names a status this tool does not have: "
                         f"{d['status']!r}")
    got["decide_sites"] = dict(got["decide_sites"] or {})
    return Record(**got)


def baseline_path(arch: str) -> str:
    stem = "formal_proof_census_baseline" if arch == "arm64" else \
        f"formal_proof_census_baseline_{arch}"
    return os.path.join(BASELINE_DIR, stem + ".json")


# ── corpus ────────────────────────────────────────────────────────────────────

def corpus(only=()) -> list:
    """`[stem]` for every `formal/examples/*.mojo`, sorted. `--only` filters it.

    Sorted, because the order a directory hands back is a property of the
    filesystem and a baseline whose rows are in a different order than the run
    that reads it is a diff nobody can read.
    """
    try:
        names = sorted(f[:-5] for f in os.listdir(EXAMPLES)
                       if f.endswith(".mojo"))
    except OSError as e:
        raise SystemExit(f"cannot read {EXAMPLES}: {e}")
    want = {s.strip() for s in only if s.strip()}
    if want:
        missing = sorted(want - set(names))
        if missing:
            raise SystemExit(f"no such example(s): {', '.join(missing)}")
        names = [n for n in names if n in want]
    return names


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── the measurement ──────────────────────────────────────────────────────────

#: One recorder per THREAD, because the census runs `-j N` threads over the same
#: module and a single shared list would hand one example's figures to another.
_RUNS = threading.local()
_REAL_RUN_LEAN = None
_REAL_LOOKUP_VERDICT = None
_REAL_PUBLISH_VERDICT = None


def _install_remeasure() -> None:
    """Make the proof-verdict cache MISS, so `check_proof_cached` elaborates.

    The verdict cache is content-addressed on the proof's exact bytes, and that
    is what makes a repeat run of an unchanged corpus cost about a tenth of a
    second per example instead of ninety. The price is that **an unchanged
    example measures no time at all**, which is precisely the state a
    `--write-baseline` seeds: the first run of this tool on a warm tree records
    statuses for 52 examples and timings for none, and a ratchet with no
    timings in its baseline has nothing to ratchet on the next time a proof
    gets slower.

    So this is the operator's way to spend the money: bypass the cache for the
    duration of the run and every example is elaborated for real. It patches the
    two CAS entry points rather than `check_proof_cached` itself, so the
    LIBRARY verdicts (`formal/lean.py::library_census`, which cost about ninety
    seconds a module) stay cached — remeasuring those is never what anybody
    means by "remeasure the proofs", and they are content-addressed on the
    `.olean`'s own source digest, so they are already correct for this tree.

    `_publish_verdict` is stubbed out rather than left in place: the key is
    derived from the proof's bytes, so a remeasurement has nowhere new to go
    and republishing would only rewrite an identical body. It is stubbed so a
    half-published entry cannot exist if the run is interrupted.
    """
    global _REAL_LOOKUP_VERDICT, _REAL_PUBLISH_VERDICT
    from formal import lean as L
    if _REAL_LOOKUP_VERDICT is not None:
        return
    _REAL_LOOKUP_VERDICT = L.cas_lookup_verdict
    _REAL_PUBLISH_VERDICT = L._publish_verdict
    L.cas_lookup_verdict = lambda key: None
    L._publish_verdict = lambda *a, **kw: None


def _restore_cache() -> None:
    global _REAL_LOOKUP_VERDICT, _REAL_PUBLISH_VERDICT
    from formal import lean as L
    if _REAL_LOOKUP_VERDICT is None:
        return
    L.cas_lookup_verdict = _REAL_LOOKUP_VERDICT
    L._publish_verdict = _REAL_PUBLISH_VERDICT
    _REAL_LOOKUP_VERDICT = _REAL_PUBLISH_VERDICT = None


def _is_proof_run(args) -> bool:
    """Is this `run_lean` call a PROOF check rather than anything else?

    Structurally, not by message. Every caller of the launcher in this tree
    spells its argv differently and the shapes are disjoint: a proof check is
    `formal/lean.py::_run_lean`'s `[basename]` — one `.lean` and nothing else;
    a library build or census is `ensure_library`/`_measure_one`'s
    `["-o", out, source]`; `lean_version` is `["--version"]`. So the test is
    "exactly one argument, and it names a Lean file", which stays true if any
    of those messages is reworded.
    """
    argv = [str(a) for a in args]
    return len(argv) == 1 and argv[0].endswith(".lean")


def _install_recorder() -> None:
    """Wrap `formal.lean.run_lean` once, keeping each thread's proof runs.

    `formal/build.py` does `from formal.lean import check_proof_cached` INSIDE
    the function and `formal/lean.py::_run_lean` resolves `run_lean` as a module
    global at call time, so replacing the module attribute is enough and no
    source file is touched. Idempotent, so a caller (or a test) that installs it
    twice does not get two wrappers.
    """
    global _REAL_RUN_LEAN
    import formal.lean as L
    if _REAL_RUN_LEAN is not None:
        return
    _REAL_RUN_LEAN = L.run_lean

    def recording(lean, args, **kw):
        res = _REAL_RUN_LEAN(lean, args, **kw)
        runs = getattr(_RUNS, "runs", None)
        if runs is not None and _is_proof_run(args):
            runs.append(res)
        return res

    L.run_lean = recording


def decide_sites(proof_text: str) -> dict:
    """`{tactic: n}` for the `native_decide`/`bv_decide` sites in one proof.

    Through `formal/admitted.py::lean_code_regions`, which blanks comment and
    string-literal CONTENTS (keeping offsets), and with the tactic list READ
    from `formal/admitted.py::AXIOM_TACTICS` rather than spelled here — a second
    hand-kept copy of two names is a copy that goes stale silently.
    """
    from formal import admitted
    code = admitted.lean_code_regions(proof_text)
    out = {}
    for tactic in admitted.AXIOM_TACTICS:
        pattern = re.compile(r"(?<![\w.'])(" + re.escape(tactic) + r")(?![\w'])")
        out[tactic] = len(pattern.findall(code))
    return out


def _cached_hole_count(proof_path: str):
    """`n_sorries` for a proof whose check FAILED, or None if not measurable.

    `compile_formal` raises on a failed check, so its own `proof_sorries` is
    out of reach for exactly the rows where a hole count is most interesting.
    `formal/lean.py::proof_census` returns the count either way, and on a
    replayed verdict it is a CAS read rather than an elaboration — Lean counts
    the holes while it elaborates, and `formal/lean.py` stores the count beside
    the verdict for this reason. `None` if the call itself fails, because
    "no count" and "zero holes" are different facts.
    """
    from formal import lean as L
    try:
        return L.proof_census(proof_path, repo_root=HERE).n_sorries
    except Exception:                                    # noqa: BLE001
        return None


def _classify_failure(runs, detail):
    """`(status, reason)` for an example whose proof check did not pass.

    Read off the captured `LeanRun` when there is one, and off the detail text
    when there is not — because **a verdict that fails is cached too**.
    `formal/lean.py` publishes failed verdicts deliberately ("a known-failing
    example is just as deterministic as a passing one"), so on a repeat run
    `proof_census` returns the stored failure and never launches Lean: the
    detail it raises carries the SAME Leown words, recorded on the run that
    first produced them, and the rows for `either`, `sum` and every other
    rejected example are replayed rather than re-measured. Matching Lean's own
    sentences rather than `compile_formal`'s is what makes both halves work,
    because Lean's sentence is the thing that is the same in both.

    The order is the order of how much each one is a verdict about the PROOF:

    * `exceeded` set — the launcher killed it. NOT a verdict on the proof
      (`formal/lean.py` says so in as many words, and refuses to publish one to
      the verdict cache for exactly this reason), so it is its own class.
    * Lean's own memory ceiling — also not a verdict, and a different fact: the
      proof was too big for the checker, which is a property of the machine's
      `-M` and of the proof's size. **Asked of
      `formal.lean.lean_refused_on_its_own_memory_ceiling`, not of a regex
      here**, because `formal/lean.py` is what SETS that `-M` and a second copy
      of the sentence is a second answer to "is this a verdict or an absence" —
      which is the disagreement this classification exists to end
      (`bugs/FORMAL_eighteen_examples_have_no_accepted_proof_and_seven_are_
      declared.md`).
    * anything else — Lean elaborated the file and said no. That IS a verdict,
      and Lean's own message is the finding.
    """
    from formal.lean import lean_refused_on_its_own_memory_ceiling
    if runs and runs[-1].exceeded:
        return "bound-exceeded", runs[-1].exceeded
    blob = (runs[-1].stderr or "") + (runs[-1].stdout or "") if runs else \
        str(detail or "")
    ceiling = lean_refused_on_its_own_memory_ceiling(blob)
    if ceiling:
        return ("too-large", " ".join(ceiling.split()))
    return "lean-rejected", first_diagnostic(detail)


def _read_proof(workdir: str):
    """`(path, text)` for the proof `compile_formal` wrote, or `(None, "")`.

    Found by GLOB rather than by reconstructing `compile_formal`'s own
    `<stem>_proof.lean` spelling, so this does not carry a second copy of a
    naming convention that can change; and it is the STRUCTURAL answer to
    "did the failure happen in the check or in the build?", because the proof
    file is written before the check runs. A tool that read `compile_formal`'s
    exception text instead would put a library-build error in the proof layer's
    column — and, on a warm verdict cache, would read *every* rejected example
    as a refusal, which is how 13 rows of the first run of this tool came out
    `refused` when all thirteen are Lean verdicts.
    """
    try:
        found = sorted(f for f in os.listdir(workdir)
                       if f.endswith("_proof.lean"))
    except OSError:
        return None, ""
    if not found:
        return None, ""
    path = os.path.join(workdir, found[0])
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return path, f.read()
    except OSError:
        return path, ""


def measure_example(stem: str, arch: str = "arm64", test_input: int = 10) -> Record:
    """One example through `compile_formal(prove=True, check=True)`.

    The single call `fire.py build --formal` makes, so what this measures is
    what the driver measures, with `formal/lean.py`'s bounds on the Lean run and
    no bound invented here. Everything the record carries about time and memory
    comes out of the `LeanRun` this call produces (see `_install_recorder`); the
    only thing measured around it is the wall clock of the call itself and this
    process's own RSS high-water mark, because the codegen half is Python in
    THIS process and `run_lean` never sees it.

    Every example builds in its own `formal/lean.py::scratch_dir`, so nothing
    two examples could both write is shared, and the directory goes away
    afterwards whatever happened.
    """
    import resource

    import formal.build as FB
    from formal import lean as L

    lean = L.find_lean(HERE)
    if not lean:
        raise SystemExit("lean not found (see ./lean-toolchain)")

    source = os.path.join(EXAMPLES, stem + ".mojo")
    proof_lines, sites, total, n_sorries, n_admitted = 0, {}, 0, None, 0
    status, reason, phase, cached = "crash", "", "build", False
    _install_recorder()
    _RUNS.runs = runs = []

    started = time.monotonic()
    with L.scratch_dir("proof-census") as workdir:
        out = os.path.join(workdir, stem + ".aout")
        try:
            result = FB.compile_formal(source, output=out, test_input=test_input,
                                       prove=True, check=True, arch=arch)
        except FB.FormalBuildError as e:
            message = str(e)
            proof_path, text = _read_proof(workdir)
            if proof_path:
                # A proof was written and the build still failed, so the
                # failure is the CHECK's. The verdict came from the cache when
                # no run was captured, and `cached` says so rather than letting
                # an unmmeasured row read as a measured one.
                status, reason = _classify_failure(runs, message)
                phase, cached = "check", not runs
                proof_lines = text.count("\n")
                sites = decide_sites(text)
                total = sum(sites.values())
                n_sorries = _cached_hole_count(proof_path)
            else:
                status, reason, phase = "refused", first_diagnostic(message), \
                    "build"
        except NotImplementedError as e:
            # The proof generator's own refusal. Every raise site in
            # `formal/arm64_proof_gen.py` is deliberate and names its reason
            # ("the model has no domain for this"), and it is the only thing in
            # this path that raises NotImplementedError.
            status, reason, phase = "refused", first_diagnostic(str(e)), \
                "generate"
            proof_path, text = _read_proof(workdir)
        except Exception as e:                          # noqa: BLE001
            status, reason = "crash", first_diagnostic(
                f"{type(e).__name__}: {e}")
            proof_path, text = _read_proof(workdir)
        else:
            phase = "check"
            proof_path = result.get("proof_path")
            proof_ok = True
            try:
                with open(proof_path, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError as e:
                status, reason, proof_ok = "crash", f"proof unreadable: {e}", \
                    False
                text = ""
            else:
                proof_lines = text.count("\n")
                sites = decide_sites(text)
                total = sum(sites.values())
            n_sorries = result.get("proof_sorries")
            admitted = result.get("admitted") or []
            n_admitted = len(admitted)
            cached = bool(result.get("proof_cached"))
            # Precedence, and both counts stay in the record either way: a
            # proof with holes AND admitted contracts is reported at the weaker
            # claim (`sorry`) and still ratchets both numbers.
            #
            # The guard is `proof_ok` and nothing about `status`: an UNREADABLE
            # PROOF is a `crash` and must not be reclassified into `proved`,
            # which is this census reporting its own crash as a pass. Guarding
            # on `status` instead — the obvious one, and the second attempt at
            # this line here — does the opposite: `status` STARTS as `crash`,
            # so every successful build reads as a crash and the whole corpus
            # regresses at once.
            if proof_ok:
                if n_sorries:
                    status = "sorry"
                elif n_admitted:
                    status = "admitted"
                else:
                    status = "proved"
    wall = time.monotonic() - started
    _RUNS.runs = None
    run = runs[-1] if runs else None
    peak = run.peak_rss / float(1 << 30) if run is not None else 0.0
    # `ru_maxrss` is KILOBYTES on Linux and BYTES on Darwin, and this tool has
    # to be right on both or the `peak_gb` it records is off by 1024 on one of
    # them — which is a number a reader would take seriously.
    maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    host = maxrss / (1024.0 * 1024.0) if sys.platform != "darwin" \
        else maxrss / float(1 << 30)
    if status in ("proved", "admitted", "sorry"):
        n_sorries = int(n_sorries or 0)
    return Record(
        stem=stem, arch=arch, status=status, reason=reason, phase=phase,
        n_sorries=n_sorries, n_admitted=n_admitted,
        decide_sites=sites, decide_total=total, proof_lines=proof_lines,
        source_sha256=sha256_file(source),
        # A REPLAYED verdict measured no time. `None`, never 0.0: the launcher
        # did not run, and a zero here would be a proof that took no time.
        lean_wall_s=round(run.wall_s, 1) if run is not None else None,
        lean_cpu_s=round(run.cpu_s, 1) if run is not None else None,
        lean_peak_gb=round(peak, 2) if run is not None else None,
        # The DATE these three were measured, which is not the same question as
        # `cached` (that is about this write's verdict) and is the only way a
        # reader can tell a timing taken last week from one taken before a
        # `--write-baseline` on another machine. `write_baseline` carries all
        # four together, so a preserved timing never loses its date.
        timed_on=time.strftime("%Y-%m-%d") if run is not None else None,
        cached=cached,
        wall_s=round(wall, 1), peak_gb=round(max(peak, host), 2))


def measure(stems, arch="arm64", jobs=1, test_input=10, verbose=True) -> list:
    """Every stem in `stems`, `-j jobs` at a time, in corpus order.

    Threads, and that is `compile_formal`'s own concurrency story rather than a
    shortcut: it publishes per-image state into module globals
    (`formal/model.py::publish_target`, `clear_non_ascii_strings`) at the START
    of each build, and `tools/formal_proof_breadth.py` — the tool that measures
    the same call over 60 items — runs its items on a `ThreadPoolExecutor` for
    the same reason. `j=1` is the default here for a different reason: this is a
    TIMING measurement, and the CPU seconds a proof costs do not depend on the
    machine's load nearly as much as its wall clock does (see the module
    docstring).

    One example raising is that example's row, not the run's: an exception that
    escapes `measure_example` itself (a missing `lean`, an unreadable example)
    is the census's problem and is raised, while everything the census exists to
    classify is caught inside `measure_example` and classified.
    """
    if jobs <= 1 or len(stems) <= 1:
        rows = []
        for n, stem in enumerate(stems, 1):
            rows.append(measure_example(stem, arch, test_input))
            if verbose:
                print(f"  [{n}/{len(stems)}] {stem}: {rows[-1].status} "
                      f"{rows[-1].wall_s:.1f}s", file=sys.stderr, flush=True)
        return rows
    rows = [None] * len(stems)
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(measure_example, stem, arch, test_input): i
                   for i, stem in enumerate(stems)}
        done = 0
        for fut in concurrent.futures.as_completed(futures):
            rows[futures[fut]] = fut.result()
            done += 1
            if verbose:
                print(f"  [{done}/{len(stems)}] {rows[futures[fut]].stem}: "
                      f"{rows[futures[fut]].status}", file=sys.stderr,
                      flush=True)
    return rows


# ── the baseline ─────────────────────────────────────────────────────────────

def write_baseline(path: str, rows, arch: str, lean_version: str,
                   corpus_stems=(), keep=None) -> str:
    """Write `rows` to `path`, atomically, merging over what is already there.

    **Merging, not replacing**, and the reason is `--only`. A `--write-baseline`
    over a subset is how an operator re-seeds ONE row — most often with
    `--only <stem> --remeasure`, which is how a row that was written from a
    replayed verdict gets a measured time without re-elaborating the other 51.
    A replacing write would answer that by throwing the other 51 rows away and
    leaving the committed baseline a census of one example.

    **`keep=None` means "merge over the file at `path`", read here rather than
    handed in.** That is the whole fix for a bug this function shipped with:
    the caller had to pass the old rows, it passed them once from the wrong
    list, and a `--only` write silently deleted 35 of 52 committed rows — twice,
    before the merge was moved in here. A merge whose second half is somebody
    else's decision is two decisions, and this one had to be one.

    **The rows that MAY be dropped are decided here too, from `corpus_stems`:**
    a row whose example has been deleted is a claim about a program that no
    longer exists, and keeping it makes every later run report that stem as "in
    the baseline and not in this run". The caller passes the WHOLE corpus and
    not the stems it measured, because dropping a row it did not measure is the
    other half of the same mistake.

    Atomic because a half-written baseline is WORSE than no baseline: it is a
    file the next run will read and compare against, and
    `tools/dangling_doc_refs.py`'s `write_baseline` says the same of its own.
    Private temp + `os.replace`, which is atomic on the same filesystem.
    """
    keep = dict(load_baseline(path) if keep is None else keep) \
        if (keep is not None or os.path.isfile(path)) else {}
    for stem in sorted(set(keep) - set(corpus_stems)):
        del keep[stem]
    kept = {r.stem: record_as_dict(r) for r in keep.values()} if keep else {}
    merged = dict(kept)
    for r in rows:
        was = kept.get(r.stem)
        if (was is not None and r.lean_cpu_s is None
                and was.get("lean_cpu_s") is not None):
            # **A replayed write KEEPS the timing the row already had.** An
            # unmeasured value is not a change, and banking an improvement on a
            # warm tree would otherwise reset every row it touched to "no
            # timing known" — which is how a time ratchet decays through
            # ordinary use of its own `--write-baseline`. All four figures move
            # together or none does, so a preserved timing never shows a CPU
            # from one elaboration and a date from another.
            r = r._replace(**{field: was[field] for field in
                              ("lean_wall_s", "lean_cpu_s", "lean_peak_gb",
                               "timed_on")})
        merged[r.stem] = record_as_dict(r)
    # `examples` and `summary` below are computed over what is actually in the
    # file, never over the caller's list.
    summary = collections.Counter(row["status"] for row in merged.values())
    body = {
        "tag": BASELINE_TAG,
        "arch": arch,
        "lean": lean_version,
        "written": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "examples": len(merged),
        "measured_this_write": sorted(r.stem for r in rows),
        "timed_rows": sum(1 for row in merged.values()
                          if row.get("lean_cpu_s") is not None),
        "summary": {k: summary.get(k, 0) for k in STATUS_RANK
                    if summary.get(k)},
        "time_factor": TIME_FACTOR,
        "records": merged,
    }
    text = json.dumps(body, indent=1, sort_keys=True) + "\n"
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return path


def _read_baseline_body(path: str) -> dict:
    """The baseline's own JSON, for the fields `load_baseline` does not return.

    `load_baseline` hands back `records` because that is all a comparison needs;
    `arch` and `time_factor` are read here so the tool can refuse a comparison
    it has no standing to make rather than silently making it.
    """
    try:
        with open(path, encoding="utf-8") as f:
            body = json.load(f)
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def load_baseline(path: str) -> dict:
    """The baseline's `records`, or raise. A wrong tag is a refusal to guess.

    `tools/dangling_doc_refs.py` and `formal/lean.py`'s verdict cache both
    refuse a body they cannot parse rather than reading it as a default, and the
    reason is the same here: a baseline read as "everything was proved" when it
    is unreadable turns the ratchet into a green light.
    """
    try:
        with open(path, encoding="utf-8") as f:
            body = json.load(f)
    except (OSError, ValueError) as e:
        raise SystemExit(f"cannot read the baseline at {path}: {e}")
    if not isinstance(body, dict) or body.get("tag") != BASELINE_TAG:
        raise SystemExit(
            f"{path} is not a {BASELINE_TAG} baseline (tag="
            f"{(body or {}).get('tag') if isinstance(body, dict) else '?'!r}); "
            f"refusing to compare against it")
    rows = body.get("records")
    if not isinstance(rows, dict) or not rows:
        raise SystemExit(f"{path} has no records")
    return {stem: record_from_dict(row) for stem, row in rows.items()}


# ── the comparison ───────────────────────────────────────────────────────────

Finding = collections.namedtuple("Finding", "severity stem text")


def compare(baseline: dict, rows, complete: bool = True) -> list:
    """`[Finding]` for every difference between a baseline and a measurement.

    Three severities and no fourth, because a ratchet's output is read by
    somebody deciding what to do next and a finding they cannot act on is noise:
    `REGRESSION` fails the run, `IMPROVEMENT` is a result to bank, and `INFO`
    is the honest "these two are not comparable, and here is why".

    `complete=False` is a `--only` run, and it suppresses the one finding that
    would otherwise be a lie: every baseline row the run did not cover reads as
    "the example was deleted", which 45 rows of it demonstrated. A narrowed run
    knows nothing about the 45, so it says nothing about them.
    """
    out = []
    seen = set()
    timed_on_one_side = []
    for r in rows:
        seen.add(r.stem)
        before = baseline.get(r.stem)
        if before is None:
            out.append(Finding("INFO", r.stem,
                               "not in the baseline — a new example. "
                               "`--write-baseline` to bank it."))
            continue
        if before.source_sha256 != r.source_sha256:
            out.append(Finding(
                "INFO", r.stem,
                "the example's bytes changed since the baseline, so its row "
                "is a different program: not compared. Bank it with "
                "`--write-baseline`."))
            continue
        rank_before, rank_now = STATUS_RANK[before.status], STATUS_RANK[r.status]
        if rank_now > rank_before:
            out.append(Finding(
                "REGRESSION", r.stem,
                f"status got WORSE: {before.status} -> {r.status}"
                + (f" — {r.reason[:160]}" if r.reason else "")))
        elif rank_now < rank_before:
            out.append(Finding(
                "IMPROVEMENT", r.stem,
                f"status got BETTER: {before.status} -> {r.status}"
                + (f" — {r.reason[:160]}" if r.reason else "")
                + ". Bank it with `--write-baseline`."))
        elif before.status != r.status:
            out.append(Finding(
                "INFO", r.stem,
                f"{before.status} -> {r.status}: both are the absence of a "
                f"verdict, so this is not a regression"))
        elif r.status in ("refused", "lean-rejected", "crash") and \
                before.reason != r.reason:
            out.append(Finding(
                "INFO", r.stem,
                f"same status, different reason: {before.reason[:120]!r} -> "
                f"{r.reason[:120]!r}"))
        for field, label in (("n_sorries", "admitted `sorry`s"),
                             ("n_admitted", "admitted host contracts")):
            was, now = getattr(before, field), getattr(r, field)
            if was is None or now is None:
                continue
            if now > was:
                out.append(Finding(
                    "REGRESSION", r.stem,
                    f"{label} went UP: {was} -> {now}"))
            elif now < was:
                out.append(Finding(
                    "IMPROVEMENT", r.stem,
                    f"{label} went DOWN: {was} -> {now}. Bank it with "
                    f"`--write-baseline`."))
        out.extend(_time_findings(before, r, timed_on_one_side))
    out.extend(_group_unmeasured(timed_on_one_side))
    for stem in sorted(set(baseline) - seen):
        if not complete:
            continue
        out.append(Finding("INFO", stem,
                           "in the baseline and not in this run — the example "
                           "was deleted, so its row is not compared"))
    return out


#: The stem a finding gets when it is about the RUN rather than about one
#: example. Printed like any other and greppable like any other; the point is
#: that "52 rows of the same sentence" is not a finding a reader can act on and
#: one line naming them is.
RUN_SCOPE = "*"

#: How many stems a run-scoped finding names before it says "+N more". Set at
#: the corpus size: 52 rows fit on two terminal lines, and a finding that hides
#: which rows it is about is one a reader has to go and rediscover.
NAMED_IN_RUN_FINDING = 20


def _group_unmeasured(stems) -> list:
    """ONE finding for every row whose two sides disagree about being timed.

    The per-row version of this sentence is the same sentence 16 times, and a
    reader cannot act on any of them individually — the action is "re-measure
    with `--remeasure`, or bank a timing for the rows that have none". So the
    stems are collected and said once, under `RUN_SCOPE`.
    """
    if not stems:
        return []
    shown = ", ".join(sorted(stems)[:NAMED_IN_RUN_FINDING])
    more = "" if len(stems) <= NAMED_IN_RUN_FINDING \
        else f", +{len(stems) - NAMED_IN_RUN_FINDING} more"
    return [Finding(
        "INFO", RUN_SCOPE,
        f"{len(stems)} row(s) have a timing on exactly one side, so the 2x "
        f"time gate could not be exercised for them — a replayed verdict "
        f"measures no time, and an unmeasured value is never compared: "
        f"{shown}{more}.")]


def _time_findings(before: Record, r: Record, unmeasured=None) -> list:
    """The CPU regression, plus what is worth saying about everything else.

    Only CPU is gated (`TIME_FACTOR` x); the module docstring gives the whole
    argument and the short version is that a wall clock here measures the box
    as much as the proof. The wall ratio is printed on a regression so a reader
    who disagrees has the number.

    **A row that is within tolerance says NOTHING**, and that is a decision
    rather than an omission: with 52 rows a per-row "12.0 s against 11.0 s
    (1.09x)" is 52 lines that bury the one line that matters, and the summary
    already says how many rows this run measured. What does get said is the two
    facts a reader can act on — one side measured and the other did not, which
    `compare` groups into ONE finding, and a proof at least `TIME_FACTOR` x
    FASTER (a result, and results are what `--write-baseline` exists for).

    A `None` on either side is never compared and never printed as a ratio: a
    replayed verdict measured no time, and comparing it would be comparing a
    measurement against a non-measurement.
    """
    out = []
    was, now = before.lean_cpu_s, r.lean_cpu_s
    wall = ""
    if r.lean_wall_s and before.lean_wall_s:
        wall = f" (wall {r.lean_wall_s:.1f}s against {before.lean_wall_s:.1f}s)"
    if was and now:
        if now > TIME_FACTOR * was:
            out.append(Finding(
                "REGRESSION", r.stem,
                f"the proof got slower: {now:.1f}s CPU against a baseline of "
                f"{was:.1f}s is {now / was:.1f}x, over the {TIME_FACTOR:g}x "
                f"this ratchet allows" + wall))
        elif now * TIME_FACTOR < was:
            out.append(Finding(
                "IMPROVEMENT", r.stem,
                f"the proof got {was / now:.1f}x faster: {now:.1f}s CPU against "
                f"a baseline of {was:.1f}s" + wall
                + ". Bank it with `--write-baseline`."))
    elif was or now:
        if unmeasured is not None:
            unmeasured.append(r.stem)
    return out


# ── the report ───────────────────────────────────────────────────────────────

def summary_line(rows) -> str:
    counts = collections.Counter(r.status for r in rows)
    proved = counts["proved"] + counts["admitted"] + counts["sorry"]
    measured = sum(1 for r in rows if r.lean_cpu_s is not None)
    replayed = sum(1 for r in rows if r.cached)
    peak = max((r.lean_peak_gb or 0.0) for r in rows) if rows else 0.0
    return (f"{len(rows)} examples: {proved} of them reach a proof Lean "
            f"accepted, {measured} measured by this run and {replayed} "
            f"replayed from the verdict cache, largest Lean peak {peak:.2f} GB")


def status_table(rows) -> list:
    counts = collections.Counter(r.status for r in rows)
    out = []
    for status in sorted(STATUS_RANK, key=lambda s: STATUS_RANK[s]):
        if not counts.get(status):
            continue
        line = f"   {status:15s} {counts[status]:3d}"
        if status in NOT_A_VERDICT:
            line += "   <- not a verdict on the proof"
        elif status == "sorry":
            line += "   <- holes: " + ", ".join(
                f"{r.stem}={r.n_sorries}" for r in rows if r.status == status)
        elif status == "admitted":
            line += "   <- contracts: " + ", ".join(
                f"{r.stem}={r.n_admitted}" for r in rows
                if r.status == status)
        out.append(line)
    return out


def report(rows, findings, arch, baseline, banked=None) -> list:
    out = [f"== formal proof census, {arch}: {len(rows)} examples",
           f"   {summary_line(rows)}"]
    out.extend(status_table(rows))
    regress = [f for f in findings if f.severity == "REGRESSION"]
    better = [f for f in findings if f.severity == "IMPROVEMENT"]
    notes = [f for f in findings if f.severity == "INFO"]
    out.append("")
    if regress:
        out.append(f"REGRESSIONS ({len(regress)}):")
        out.extend(f"   {f.stem}: {f.text}" for f in regress)
    if better:
        out.append(f"improvements ({len(better)}), none banked yet:")
        out.extend(f"   {f.stem}: {f.text}" for f in better)
        out.append(f"   bank them with: python3 tools/formal_proof_census.py "
                   f"--write-baseline")
    if notes:
        out.append(f"not comparable ({len(notes)}):")
        out.extend(f"   {f.stem}: {f.text}" for f in notes)
    if banked:
        out.append(f"baseline written: {banked}")
    if not regress:
        out.append("no example regressed against "
                   + (os.path.basename(baseline) if baseline else "nothing"))
    return out


# ── main ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="the per-example Lean-proof ratchet over formal/examples")
    ap.add_argument("--baseline", default=None,
                    help="the JSON baseline (default: per-arch, committed)")
    ap.add_argument("--write-baseline", action="store_true",
                    help="write what this run measured as the baseline; this "
                         "is how an improvement is banked, and it also "
                         "RESETS the time and hole ratchets to the new state")
    ap.add_argument("--list", action="store_true",
                    help="print the corpus and exit, building nothing")
    ap.add_argument("--only", default="",
                    help="comma-separated example stems, for a narrower run")
    ap.add_argument("--arch", default="arm64", choices=("arm64", "x86_64"))
    ap.add_argument("-j", "--jobs", type=int, default=1,
                    help="examples in flight; 1 (the default) because this is "
                         "a timing measurement")
    ap.add_argument("-n", "--test-input", type=int, default=10,
                    help="the value the startup stub hands `main` "
                         "(compile_formal's own default)")
    ap.add_argument("--quiet", action="store_true",
                    help="no per-example progress on stderr")
    ap.add_argument("--remeasure", action="store_true",
                    help="bypass the proof-verdict CACHE, so every example is "
                         "elaborated for real and its time is measured. This "
                         "is what puts timings in a baseline written on a warm "
                         "tree, and it costs a Lean run per example "
                         "(seconds to ~300 s each, up to ~3 GB peak)")
    args = ap.parse_args(argv)

    stems = corpus(args.only.split(",") if args.only else ())
    if args.list:
        print(f"{len(stems)} examples in {EXAMPLES}")
        for stem in stems:
            print(f"   {stem}")
        return 0

    import formal.lean as L
    lean = L.find_lean(HERE)
    if not lean:
        print("lean not found (see ./lean-toolchain)", file=sys.stderr)
        return 2
    path = args.baseline or baseline_path(args.arch)
    # The baseline is compared only against the same architecture. The two
    # backends' proof generators are independent implementations over
    # different machine models (`test_formal.py`'s own docstring: "their
    # KNOWN-GAP lists are separate"), so an x86-64 row compared against an
    # arm64 baseline would report every example as a regression.
    if os.path.isfile(path):
        body = _read_baseline_body(path)
        if body.get("arch") != args.arch:
            print(f"{path} is an {body.get('arch')} baseline and this run is "
                  f"{args.arch}; point --baseline at an {args.arch} one",
                  file=sys.stderr)
            return 2

    if args.remeasure:
        _install_remeasure()
    try:
        rows = measure(stems, args.arch, args.jobs, args.test_input,
                       verbose=not args.quiet)
    finally:
        _restore_cache()
    baseline = load_baseline(path) if os.path.isfile(path) else {}
    if args.write_baseline:
        # The WHOLE corpus goes in as `corpus_stems`, never `stems`: the merge
        # and the drop are one decision (see `write_baseline`), and passing the
        # measured stems would make every `--only` write delete the rows it did
        # not measure.
        print(f"wrote {write_baseline(path, rows, args.arch, L.lean_version(lean), corpus())}"
              f" ({len(rows)} measured, {len(baseline)} already recorded)")
        for line in report(rows, [], args.arch, path, banked=path):
            print(line)
        return 0
    if not baseline:
        print("\n".join(report(rows, [], args.arch, None)))
        print(f"no baseline at {path} — nothing to compare against. Seed it "
              f"with: python3 tools/formal_proof_census.py --write-baseline")
        return 2
    findings = compare(baseline, rows,
                       complete=len(stems) == len(corpus()))
    print("\n".join(report(rows, findings, args.arch, path)))
    return 1 if any(f.severity == "REGRESSION" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())