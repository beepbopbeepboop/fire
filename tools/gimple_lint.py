#!/usr/bin/env python3
"""Type-check emitted GIMPLE text (`.ci` files) with the typed IR in mojo/ir.

GCC only verifies functions tagged `__GIMPLE`, and never checks call
arguments.  This checks every three-address function, tagged or not.

    python3 tools/gimple_lint.py a.ci b.ci        # summary by finding code
    python3 tools/gimple_lint.py -v a.ci          # every finding
    python3 tools/gimple_lint.py --code copy-int-narrow -v a.ci
    python3 tools/gimple_lint.py --json a.ci      # machine-readable counts

Finding codes are documented in mojo/ir/verify.py and doc/GIR.md.
Exit status: 0 always, unless --fail-on names a code that occurred.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mojo.ir import reader, verify  # noqa: E402


def lint_file(path: str):
    mod = reader.read_ci(path, [os.path.join(ROOT, 'runtime')])
    rep = verify.Report()
    verify.verify_module(mod, rep)
    return mod, rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('files', nargs='+')
    ap.add_argument('-v', '--verbose', action='store_true', help='print every finding')
    ap.add_argument('--code', action='append', default=[], help='only these codes')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--examples', type=int, default=2, help='examples per code in the summary')
    ap.add_argument('--fail-on', action='append', default=[])
    args = ap.parse_args(argv)

    counts: dict[str, list[int]] = {}        # code -> [tagged, untagged]
    examples: dict[str, list[str]] = {}
    unknown: dict[str, int] = {}
    tot_fn = tot_opq = tot_stmt = skipped = stmt_opq = 0
    for path in args.files:
        mod, rep = lint_file(path)
        tot_fn += rep.functions
        tot_opq += rep.functions_opaque
        tot_stmt += rep.stmts
        stmt_opq += rep.stmts_opaque
        skipped += mod.skipped
        for k, n in rep.unknown.items():
            unknown[k] = unknown.get(k, 0) + n
        for f in rep.findings:
            if args.code and f.code not in args.code:
                continue
            c = counts.setdefault(f.code, [0, 0])
            c[0 if f.tagged else 1] += 1
            line = (f"{os.path.basename(path)}:{f.out_line}: {f.code}: {f.detail}\n"
                    f"    in {f.fn}{' [__GIMPLE]' if f.tagged else ''} (source line {f.src_line}):  {f.stmt}")
            if args.verbose:
                print(line)
            ex = examples.setdefault(f.code, [])
            if len(ex) < args.examples:
                ex.append(line)
    if args.json:
        print(json.dumps({'counts': {k: sum(v) for k, v in sorted(counts.items())},
                          'functions': tot_fn, 'functions_opaque': tot_opq,
                          'statements': tot_stmt, 'statements_opaque': stmt_opq,
                          'unknown': unknown,
                          'toplevel_skipped': skipped}, indent=1, sort_keys=True))
    else:
        print(f"{len(args.files)} file(s): {tot_fn} functions "
              f"({tot_opq} contain hand-written C), {tot_stmt} statements checked, "
              f"{stmt_opq} hand-written statements not modelled, "
              f"{skipped} top-level items not modelled")
        print("not provable (skipped, never reported): "
              + (', '.join(f"{k} {n}" for k, n in sorted(unknown.items())) or 'none'))
        total = sum(sum(v) for v in counts.values())
        print(f"\n{total} findings")
        print(f"{'code':<22}{'total':>8}{'in __GIMPLE':>13}{'untagged':>10}  GCC-rejects-if-tagged")
        for code, (t, u) in sorted(counts.items(), key=lambda kv: -sum(kv[1])):
            print(f"{code:<22}{t + u:>8}{t:>13}{u:>10}  {'yes' if verify.is_gimple_illegal(code) else 'no'}")
            if not args.verbose:
                for ex in examples[code]:
                    print('    ' + ex.replace('\n', '\n    '))
    for code in args.fail_on:
        if counts.get(code):
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
