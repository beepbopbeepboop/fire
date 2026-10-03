#!/usr/bin/env python3
"""Compare two formal_sweep.py logs per FILE, so an architecture gap is visible.

`bugs/FORMAL_sweep_work_map_2026-10-02_b7.md` §2.5 reported the two
architectures as the same sweep: 542 files classified on both, "of those, class
CHANGED: 0", one x86-64-only row. That is the right claim and it was computed by
hand, from the two logs, with a scratch script nobody could run again — so the
next divergence would have been found the same way the last one was, by noticing
a count.

This is that computation, as a tool. It reads two logs and prints, per file:

  * `CLASS CHANGED` — classified on both arms, different verdict. A file that is
    `pass` on one arm and a refusal on the other is the machine subset falling
    behind, and the direction is the whole answer.
  * `ONLY AS A ROW ON <arch>` — a printed row on one arm and nothing on the
    other. The sweep prints one line per file that did NOT pass (see its module
    docstring), so a MISSING row is not an absent verdict: it is a `pass`. So
    this section is exactly "passes on one architecture and not on the other",
    which is why diffing the two logs' text cannot find it.
  * `REASON CHANGED` — same class on both arms, a different terminal reason or a
    different refusing module. The class is the coarse bucket, and two
    architectures land in the same bucket for different constructs all the time:
    a file that is `codegen` on both arms because one refused a subscript and the
    other a slice reads as agreement at the level of counts.

WHAT IS COMPARED, AND THE ONE NORMALISATION

A reason is compared as the sweep's OWN peel of the dependency chain
(`formal_sweep._split_chain` / `_terminal_reason`) — so this tool and
`tools/formal_sweep_causes.py` cannot come apart about where a message ends —
with every architecture LABEL in it folded to `<arch>`. That last step is not
cosmetics. An architecture-aware refusal says which machine it is talking about:
`print() cannot tell whether SubscriptExpr is a string or a number on the formal
arm64 path` and the same sentence with `x86-64` in it are one construct refused
one way, and reporting them as a divergence would be a difference in this tool's
output rather than in the backend. Both machines' labels are folded, because a
message naming both ("10 on arm64 and 0 on x86-64 for one source") is the same
sentence in both logs. An architecture name that is part of a FILE name is not
folded: `formal/x86_64_codegen.py` is the same file in both logs and is the key
the row is filed under. Folding hides a spelling, never a presence — a name one
log has and the other does not still shows up as a difference.

Exit status is 1 when any difference survives, so this can be a check rather
than a report. Zero differences is the state to hold; a difference is either a
regression or a new architecture-dependent fact, and the second has to be
explained by whoever found it.

    python3 tools/formal_sweep_parity.py bugs/sweeps/sweep-arm-7.txt \\
                                         bugs/sweeps/sweep-x86-7.txt

A NEW FILE, and not a flag on formal_sweep.py, because of one mechanism:
`formal_sweep._criteria_id()` hashes that file's own bytes into every cache key,
so a reader added to it invalidates all 668 cached verdicts and the next sweep
of either arm rebuilds the world (measured: 665 of 668 rebuilt after three
unrelated commits landed). A tool that only reads logs must not be able to do
that.

The log parsing is `formal_sweep_causes.LINE_RE` and the sweep's own chain
helpers rather than a third copy of each: a second row regex is how two readers
start disagreeing about what a line is.
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import formal_sweep_causes as CAUSES  # noqa: E402

FS = CAUSES.FS
LINE_RE = CAUSES.LINE_RE

# The summary line: `[x86_64] 668 files: PASS=125 not-pass=543`. Read for the
# architecture the log is about and for the two counts, so a report that says
# "one file differs" can be checked against the totals it was derived from.
SUMMARY_RE = re.compile(
    r"^\[(?P<arch>[a-z0-9_]+)\] (?P<files>\d+) files: PASS=(?P<pass>\d+) "
    r"not-pass=(?P<notpass>\d+)\s*$")

# An architecture NAME in a message, folded out — but only where the name is a
# LABEL for a machine rather than part of a file name. `x86_64` in "on the
# formal x86-64 path" and in "produced 10 on arm64 and 0 on x86-64 for one
# source" is a label; in `formal/x86_64_codegen.py`, `jit/arm64.py` and
# `test_arm64_emission.py` it is half a FILE NAME, and folding those renames the
# very file whose class is being compared (measured: 12 of 542 rows reported as
# differing for no reason other than that).
#
# So: not preceded by a word, `/`, `.` or `-` character (which is what keeps
# `test_arm64_emission.py` and `jit/arm64.py` whole), and not followed by a word
# character, a `/`, or a `.lowercase` (which is what keeps `x86_64_codegen.py`
# and `arm64.py` whole). `arm64-macos` still folds: a target triple names a
# machine, and the hyphen is not a word character.
ARCH_LABEL_RE = re.compile(
    r"(?<![\w./-])(?:arm64|x86_64|x86-64)(?![\w/]|\.[a-z])")
ARCH_TOKEN = "<arch>"


class Row:
    """One classified file: its class and why, from ONE arm's log."""

    __slots__ = ("cls", "refuser", "reason")

    def __init__(self, cls, refuser, reason):
        self.cls = cls
        self.refuser = refuser
        self.reason = reason

    def key(self):
        """The three facts two arms are compared on."""
        return (self.cls, self.refuser, self.reason)


