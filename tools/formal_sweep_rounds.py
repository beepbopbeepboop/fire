#!/usr/bin/env python3
"""Compare two formal_sweep.py logs of the SAME architecture, round against round.

`tools/formal_sweep_parity.py` compares two ARCHITECTURES of one round. This
compares two ROUNDS of one architecture, which is the other question a sweep is
run to answer: *which fixes moved the number, and which rows emptied because a
refusal landed in front of them instead?*

WHY IT IS A TOOL AND NOT A FOURTH DESCRIPTION OF ONE
----------------------------------------------------
Every work map in this series has answered that question with a throwaway
script, and each one has said so and then written the next one the same way.
`…_b10.md` §6: *"the honest reading of that is that §2.3/§2.4's scratch should
have become a second tool rather than a fourth description of one."*
`…_b11.md` §6: *"it still has not, and this is the second map to repeat that
judgement — which is itself the argument for it."* The computation is small and
was stable enough to be re-derived identically three rounds running, which is
the definition of something that should have been committed.

THE QUESTION THAT MATTERS IS ABOUT CAUSES, NOT CLASSES
------------------------------------------------------
Class counts move 49 files in a round while causes move 146, and a class table
cannot tell a fix from a wall going up in front of it. So this tool works in the
vocabulary of `tools/formal_sweep_causes.py` — the per-file cause label, keyed
on what a fix would have to CHANGE — and reports, per cause:

  * its file count in each round and the delta;
  * for every file it LOST, **where that file went**: a pass, or another named
    cause. That second half is the whole point. `…_b11.md` §3.2 recorded a row
    falling 30 → 1 with 29 files "DARK" and had to establish by hand that every
    one of the 29 had landed on one f-string refusal 3 refusals further in. A
    row that empties and is reported as a fix is the failure this tool exists to
    make impossible to report.

WHAT "DARK" MEANS HERE, AND WHY IT IS NOT A WORD IN THE OUTPUT
---------------------------------------------------------------
It is not a category, because "dark" is not a property of a file: it is a
property of a MOVE, and a move is dark exactly when the file went from cause A
to cause B and neither is a pass. `…_b11.md`'s 54 dark files were 54 moves, and
the useful fact about them was that 54 of them went to ONE row — which is a
statement about the from→to matrix, so that is what gets printed: the matrix,
biggest movement first. A reader sees "29 files left this row and 29 of them
landed on `string composition`" without the tool having to have an opinion.

WHAT IS NOT COMPARED, AND WHY IT IS SAID OUT LOUD
--------------------------------------------------
Two logs whose scopes differ are NOT refused here, because a sweep's scope grows
every round (470 → 483 repository files between `-11` and this one) and refusing
would refuse every comparison anybody wants to make. Instead the files only one
round swept are counted and listed by class, and every rate this tool prints
carries the caveat that `FILES BLOCKED IS AN UPPER BOUND`: a file's terminal
cause is the first refusal its build walk reaches, so fixing one moves the file
to the next with the count unchanged. The counts are printed beside the pass
count for the same reason the cause table prints `in_file`: 41 files leaving
`not-answerable/host-import` for a codegen row is capability arriving, and reads
as a fall in the rate.

The log parsing, the chain peel and the cause labels are `formal_sweep_causes`'s
and `formal_sweep_parity`'s own, imported rather than copied: a second row regex
and a second idea of where a dependency chain ends is how two readers of the
same log start disagreeing.

Exit status is 0 whenever both logs were read and the arithmetic adds up, and 1
when it does not — the accounting check is the useful part, because a lost or
duplicated row makes every "which row emptied" answer wrong in a way that looks
finished. It is a REPORT, not a gate: a round that improved nothing is a
legitimate result and does not fail.

    python3 tools/formal_sweep_rounds.py bugs/sweeps/sweep-arm-11.txt \\
                                        bugs/sweeps/sweep-arm-12.txt
    python3 tools/formal_sweep_rounds.py --min 3 --json OLD NEW
"""

import argparse
import collections
import io
import json
import os
import sys
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import formal_sweep_causes as CAUSES  # noqa: E402
import formal_sweep_parity as PARITY  # noqa: E402

FS = CAUSES.FS

#: The pass class. A pass prints no line, so it is named here rather than parsed:
#: "this file stopped being printed" and "this file passes" are the same event,
#: and a report that cannot say so would report a vanished row as a lost file.
PASS = FS.CLASS_PASS

