#!/usr/bin/env python3
"""What a generated arm64/x86-64 proof COSTS, and what it is still trying to prove.

    python3 tools/formal_proof_shape.py formal/examples/bitops.mojo
    python3 tools/formal_proof_shape.py <file> --mode goal --which 2
    python3 tools/formal_proof_shape.py <file> --mode profile --json

WHY THIS TOOL EXISTS, AND WHY IT IS NOT `tools/formal_proof_breadth.py`
--------------------------------------------------------------------------
`tools/formal_proof_breadth.py` answers "how much of this repository's own
source can the formal path PROVE, and what stops each function that cannot".
This one answers the two questions a proof-cost bug needs and breadth cannot:

  * `--mode profile` — **where the seconds are**, in one `lean --profile` run,
    with the buckets RANKED so the answer is a list rather than a wall of text.
    `bugs/FORMAL_the_arm64_proof_time_floor_is_one_composition_theorem.md` is
    entirely about this: it attributes 83% of one generated proof to one
    declaration, and its own next steps are guesses about which tactic to
    cheapen. "Guess which tactic" is what this mode exists to stop.
  * `--mode goal` — **what the expensive tactic is still trying to prove**,
    by replacing the Nth terminal value flow's `simp +decide only` with
    `trace_state` and admitting the leaf, so Lean prints the residual goal and
    the file still elaborates. A cost with no goal in front of it is a number
    nobody can act on; the goal is what says whether the cost is TERM SIZE or
    TACTIC COUNT, and those need different fixes.

Both numbers in that bug doc were taken from scratch scripts under `.tmp/`
(`.tmp/genproof.py` and a prefix sweep), so they could not be re-derived by the
next session without rewriting them. This is those instruments, with the
`--mode goal` half added.

EVERY LEAN RUN GOES THROUGH `formal/lean.py::run_lean`
-------------------------------------------------------
Never a bare `lean`: the guard in `formal/lean.py` is what bounds a run at 45
minutes of wall and 90 of CPU and what REPORTS which bound a run broke. A tool
that launched `lean` itself would answer "lean failed" for a run the guard
killed, which is the confusion `run_lean`'s `exceeded` field exists to prevent.

PROOF GENERATION RUNS WITH `check=False`
----------------------------------------
`compile_formal(prove=True, check=False)` writes `<stem>_proof.lean` next to the
image and does not elaborate it. Generation is pure python (0.1 GB, about a
second for `bitops`); elaboration is the expensive half and each mode below
deliberately pays for it exactly once.

WHAT THE TWO MODES CANNOT DO
----------------------------
Neither mode changes what is proved — `goal` replaces one tactic with
`trace_state` and a leaf `sorry`, so the file it elaborates is NOT the file the
compiler would ship, and the profile it prints is the cost of the instrumented
file. Both are stated in the output rather than left for a reader to infer: the
`goal` mode prints how many holes it admitted.
"""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The tactic block the `goal` mode replaces.  It is matched by its SPELLING
# rather than by a line number, because the line number moves every time the
# emitter changes and a line number would then point at the wrong goal — which
# is the failure mode this mode exists to prevent.  `TERMINAL_FLOW` is the
# emitter's own comment on the line above it, and the `simp +decide only` is the
# first line that starts it.
TERMINAL_FLOW = "      simp +decide only [h8, mojo,"
CLOSERS = ("all_goals", "·")


def generate(src, arch, outdir):
    """`compile_formal(prove=True, check=False)`; the generated `.lean` path.

    `check=False` is the whole point: this returns the ARTIFACT, and both modes
    below decide for themselves whether to elaborate it.
    """
    import sys as _sys
    _sys.path.insert(0, HERE)
    from formal import build as FB
    stem = os.path.splitext(os.path.basename(src))[0]
    out = os.path.join(outdir, stem)
    t = time.time()
    result = FB.compile_formal(src, output=out, test_input=10,
                               prove=True, check=False, arch=arch)
    proof = None
    for cand in (os.path.join(outdir, stem + "_proof.lean"),
                 str(out) + "_proof.lean"):
        if os.path.isfile(cand):
            proof = cand
            break
    if proof is None:
        for root, _dirs, files in os.walk(outdir):
            for f in files:
                if f.endswith("_proof.lean"):
                    proof = os.path.join(root, f)
    if proof is None:
        raise SystemExit(f"compile_formal wrote no _proof.lean under {outdir} "
                         f"(it reported {result.get('path')!r})")
    return proof, time.time() - t


# ── profile mode ───────────────────────────────────────────────────────────

_PROFILE_LINE = re.compile(r"^(?P<what>.+?) took (?P<num>[\d.]+)(?P<unit>ms|s)$")