def fold_arch(text):
    """Architecture labels in a reason folded to `<arch>`.

    BOTH machines' names are folded, not just the reporting arm's: a message
    that says "10 on arm64 and 0 on x86-64 for one source" is the same sentence
    in both logs, and folding only the arm doing the talking would report it as
    a divergence with one side reading `0 on x86-64` and the other `0 on <arch>`.
    Folding hides the SPELLING and never the presence: a name one log has and
    the other does not still differs, because there is nothing to fold it to.
    """
    return ARCH_LABEL_RE.sub(ARCH_TOKEN, text)


def read_log(path):
    """`(arch, rows, counts, swept, summary_pass)` for one sweep log.

    `rows` is path -> Row, and a path printed twice keeps the LAST line: that is
    the one a re-run produced. (A class that MOVED between two runs of one arm
    is what the sweep's own `verdict history:` section reports, and this tool
    compares two arms rather than two runs of one.)

    `counts` covers the printed rows only, so it has no `pass` in it — a pass
    prints nothing. The pass count is derived from the file total instead, by
    the caller, and the summary's own figure is returned beside it so the two
    can be compared rather than trusted.
    """
    with open(path, errors="replace") as f:
        lines = [raw.rstrip("\n") for raw in f]
    # The summary is at the END of a sweep log and the rows are above it, and
    # the architecture is what folds a row's reason — so it is found FIRST, from
    # the whole file, rather than discovered one row too late to be used. A
    # single pass in file order would silently compare every row un-folded and
    # then report each architecture-aware refusal as a divergence.
    arch = swept = summary_pass = None
    for line in lines:
        m = SUMMARY_RE.match(line)
        if m:
            arch = m.group("arch")
            swept = int(m.group("files"))
            summary_pass = int(m.group("pass"))
            break
    rows, counts = {}, {}
    for line in lines:
        m = LINE_RE.match(line)
        if not m:
            continue
        cls = m.group("cls").lower()
        _hops, term = FS._split_chain(m.group("detail"))
        rows[m.group("path")] = Row(
            cls=cls, refuser=FS._refuser(term),
            reason=fold_arch(FS._terminal_reason(term).strip()))
        counts[cls] = counts.get(cls, 0) + 1
    return arch, rows, counts, swept, summary_pass