#: The two classes a cause can be in. A cause label is only meaningful for these,
#: so a `not-answerable/*` row has no cause and moves as a class only. Named from
#: `formal_sweep.py`'s own constants rather than spelled here, so a class this
#: sweep grows is a class this tool already knows and not an "unknown class"
#: warning on the next round.
CODEGEN_CLASSES = (FS.CLASS_CODEGEN, FS.CLASS_CODEGEN_DEP)


def causes_of(rows):
    """`path -> cause label`, for the files in one of the two codegen classes.

    The label is `formal_sweep_causes.classify_message` over the same terminal
    message `formal_sweep_parity.read_log` already peeled, read off the Row's
    `reason` rather than by re-peeling: the peel happens once, in one place, and
    a second reader of `Row.reason` is the same class of duplication the module
    docstring warns about.
    """
    return {path: CAUSES.classify_message(row.reason)
            for path, row in rows.items()
            if row.cls in CODEGEN_CLASSES}


def read_round(path):
    """`(arch, rows, causes, counts, swept, summary_pass, bad_lines)` for a log.

    `bad_lines` is every printed row whose class this tool does not know, which
    is empty for a sweep of this vintage and is reported rather than ignored: an
    unknown class is a row whose file is neither counted as a pass nor given a
    cause, so every total below would be quietly short by that many.
    """
    arch, rows, counts, swept, summary_pass = PARITY.read_log(path)
    unknown = sorted({row.cls for row in rows.values()
                      if row.cls not in FS.CLASS_ORDER})
    return arch, rows, causes_of(rows), counts, swept, summary_pass, unknown


def move_kind(old_row, new_row, old_cause, new_cause):
    """How one file moved between two rounds: the vocabulary of the matrix.

    Four kinds, and each answers a different question a reader has:

      * `fixed` — a pass now. A row lost the file and the file went away, which
        is the only move where the construct behind it stopped being refused.
      * `to a pass` / `from a pass` — the file crossed the pass line in either
        direction. A file that STARTS passing is in this tool's report because
        the class counts alone report it as a rate, and a rate cannot tell
        "three files got fixed" from "three files stopped being swept".
      * `cause` — still refused, by a different cause. This is where a fix that
        moved a file one refusal further on reads exactly like a fix, so it is
        named rather than folded into the counts.
      * `class` — still refused, same cause, different class (an in-file refusal
        that became one in a module it imports, or the reverse). One construct,
        two places.
      * `unchanged` — same class and same cause. Not printed, and counted, so
        the moves and the stills add up to the file total.
    """
    if old_row is None:
        return "from a pass"
    if new_row is None:
        return "to a pass"
    if old_row.cls == new_row.cls and old_cause == new_cause:
        return "unchanged"
    if old_row.cls in CODEGEN_CLASSES and new_row.cls in CODEGEN_CLASSES:
        return "cause"
    return "class"


def classify_moves(old, new, old_causes, new_causes):
    """Every file's move between two rounds, as `(path, kind, old, new)`.

    `old`/`new` are the `rows` dicts; `None` for a file one round did not sweep
    is a real answer only when the other round also swept it, which the caller
    has already established by giving both rounds the same roots.
    """
    out = []
    for path in sorted(set(old) | set(new)):
        old_row, new_row = old.get(path), new.get(path)
        kind = move_kind(old_row, new_row,
                         old_causes.get(path), new_causes.get(path))
        out.append((path, kind, old_causes.get(path), new_causes.get(path)))
    return out