def parse_profile(text):
    """`lean --profile`'s lines as `(what, seconds)`, ranked, worst first.

    A DICTIONARY keyed on the label, summing repeats, because the interesting
    line is `simp took` and the file prints it once per `simp` call — a reader
    who sees eight `simp took` lines and one total has to add them up by hand,
    and adding them up by hand is how a 7.5-second cost gets reported as
    0.9. Ties are broken by label so the output is stable.
    """
    totals = {}
    for line in text.split("\n"):
        m = _PROFILE_LINE.match(line.strip())
        if not m:
            continue
        what = m.group("what").strip()
        secs = float(m.group("num")) / (1000.0 if m.group("unit") == "ms" else 1.0)
        totals[what] = totals.get(what, 0.0) + secs
    return sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))


def run_lean_raw(proof, lib_dir, extra_args=()):
    """One bounded `lean` run over `proof`; the `LeanRun` itself.

    `LEAN_PATH` is the proof's own directory and `lib/`, which is what
    `formal/lean.py::_run_lean` sets and why this must go through it rather
    than reproduce the invocation: a `lean` that cannot find `ProofLib` reports
    a module error in 0.3 s and looks like a fast proof.
    """
    import sys as _sys
    _sys.path.insert(0, HERE)
    from formal.lean import find_lean, run_lean, ensure_library
    lean = find_lean(HERE)
    if lean is None:
        raise SystemExit("no lean toolchain (see ./lean-toolchain)")
    ensure_library(lean, lib_dir)
    env = os.environ.copy()
    env["LEAN_PATH"] = os.pathsep.join(
        (os.path.dirname(os.path.abspath(proof)), os.path.abspath(lib_dir)))
    res = run_lean(lean, list(extra_args) + [os.path.basename(proof)],
                   env=env, cwd=os.path.dirname(os.path.abspath(proof)))
    # `LeanRun.wall_s` is `run_lean`'s OWN measured wall, not this tool's
    # stopwatch: the bound is checked inside `run_lean`, so a wall measured
    # outside it would keep counting after the guard killed the child and would
    # report a breach as a slow success.
    return res


def run_profile(proof, lib_dir, extra_args=("--profile",)):
    """One `lean --profile` run through `run_lean`; `(ranked, run)`.

    The profile flag is an ARGUMENT here rather than baked in, so the `goal`
    mode can elaborate the instrumented file without paying for the profile's
    own bookkeeping on a file whose timings are not the measurement.
    """
    res = run_lean_raw(proof, lib_dir, extra_args)
    return parse_profile(res.stdout or ""), res


# ── goal mode ──────────────────────────────────────────────────────────────

def flow_lines(text):
    """The line numbers of every terminal value flow's `simp +decide only`.

    Zero-based, in source order. A caller that asks for `--which 2` and there is
    one flow gets ONE line rather than an index error, because "there is only
    one" is the more useful answer than a traceback.
    """
    return [i for i, l in enumerate(text.split("\n")) if l.startswith(TERMINAL_FLOW)]


def instrument(text, which=1):
    """`(new_text, n_holes)` with the `which`-th terminal flow traced instead.

    The flow's own closing `all_goals try …` lines have to go too: they are
    tactics for a goal `trace_state` has already printed, and leaving them in
    makes Lean run `simp`/`bv_decide`/`grind` against no goals and report
    "no goals to be solved" for each. The number of holes admitted is returned
    rather than assumed, so the caller can print it — an instrumented file with
    a hole in it is NOT the file the compiler ships, and a reader who is not
    told that will read a timing as a verdict.
    """
    lines = text.split("\n")
    at = flow_lines(text)
    if not at:
        return text, 0
    i = at[min(max(which, 1), len(at)) - 1]
    holes = 0
    j = i + 1
    while j < len(lines) and lines[j].lstrip().startswith(CLOSERS):
        holes += 1
        lines[j] = None
        j += 1
    lines[i] = "      trace_state"
    new = "\n".join("      all_goals (first | done | sorry)" if l is None else l
                     for l in lines)
    # Re-admit the leaf itself: `trace_state` does not close the goal, and the
    # flow's own leaf `all_goals (first | done | sorry)` was one of the lines
    # removed above.
    new = new.replace("      trace_state\n",
                      "      trace_state\n      all_goals (first | done | sorry)\n", 1)
    return new, holes + 1


def residual_goals(stdout, stderr=""):
    """Every `⊢`-marked goal Lean's `trace_state` printed, in order.

    A LIST, not the last one, and that is a measured correction rather than a
    defensive one: `trace_state` prints one state per goal the enclosing
    combinator hands it, and on `formal/examples/bitops.mojo` instrumenting the
    FIRST terminal value flow prints three goals — the walk's own intermediate
    ones plus the flow's. A tool that returned the last one would report a
    693-character goal when the expensive one is an order of magnitude larger,
    which is a measurement of the wrong goal presented as a measurement.

    Each goal runs from its `⊢` to the next `⊢` or to the end, so a goal that
    contains a `⊢` inside its own text cannot swallow its successor.
    """
    text = (stdout or "") + "\n" + (stderr or "")
    starts = [m.start() for m in re.finditer(r"^⊢", text, re.M)]
    out = []
    for k, at in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(text)
        out.append(text[at:end].strip())
    return out


