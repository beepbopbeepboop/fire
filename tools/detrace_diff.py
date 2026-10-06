#!/usr/bin/env python3
"""Find the first divergence between two determinism-trace streams.

Reads two files of `<iota> <hash>` lines (produced by
`determinism_trace.note()` with `MOJO_TRACE=1` set) and prints the first
iota at which they differ, with the two hashes and a few lines of context.
This is the scripted form of `diff a b | sed 10q`: it hands you a step
number to break on, not "somewhere in the whole compile".

Usage:
    MOJO_TRACE=1 MOJO_TRACE_FILE=/tmp/ref.txt python3 fire.py X.py --dump
    MOJO_TRACE=1 MOJO_TRACE_FILE=/tmp/nat.txt ./mojoc X.py --dump
    tools/detrace_diff.py /tmp/ref.txt /tmp/nat.txt [--context N]
"""
import argparse
import sys


def load(path):
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(line.split())
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('a')
    ap.add_argument('b')
    ap.add_argument('--context', type=int, default=3)
    args = ap.parse_args()

    a, b = load(args.a), load(args.b)
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            print(f"first divergence at iota {a[i][0]} (index {i}):")
            lo = max(0, i - args.context)
            for j in range(lo, min(i + args.context + 1, n)):
                mark = '  <<<' if j == i else ''
                print(f"  {a[j][0]:>10} {a[j][1]:>20} | {b[j][0]:>10} {b[j][1]:>20}{mark}")
            return 1
    if len(a) != len(b):
        i = n
        longer = 'a' if len(a) > len(b) else 'b'
        print(f"streams agree for {n} steps, then {longer} has {abs(len(a)-len(b))} more")
        return 1
    print(f"IDENTICAL: {n} steps")
    return 0


if __name__ == '__main__':
    sys.exit(main())