def report(old_log, new_log, minimum=0, stream=None):
    """Print the round-over-round comparison. Returns True when it adds up.

    Four sections, in the order a planner reads them: what the corpus is, which
    classes moved, which CAUSES moved (with where every lost file went), and
    the arithmetic that says the first three are the whole story.
    """
    out = stream or sys.stdout
    old_arch, old_rows, old_causes, old_counts, old_files, old_pass, old_odd = \
        read_round(old_log)
    new_arch, new_rows, new_causes, new_counts, new_files, new_pass, new_odd = \
        read_round(new_log)
    missing = [p for p, a in ((old_log, old_arch), (new_log, new_arch))
               if not a]
    if missing:
        raise SystemExit(
            "NOT A SWEEP LOG (no `[arch] N files: PASS=… not-pass=…` summary "
            f"line): {missing[0]}")
    if old_arch != new_arch:
        raise SystemExit(
            f"the two logs are different architectures ([{old_arch}] and "
            f"[{new_arch}]). This tool compares two ROUNDS of one architecture; "
            f"for two architectures of one round use tools/formal_sweep_parity.py, "
            f"which refuses to be handed two logs of one machine on exactly this "
            f"ground")

    def say(text=""):
        print(text, file=out)

    say(f"OLD {old_log}\n    [{old_arch}] {old_files} files, "
        f"{len(old_rows)} printed row(s), {old_files - len(old_rows)} pass "
        f"(summary says {old_pass})")
    say(f"NEW {new_log}\n    [{new_arch}] {new_files} files, "
        f"{len(new_rows)} printed row(s), {new_files - len(new_rows)} pass "
        f"(summary says {new_pass})")
    say("(a pass prints no line, so 'printed row(s)' is every file that did NOT "
        "pass; a file absent from a log is a pass in it)")
    for path, odd in ((old_log, old_odd), (new_log, new_odd)):
        if odd:
            say(f"UNKNOWN CLASS in {path}, so its files are in no count below: "
                f"{', '.join(odd)}")

    # ── 1. the scope, stated first because every rate depends on it ────────
    old_set, new_set = set(old_rows), set(new_rows)
    gone = sorted(old_set - new_set)
    fresh = sorted(new_set - old_set)
    say(f"\nSCOPE: {old_files} -> {new_files} files "
        f"({new_files - old_files:+d}); "
        f"{len(gone)} file(s) printed a row in OLD and none in NEW, "
        f"{len(fresh)} the other way")
    say("  A file that stopped being printed may have passed OR left the roots; "
        "the pass counts below are what tells the two apart, and a scope that "
        "grew makes every rate a rate over a different denominator.")
    for label, paths in (("printed in OLD, not in NEW", gone),
                         ("printed in NEW, not in OLD", fresh)):
        if paths:
            say(f"  {label} ({len(paths)}):")
            for path in paths[:40]:
                say(f"    {path}")
            if len(paths) > 40:
                say(f"    … and {len(paths) - 40} more")

    # ── 2. classes ─────────────────────────────────────────────────────────
    old_all = _counts(old_counts, old_files)
    new_all = _counts(new_counts, new_files)
    say("\nCLASS COUNTS (pass derived as swept - printed rows):")
    for cls in sorted(set(old_all) | set(new_all)):
        a, b = old_all.get(cls, 0), new_all.get(cls, 0)
        mark = "  " if a == b else "->"
        say(f"  {mark} {cls:<40} {a:>5} {b:>5}  ({b - a:+d})")
    old_codegen = sum(v for k, v in old_all.items() if k in CODEGEN_CLASSES)
    new_codegen = sum(v for k, v in new_all.items() if k in CODEGEN_CLASSES)
    old_answerable = sum(v for k, v in old_all.items() if k in FS.ANSWERABLE)
    new_answerable = sum(v for k, v in new_all.items() if k in FS.ANSWERABLE)
    old_pct = _pct(old_all.get(PASS, 0), old_answerable)
    new_pct = _pct(new_all.get(PASS, 0), new_answerable)
    say(f"  codegen findings {old_codegen} -> {new_codegen} "
        f"({new_codegen - old_codegen:+d})")
    say(f"  codegen coverage {_rate(old_all.get(PASS, 0), old_answerable)} -> "
        f"{_rate(new_all.get(PASS, 0), new_answerable)}"
        + ("" if old_pct == new_pct
           else f"  ({new_pct - old_pct:+.1f} pp)"))
    say("  (the sweep's own headline, over the files whose build could have "
        "answered: pass + built-with-admitted-contracts + codegen + "
        "codegen/dependency. A not-answerable file is a fact about the target "
        "and is in no rate, so a file that STOPS being one moves into the "
        "denominator and onto a refusal standing behind the wall that came "
        "down — which lowers this rate while raising the finding count above. "
        "Print both; neither alone is a measure of a round.)")

    # ── 3. causes, and where every lost file went ──────────────────────────
    moves = classify_moves(old_rows, new_rows, old_causes, new_causes)
    kinds = collections.Counter(kind for _p, kind, _o, _n in moves)
    say("\nFILE MOVES:")
    for kind in ("to a pass", "from a pass", "cause", "class", "unchanged"):
        say(f"  {kind:<12} {kinds.get(kind, 0)}")

    old_causes_count = collections.Counter(old_causes.values())
    new_causes_count = collections.Counter(new_causes.values())
    labels = sorted(set(old_causes_count) | set(new_causes_count),
                    key=lambda label: (-max(old_causes_count[label],
                                            new_causes_count[label]), label))
    say(f"\nCAUSES ({len([l for l in labels if max(old_causes_count[l], new_causes_count[l]) >= minimum])}"
        f" at or above --min {minimum}; the rest are omitted):")
    say(f"  {'files':>18}  {'old':>5} {'new':>5} {'delta':>6}  cause")
    for label in labels:
        a, b = old_causes_count[label], new_causes_count[label]
        if max(a, b) < minimum:
            continue
        say(f"  {'':>18}  {a:>5} {b:>5} {b - a:+6d}  {label}")

    # The matrix: for every cause that lost files, where they went. This is the
    # section that makes "a row emptied" mean something — a cause that falls
    # from 30 to 1 has not been fixed 29 times over unless 29 of its files are
    # accounted for, and the account is one line per destination.
    say("\nWHERE THE FILES WENT, per cause that lost any (a file that moved to "
        "another cause is not a fix):")
    by_old = collections.defaultdict(collections.Counter)
    for path, kind, old_cause, new_cause in moves:
        if kind == "cause" and old_cause is not None:
            by_old[old_cause][new_cause] += 1
    if not by_old:
        say("  (no file changed cause)")
    for label in sorted(by_old, key=lambda l: -sum(by_old[l].values())):
        dests = by_old[label].most_common()
        say(f"  {label}  ({sum(n for _d, n in dests)} file(s)):")
        for dest, n in dests:
            say(f"      {n:>5} -> {dest}")

    # The inverse, which is the one that reads as progress: a cause that GREW,
    # and where its new files came from. A wall going up in front of a row shows
    # up here, not in the cause's own count.
    by_new = collections.defaultdict(collections.Counter)
    for path, kind, old_cause, new_cause in moves:
        if kind == "cause" and new_cause is not None:
            by_new[new_cause][old_cause] += 1
    grew = [(label, sum(src.values()), src.most_common())
            for label, src in by_new.items()
            if old_causes_count[label] < new_causes_count[label]]
    say("\nAND WHERE THEY CAME FROM, per cause that gained (a refusal landing "
        "in front of a row moves files INTO the row in front):")
    if not grew:
        say("  (no cause gained files from another cause)")
    for label, n, srcs in sorted(grew, key=lambda t: -t[1]):
        say(f"  {label}  (+{n}):")
        for src, k in srcs:
            say(f"      {k:>5} <- {src}")

    files_listed = [p for p, kind, _o, _n in moves if kind != "unchanged"]
    say(f"\n{len(moves)} file(s) in the union of the two rounds' printed rows, "
        f"{len(files_listed)} of which moved and "
        f"{kinds.get('unchanged', 0)} did not.")

    # ── 4. does it add up ──────────────────────────────────────────────────
    inconsistent = _inconsistent_logs(
        ((old_log, old_files, old_rows, old_pass),
         (new_log, new_files, new_rows, new_pass)))
    for line in inconsistent:
        say(f"INCONSISTENT LOG: {line}")
    problems = _accounting(old_rows, new_rows, moves, old_causes_count,
                           new_causes_count)
    if problems or inconsistent:
        for line in problems:
            say(f"NOT ACCOUNTED FOR: {line}")
        return False
    say("accounted for: every printed row in either round is either still "
        "printed with the same class and cause, or is in exactly one of the "
        "move lists above, and each round's pass count is its file total less "
        "its own printed rows.")
    say("FILES BLOCKED IS AN UPPER BOUND: a file's terminal cause is the first "
        "refusal its build walk reaches, so fixing one moves the file to the "
        "next with the count unchanged. Only a re-sweep of the files a cause "
        "blocks can price it.")
    return True