def compare(arm, x86):
    """Every way two arms' rows can disagree, as four lists.

    `(changed, only_arm, only_x86, reasoned)` — existence and class first, then
    the reason behind a class both arms agree on.
    """
    changed, only_arm, only_x86, reasoned = [], [], [], []
    for path in sorted(set(arm) | set(x86)):
        a, x = arm.get(path), x86.get(path)
        if a is not None and x is None:
            only_arm.append((path, a))
        elif x is not None and a is None:
            only_x86.append((path, x))
        elif a.cls != x.cls:
            changed.append((path, a, x))
        elif a.key() != x.key():
            reasoned.append((path, a, x))
    return changed, only_arm, only_x86, reasoned


def _counts_with_pass(counts, rows, swept):
    """Per-class counts for one arm, with `pass` derived rather than parsed.

    A pass prints no line, so it is `swept - rows`, and computing it that way
    rather than reading the summary's figure keeps this table a table OF the
    rows instead of a second opinion about them.
    """
    out = dict(counts)
    if swept is not None:
        out["pass"] = swept - len(rows)
    return out


def _section(title, rows, render):
    print(f"\n{title} ({len(rows)}):")
    if not rows:
        print("  (none)")
        return
    for row in rows:
        print(render(row))


def report(arm_log, x86_log):
    """Print the comparison. Returns True when the two arms agree per file."""
    arm_arch, arm, arm_counts, arm_files, arm_pass = read_log(arm_log)
    x86_arch, x86, x86_counts, x86_files, x86_pass = read_log(x86_log)
    missing = [p for p, a in ((arm_log, arm_arch), (x86_log, x86_arch))
               if not a]
    if missing:
        raise SystemExit(
            "NOT A SWEEP LOG (no `[arch] N files: PASS=… not-pass=…` summary "
            f"line): {missing[0]}")
    if arm_arch == x86_arch:
        raise SystemExit(
            f"both logs are [{arm_arch}] sweeps. This tool compares two "
            f"architectures, and comparing a run against itself would report "
            f"the run's own noise as architecture parity")
    if arm_files != x86_files:
        raise SystemExit(
            f"the two sweeps are not over the same scope ({arm_files} files on "
            f"{arm_arch}, {x86_files} on {x86_arch}). Every difference below "
            f"would then include the files that were only in one of them, "
            f"which says nothing about either architecture. Sweep the same "
            f"roots on both arms first.")

    print(f"[{arm_arch}] {arm_log}: {arm_files} files, {len(arm)} classified, "
          f"{arm_files - len(arm)} pass (summary says {arm_pass})")
    print(f"[{x86_arch}] {x86_log}: {x86_files} files, {len(x86)} classified, "
          f"{x86_files - len(x86)} pass (summary says {x86_pass})")
    print("(a pass prints no line, so 'classified' is every file that did NOT "
          "pass; a file absent from one arm's log is a pass on that arm)")

    arm_all = _counts_with_pass(arm_counts, arm, arm_files)
    x86_all = _counts_with_pass(x86_counts, x86, x86_files)
    print("\nclass counts, and only the classes that differ:")
    diffs = [(cls, arm_all.get(cls, 0), x86_all.get(cls, 0))
             for cls in sorted(set(arm_all) | set(x86_all))
             if arm_all.get(cls, 0) != x86_all.get(cls, 0)]
    if not diffs:
        print("  (none — every class has the same count on both arms)")
    for cls, n_arm, n_x86 in diffs:
        print(f"  {cls + ':':<38} {n_arm:>5} -> {n_x86:>5} "
              f"({n_x86 - n_arm:+d} on {x86_arch})")

    changed, only_arm, only_x86, reasoned = compare(arm, x86)

    _section("CLASS CHANGED — classified on both arms, different verdict",
             changed,
             lambda r: (f"  {r[0]}\n"
                        f"      {arm_arch}: {r[1].cls}  "
                        f"{r[1].refuser or r[1].reason[:90]}\n"
                        f"      {x86_arch}: {r[2].cls}  "
                        f"{r[2].refuser or r[2].reason[:90]}"))
    _section(f"ONLY AS A ROW ON {arm_arch} — a pass on {x86_arch}", only_arm,
             lambda r: (f"  {r[0]}\n      {arm_arch}: {r[1].cls}  "
                        f"{r[1].refuser or r[1].reason[:120]}"))
    _section(f"ONLY AS A ROW ON {x86_arch} — a pass on {arm_arch}", only_x86,
             lambda r: (f"  {r[0]}\n      {x86_arch}: {r[1].cls}  "
                        f"{r[1].refuser or r[1].reason[:120]}"))
    _section("REASON CHANGED — same class on both arms, a different refusal",
             reasoned,
             lambda r: (f"  {r[0]}  ({r[1].cls})\n"
                        f"      {arm_arch}: "
                        f"{r[1].refuser + ': ' if r[1].refuser else ''}"
                        f"{r[1].reason[:160]}\n"
                        f"      {x86_arch}: "
                        f"{r[2].refuser + ': ' if r[2].refuser else ''}"
                        f"{r[2].reason[:160]}"))

    common = len(set(arm) & set(x86))
    total = len(changed) + len(only_arm) + len(only_x86) + len(reasoned)
    print(f"\n{common} file(s) classified on both arms, {total} differing "
          f"between them.")
    print(f"Reasons are compared as the terminal message with every "
          f"architecture LABEL folded to {ARCH_TOKEN}; an architecture name that "
          f"is part of a file name is left alone, because that file is the key.")

    # The one arithmetic check this report can make about itself, and it is the
    # difference between "one file's verdict differs" and "the run's own
    # bookkeeping differs". Both arms classify `common` files; a file classified
    # on one arm only is a PASS on the other, so the pass counts must differ by
    # exactly the number of one-sided rows. If they do not, then a row was lost
    # or printed twice somewhere and the differences above are not the whole
    # story — which is worth saying rather than leaving a reader to assume the
    # list is complete.
    expected = len(only_x86) - len(only_arm)
    measured = (arm_files - len(arm)) - (x86_files - len(x86))
    if expected == measured:
        print(f"accounted for: {arm_files - len(arm)} pass on {arm_arch} vs "
              f"{x86_files - len(x86)} on {x86_arch}, which is exactly the "
              f"{len(only_x86)} file(s) only {x86_arch} printed a row for and "
              f"the {len(only_arm)} only {arm_arch} did.")
    else:
        print(f"NOT ACCOUNTED FOR: the pass counts differ by {measured} and "
              f"the one-sided rows number {expected}. A row was lost or "
              f"repeated, so the differences above are not the whole story.")

    # A log whose own summary disagrees with its own rows. `swept - rows` is
    # what this report counts with, so the disagreement is invisible in every
    # number above unless it is said: it means the log is partial (a sweep
    # killed with SIGKILL publishes no summary at all, and one killed with
    # SIGTERM publishes a partial ledger and a truncated set of rows) or that a
    # second run was appended to it. Either way the files that are missing from
    # it look exactly like passes on the other arm, which is the one class of
    # difference this report must never invent.
    inconsistent = [f"[{arch}] {files} files with {n} printed row(s) is "
                    f"{files - n} pass(es), and its own summary says {said}"
                    for arch, files, n, said in
                    ((arm_arch, arm_files, len(arm), arm_pass),
                     (x86_arch, x86_files, len(x86), x86_pass))
                    if said is not None and files - n != said]
    for line in inconsistent:
        print(f"INCONSISTENT LOG: {line} — partial, or two runs in one file.")
    return total == 0 and expected == measured and not inconsistent


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", help="a formal_sweep.py log (stdout+stderr)")
    ap.add_argument("other", help="another arm's log, of a different "
                                  "architecture")
    args = ap.parse_args()
    return 0 if report(args.log, args.other) else 1


if __name__ == "__main__":
    sys.exit(main())