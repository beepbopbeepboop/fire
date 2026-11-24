#!/usr/bin/env python3
"""Read the type solver's ledger (FIRE_TSOLVE_LEDGER) and summarize it.

    python3 tools/tsolve_why.py --classify LEDGER   # one row per decided name, by kind
    python3 tools/tsolve_why.py --shadow LEDGER     # the solver/backend disagreements (S2)
    python3 tools/tsolve_why.py --undecided LEDGER  # undecided names, by reason

The ledger is written by the compile (bugs/GIR_type_solver_precision.md, 4.5): one
`early`, `conflict`, `undecided reason=...` or `shadow solver=... measured=...` line per
name, then a `summary` line. This tool is not in the closure and may use any library.
"""
import collections
import sys


def read_lines(path: str) -> list:
    with open(path) as f:
        return [ln.rstrip('\n') for ln in f if ln.strip()]


def classify(lines: list) -> None:
    kinds = collections.OrderedDict()
    for ln in lines:
        if ln.startswith('summary'):
            print(ln)
            continue
        parts = ln.split(' ')
        kind = parts[0]
        name = parts[1] if len(parts) > 1 else ''
        kinds.setdefault(kind, []).append(name)
    for kind in kinds:
        names = sorted(set(kinds[kind]))
        print('%-10s %4d lines, %4d names' % (kind, len(kinds[kind]), len(names)))


def shadow(lines: list) -> None:
    rows = [ln for ln in lines if ln.startswith('shadow ')]
    print('shadow: %d names disagree' % len(rows))
    for ln in sorted(rows):
        print(' ', ln[len('shadow '):])


def undecided(lines: list) -> None:
    counts = collections.Counter()
    for ln in lines:
        if ln.startswith('undecided '):
            reason = ln.rsplit('reason=', 1)[-1] if 'reason=' in ln else '?'
            counts[reason] += 1
    for reason, n in counts.most_common():
        print('%-14s %d names' % (reason, n))


def main(argv: list) -> int:
    if len(argv) != 2 or argv[0] not in ('--classify', '--shadow', '--undecided'):
        print(__doc__)
        return 2
    lines = read_lines(argv[1])
    {'--classify': classify, '--shadow': shadow, '--undecided': undecided}[argv[0]](lines)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