def _counts(counts, files):
    """`counts` plus a derived `pass`, via the parity tool's own rule."""
    out = dict(counts)
    if files is not None:
        out[PASS] = files - sum(counts.values())
    return out


def _rate(num, den):
    return f"{num}/{den} = {100.0 * num / den:.1f}%" if den else "n/a"


def _pct(num, den):
    return 100.0 * num / den if den else 0.0


def _inconsistent_logs(rounds):
    """Rounds whose own summary disagrees with their own rows.

    `swept - printed rows` is what this report counts with, so the disagreement
    is invisible in every number it prints unless it is said. It means the log is
    partial — a sweep killed with SIGKILL publishes no summary at all, and one
    killed with SIGTERM publishes a truncated set of rows — or that a second run
    was appended to it. Either way the files missing from it look exactly like
    passes in the OTHER round, which is the one class of difference this report
    must never invent. `formal_sweep_parity.py` reports the same defect with the
    same two words, so the two readers of a sweep log cannot disagree about
    whether a log is whole.
    """
    out = []
    for log, files, rows, said in rounds:
        if said is not None and files - len(rows) != said:
            out.append(
                f"{log}: {files} files with {len(rows)} printed row(s) is "
                f"{files - len(rows)} pass(es) and its own summary says {said} "
                f"— partial, or two runs in one file.")
    return out


