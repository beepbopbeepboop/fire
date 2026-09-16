#!/usr/bin/env python3
"""Compares aside/ (shim) vs bside/ (self-hosted mojoc) dump output for
every file tools/ab_filelist.py discovers, and prints ONLY `FAIL:` lines
plus a totals summary — no PASS lines, by design: this is a find-at-scale
sweep meant to be run once (`make -j20 aside bside && make compare-a-b`),
with the resulting FAIL list worked through by hand, one file at a time.

Categories (a file can only match one, checked in this priority order):
  - NOT-RUN         side never produced a .meta.json (run aside/bside first)
  - SHIM-FAILED      the shim itself failed — not a self-host bug, just noise
                      to filter out until the shim-side issue is fixed
  - BOTH-FAILED      both sides failed — same caveat as SHIM-FAILED
  - SELFHOST-CRASHED shim succeeded, self-host didn't — a real self-host bug
  - CI-DIFF          both succeeded but .ci content differs — a real
                      self-host MISCOMPILE (the headline case this harness
                      exists to find)
  - AST-DIFF/TOK-DIFF  .ci matches but .tok/.ast differs — a real divergence
                      upstream of codegen (tokenizer/parser), still worth
                      fixing even though it happened not to affect this
                      particular file's C output
"""
import json
import os
import sys

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TOOLS_DIR)
sys.path.insert(0, TOOLS_DIR)
import ab_filelist as fl  # noqa: E402


def _load_meta(side_dir: str, key: str):
    p = os.path.join(REPO, side_dir, f'{key}.meta.json')
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def _read(side_dir: str, key: str, ext: str):
    p = os.path.join(REPO, side_dir, f'{key}.{ext}')
    if not os.path.exists(p):
        return None
    with open(p, 'rb') as f:
        return f.read()


def _first_diff_offset(a: bytes, b: bytes) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def main() -> int:
    entries = list(fl.discover())
    counts = {
        'total': len(entries), 'not_run': 0, 'shim_failed': 0,
        'both_failed': 0, 'selfhost_crashed': 0, 'ci_diff': 0,
        'ast_or_tok_diff': 0, 'clean': 0,
    }

    for key, _src in entries:
        meta_a = _load_meta('aside', key)
        meta_b = _load_meta('bside', key)

        if meta_a is None or meta_b is None:
            missing = 'aside' if meta_a is None else 'bside'
            print(f"FAIL: {key}: NOT-RUN ({missing} has no result — "
                  f"run `make {missing}` first)")
            counts['not_run'] += 1
            continue

        rc_a, rc_b = meta_a['rc'], meta_b['rc']

        if rc_a != 0 and rc_b != 0:
            print(f"FAIL: {key}: BOTH-FAILED (shim rc={rc_a}, self-host rc={rc_b}) "
                  f"— shim: {meta_a['stderr_tail'].strip()[-150:]!r}")
            counts['both_failed'] += 1
            continue

        if rc_a != 0:
            print(f"FAIL: {key}: SHIM-FAILED (rc={rc_a}) — not a self-host bug — "
                  f"{meta_a['stderr_tail'].strip()[-200:]!r}")
            counts['shim_failed'] += 1
            continue

        if rc_b != 0:
            print(f"FAIL: {key}: SELFHOST-CRASHED (rc={rc_b}) while shim succeeded — "
                  f"{meta_b['stderr_tail'].strip()[-200:]!r}")
            counts['selfhost_crashed'] += 1
            continue

        ci_a, ci_b = _read('aside', key, 'ci'), _read('bside', key, 'ci')
        if ci_a != ci_b:
            off = _first_diff_offset(ci_a or b'', ci_b or b'')
            print(f"FAIL: {key}: CI-DIFF (shim={len(ci_a or b'')}B, "
                  f"self-host={len(ci_b or b'')}B, first diff @{off})")
            counts['ci_diff'] += 1
            continue

        upstream_diff = None
        for ext in ('tok', 'ast'):
            va, vb = _read('aside', key, ext), _read('bside', key, ext)
            if va != vb:
                upstream_diff = ext
                break
        if upstream_diff:
            print(f"FAIL: {key}: {upstream_diff.upper()}-DIFF (.ci matched anyway — "
                  f"tokenizer/parser-only divergence)")
            counts['ast_or_tok_diff'] += 1
            continue

        counts['clean'] += 1

    print()
    print(f"Totals: {counts['total']} files — "
          f"clean={counts['clean']}, "
          f"CI-DIFF={counts['ci_diff']}, "
          f"SELFHOST-CRASHED={counts['selfhost_crashed']}, "
          f"AST/TOK-DIFF={counts['ast_or_tok_diff']}, "
          f"SHIM-FAILED={counts['shim_failed']} (not self-host bugs), "
          f"BOTH-FAILED={counts['both_failed']} (not self-host bugs), "
          f"NOT-RUN={counts['not_run']}")

    real_fails = (counts['ci_diff'] + counts['selfhost_crashed']
                  + counts['ast_or_tok_diff'])
    return 1 if real_fails or counts['not_run'] else 0


if __name__ == '__main__':
    sys.exit(main())