def goal_size(goal):
    """`(chars, lines, state_literals)` for a residual goal.

    `state_literals` counts the fully-expanded `{ x0 := …, …, mem := … }`
    structures, because that is the term whose SIZE the terminal flow's `simp`
    and the elaborator's type checker are paying for: on
    `formal/examples/bitops.mojo` each is 31 fields, and the same one appears
    in four hypotheses and the goal. A number a reader cannot connect to a term
    is a number they cannot act on.
    """
    lines = goal.split("\n")
    literals = len(re.findall(r"\{ x0 :=", goal))
    return len(goal), len(lines), literals


# ── main ───────────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="a .mojo file to generate a proof for")
    ap.add_argument("--arch", default="arm64", choices=("arm64", "x86_64"))
    ap.add_argument("--mode", default="profile",
                    choices=("profile", "goal", "both", "generate"))
    ap.add_argument("--which", type=int, default=1,
                    help="which terminal value flow to trace (1-based)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--keep", action="store_true",
                    help="keep the generated tree instead of a temp dir")
    args = ap.parse_args(argv)

    outdir = tempfile.mkdtemp(prefix="proofshape") if not args.keep else \
        os.path.join(HERE, "build", "proofshape")
    os.makedirs(outdir, exist_ok=True)
    report = {"source": args.source, "arch": args.arch, "mode": args.mode}
    try:
        proof, gen_s = generate(args.source, args.arch, outdir)
        report["proof"] = proof
        report["generate_seconds"] = round(gen_s, 2)
        report["proof_bytes"] = os.path.getsize(proof)
        text = open(proof).read()
        report["flows"] = len(flow_lines(text))

        if args.mode in ("goal", "both"):
            inst, holes = instrument(text, args.which)
            goal_path = os.path.join(outdir, "goal.lean")
            with open(goal_path, "w") as f:
                f.write(inst)
            res = run_lean_raw(goal_path, os.path.join(HERE, "lib"))
            goals = residual_goals(res.stdout, res.stderr)
            biggest = max(goals, key=len) if goals else ""
            chars, lines, literals = goal_size(biggest)
            report["goal"] = {
                "which": args.which,
                "flows_present": len(flow_lines(text)),
                "holes_admitted": holes,
                "instrumented_wall": res.wall_s,
                "returncode": res.returncode,
                "exceeded": res.exceeded,
                "goals_printed": len(goals),
                "goal_chars": chars,
                "goal_lines": lines,
                "state_literals": literals,
                "goals": [{"chars": len(g), "lines": g.count(chr(10)) + 1}
                          for g in goals],
            }
            if args.keep:
                report["goal"]["instrumented_proof"] = goal_path

        if args.mode in ("profile", "both"):
            ranked, res = run_profile(proof, os.path.join(HERE, "lib"))
            report["profile"] = {
                "wall": res.wall_s,
                "cpu": getattr(res, "cpu_s", None),
                "returncode": res.returncode,
                "exceeded": res.exceeded,
                "buckets": [{"what": w, "seconds": round(s, 2)}
                            for w, s in ranked],
            }
    finally:
        if not args.keep:
            shutil.rmtree(outdir, ignore_errors=True)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print(f"proof      {report['proof']} ({report['proof_bytes']} bytes, "
          f"generated in {report['generate_seconds']}s)")
    print(f"flows      {report['flows']} terminal value flow(s)")
    if "profile" in report:
        p = report["profile"]
        print(f"profile    wall {p['wall']}s cpu {p['cpu']}s rc {p['returncode']}"
              + (f" EXCEEDED: {p['exceeded']}" if p["exceeded"] else ""))
        for b in p["buckets"]:
            print(f"  {b['seconds']:8.2f}s  {b['what']}")
    if "goal" in report:
        g = report["goal"]
        print(f"goal       flow {g['which']} of {g['flows_present']}, "
              f"{g['holes_admitted']} hole(s) admitted by the instrument, "
              f"wall {g['instrumented_wall']}s")
        print(f"           {g['goals_printed']} goal(s) printed; the largest is "
              f"{g['goal_chars']} chars, {g['goal_lines']} lines, "
              f"{g['state_literals']} fully-expanded state literal(s)")
        if g["exceeded"]:
            print(f"           EXCEEDED: {g['exceeded']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())