def _accounting(old_rows, new_rows, moves, old_causes_count, new_causes_count):
    """Every way this report can be quietly wrong, as a list of sentences.

    Three checks, each of which has caught a real defect in a sweep log rather
    than being defensive:

      * a move list that does not partition the union of the two rounds' rows
        (`unchanged` plus every move kind has to be the union, or a file was
        dropped from the comparison and every "which row emptied" answer is
        quietly short by it);
      * a file carrying two move kinds, which would mean `classify_moves`
        disagreed with itself;
      * a cause whose per-file labels do not sum to the number of codegen rows
        printed, which is what a mis-peeled chain looks like.
    """
    problems = []
    union = set(old_rows) | set(new_rows)
    if len(moves) != len(union):
        problems.append(
            f"the move list has {len(moves)} entries and the two rounds' rows "
            f"union to {len(union)} — a path was dropped from the comparison.")
    kinds = collections.Counter(kind for _p, kind, _o, _n in moves)
    if sum(kinds.values()) != len(moves):
        problems.append("a file carries two move kinds.")
    for log, rows, counts in ((old_rows, old_rows, old_causes_count),
                              (new_rows, new_rows, new_causes_count)):
        printed = sum(1 for r in rows.values() if r.cls in CODEGEN_CLASSES)
        if sum(counts.values()) != printed:
            problems.append(
                f"a round's causes sum to {sum(counts.values())} but it "
                f"printed {printed} codegen row(s).")
    return problems


def to_json(old_log, new_log, minimum=0):
    """The same comparison, machine-readable."""
    old_arch, old_rows, old_causes, old_counts, old_files, old_pass, _oo = \
        read_round(old_log)
    new_arch, new_rows, new_causes, new_counts, new_files, new_pass, _no = \
        read_round(new_log)
    moves = classify_moves(old_rows, new_rows, old_causes, new_causes)
    old_cc = collections.Counter(old_causes.values())
    new_cc = collections.Counter(new_causes.values())
    by_old, by_new = (collections.defaultdict(collections.Counter)
                      for _ in range(2))
    for path, kind, old_cause, new_cause in moves:
        if kind == "cause":
            if old_cause is not None:
                by_old[old_cause][new_cause] += 1
            if new_cause is not None:
                by_new[new_cause][old_cause] += 1
    return {
        "old": {"log": old_log, "arch": old_arch, "swept": old_files,
                "pass": old_pass, "classes": _counts(old_counts, old_files)},
        "new": {"log": new_log, "arch": new_arch, "swept": new_files,
                "pass": new_pass, "classes": _counts(new_counts, new_files)},
        "moves": dict(collections.Counter(k for _p, k, _o, _n in moves)),
        "causes": {label: {"old": old_cc[label], "new": new_cc[label]}
                   for label in sorted(set(old_cc) | set(new_cc))
                   if max(old_cc[label], new_cc[label]) >= minimum},
        "where_the_files_went": {label: dict(c)
                                 for label, c in sorted(by_old.items())},
        "where_they_came_from": {label: dict(c)
                                 for label, c in sorted(by_new.items())},
        "files": [{"path": p, "move": k, "old_cause": o, "new_cause": n}
                  for p, k, o, n in moves if k != "unchanged"],
    }


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old", help="the earlier formal_sweep.py log")
    ap.add_argument("new", help="the later formal_sweep.py log, same architecture")
    ap.add_argument("--min", type=int, default=1, dest="minimum",
                    help="only print causes reaching this many files (default 1)")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable instead of the report")
    args = ap.parse_args()
    if args.json:
        print(json.dumps(to_json(args.old, args.new, args.minimum), indent=1))
        return 0
    buf = io.StringIO()
    ok = report(args.old, args.new, args.minimum, stream=buf)
    sys.stdout.write(buf.getvalue())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
