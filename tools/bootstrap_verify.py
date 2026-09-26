#!/usr/bin/env python3
"""Compare the three bootstrap stage trees: stage1 == stage2 == stage3.

The last step of the 3-stage self-host, and the one that says whether the
self-hosted compiler is a fixed point: the python reference compiles the
compiler, the compiled compiler compiles itself, and the same binary compiles
itself a third time. If stage2 and stage3 differ, the compiler is not
deterministic; if stage1 and stage2 differ, the compiled compiler is not
computing what the reference computes.

This was a Make recipe (`for ext in ci tok ast pyi; do for f in stage1/*.$ext`)
and is a script now for two reasons. The recipe could only report *which* file
differed, and when it did, the useful next step was to find *where* — so a
mismatch here names the first differing line and shows both sides of it. And
it reports its own counts, so `tools/suite.py` can put a real verdict in the
run's single tally instead of trusting an exit code alone.

Verdict: exit 1 if any present-in-all-three file differs. A file that is
missing from one stage is reported as a WARNING and counted separately, not
failed — that asymmetry is deliberate and inherited: the stage drivers dump the
same input list at every stage, so a file missing from a stage is a driver
problem worth seeing, but it is not evidence of a codegen divergence, and
failing on it would conflate the two. Use --strict to make it fail.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
STAGES = ('stage1', 'stage2', 'stage3')
EXTS = ('ci', 'tok', 'ast', 'pyi')
CHUNK = 1 << 20


def artefacts():
    """`name -> {stage: path}` for every generated file in any stage, keyed by
    basename. The union, not just stage1's: a file that only one stage
    produced is exactly the asymmetry worth reporting, and iterating stage1
    alone (as the old recipe did) could not see it."""
    out = {}
    for stage in STAGES:
        d = os.path.join(REPO, stage)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            for ext in EXTS:
                if name.endswith(f'.{ext}'):
                    out.setdefault(name, {})[stage] = os.path.join(d, name)
    return out


def first_diff(path_a, path_b):
    """Byte offset of the first difference, or None if the files are equal."""
    off = 0
    with open(path_a, 'rb') as fa, open(path_b, 'rb') as fb:
        while True:
            ca, cb = fa.read(CHUNK), fb.read(CHUNK)
            m = min(len(ca), len(cb))
            for i in range(m):
                if ca[i] != cb[i]:
                    return off + i
            off += m
            if len(ca) != len(cb):
                return off
            if not ca:
                return None


def line_of(path, offset, context=2):
    """(line_no, [lines around it]) for a byte offset — where a reader has to
    start looking."""
    with open(path, 'rb') as f:
        head = f.read(offset)
        no = head.count(b'\n') + 1
        start = max(0, no - 1 - context)
        f.seek(0)
        lines = []
        for i, raw in enumerate(f, 1):
            if start < i <= no + context:
                lines.append((i, raw.decode('utf-8', 'replace').rstrip('\n')))
            if i > no + context:
                break
    return no, lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('-q', '--quiet', action='store_true',
                    help='print only mismatches and missing files')
    ap.add_argument('--strict', action='store_true',
                    help='also fail when a file is missing from a stage')
    opts = ap.parse_args(argv)

    for stage in STAGES:
        if not os.path.isdir(os.path.join(REPO, stage)):
            print(f'FAIL: {stage}/ does not exist — run the bootstrap stages '
                  f'first', file=sys.stderr)
            return 2

    files = artefacts()
    if not files:
        print('FAIL: no generated files in any stage tree', file=sys.stderr)
        return 2

    ok = diff12 = diff23 = missing = 0
    for name in sorted(files):
        where = files[name]
        present = [s for s in STAGES if s in where]
        if len(present) != 3:
            missing += 1
            print(f'MISSING {name}: present in '
                  f'{", ".join(s + "/" for s in present) or "no stage"}')
            continue
        d12 = first_diff(where['stage1'], where['stage2'])
        d23 = first_diff(where['stage2'], where['stage3'])
        if d12 is None and d23 is None:
            ok += 1
            if not opts.quiet:
                print(f'  ok   {name}')
            continue
        if d12 is not None:
            diff12 += 1
            print(f'DIFF  {name}: stage1 vs stage2 first differ at byte '
                  f'{d12}')
            _show(where['stage1'], where['stage2'], d12)
        if d23 is not None:
            diff23 += 1
            print(f'DIFF  {name}: stage2 vs stage3 first differ at byte '
                  f'{d23}')
            _show(where['stage2'], where['stage3'], d23)

    print()
    print(f'verify: {ok} identical, {diff12} stage1-vs-stage2 diff(s), '
          f'{diff23} stage2-vs-stage3 diff(s), {missing} missing from a stage '
          f'({len(files)} files)')
    if missing:
        print('  a file missing from a stage is a driver problem, not evidence '
              'of a codegen divergence; --strict fails on it too')
    bad = diff12 + diff23 + (missing if opts.strict else 0)
    return 1 if bad else 0


def _show(path_a, path_b, offset):
    try:
        no_a, lines_a = line_of(path_a, offset)
        no_b, lines_b = line_of(path_b, offset)
    except OSError as exc:
        print(f'      (could not read around the difference: {exc})')
        return
    size_a = os.path.getsize(path_a)
    size_b = os.path.getsize(path_b)
    print(f'      {os.path.basename(path_a)} {size_a} bytes vs '
          f'{os.path.basename(path_b)} {size_b} bytes')
    print(f'      {os.path.basename(path_a)}:{no_a}')
    for i, text in lines_a:
        print(f'        {i:>8} | {text[:160]}')
    print(f'      {os.path.basename(path_b)}:{no_b}')
    for i, text in lines_b:
        print(f'        {i:>8} | {text[:160]}')


if __name__ == '__main__':
    sys.exit(main())
