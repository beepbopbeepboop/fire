#!/usr/bin/env python3
"""test_coro_scoreboard.py -- the before/after scoreboard for the A3
coroutine-codegen work (doc/COROUTINE.html §5.1).

For every bug report in bugs/ and bugs/hard/ that names a `Source file:`,
run `python3 fire.py build` on it and record the outcome:

    compile  -> .ci/.o produced
    link     -> an executable produced
    run      -> the executable exits 0

Outcomes are bucketed. The JSON summary is written to
build/coro_scoreboard.<tag>.json (tag = value of MOJO_CORO, or "cpp").
Compare two runs with `--diff a.json b.json`.

Usage:
    python3 test_coro_scoreboard.py                 # run, write baseline
    MOJO_CORO=stackswitch python3 test_coro_scoreboard.py
    python3 test_coro_scoreboard.py --diff build/coro_scoreboard.cpp.json \
                                          build/coro_scoreboard.stackswitch.json
"""
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BUGS = [os.path.join(HERE, 'bugs'), os.path.join(HERE, 'bugs', 'hard')]
SRC_RE = re.compile(r'^Source file:\s*(\S+)', re.M)


def _targets():
    out = {}
    for d in BUGS:
        for fn in sorted(os.listdir(d)):
            if not fn.endswith('.md'):
                continue
            p = os.path.join(d, fn)
            m = SRC_RE.search(open(p, encoding='utf-8', errors='replace').read())
            if m and os.path.exists(m.group(1)):
                out[os.path.relpath(p, HERE)] = m.group(1)
    return out


FAST = os.environ.get('CORO_SB_FAST') == '1'


def _classify_fast(report, src):
    """Compile-only classification via compile_to_gimple_with_cpp -- seconds,
    not minutes (no link, no full-stdlib build). Buckets: refused-generator
    (fell through to the cpp path and it refused), compile-ok (produced C),
    compile-fail (raised)."""
    import gimple_codegen
    try:
        c, cpp = gimple_codegen.compile_to_gimple_with_cpp(
            open(src).read(), do_imports=False, filename=src)
        if '__mgco_' in c:
            return report, 'stackswitch-lowered', ''
        return report, 'compile-ok', ''
    except Exception as e:
        s = f'{type(e).__name__}: {e}'
        low = s.lower()
        if 'unsupportedgeneratorshape' in low or 'refus' in low:
            return report, 'refused-generator', s[:300]
        return report, 'compile-fail', s[:300]


def _classify(report, src):
    if FAST:
        try:
            return _classify_fast(report, src)
        except Exception as e:
            return report, 'harness-error', str(e)[:200]
    wd = tempfile.mkdtemp(prefix='coro_sb_')
    exe = os.path.join(wd, 'a.out')
    env = dict(os.environ)
    try:
        cp = subprocess.run([sys.executable, os.path.join(HERE, 'fire.py'),
                             'build', src, '-o', exe],
                            capture_output=True, text=True, timeout=600, cwd=wd, env=env)
    except subprocess.TimeoutExpired:
        return report, 'timeout', ''
    blob = (cp.stdout + cp.stderr)
    if cp.returncode != 0 or not os.path.exists(exe):
        # crude bucket of the failure
        low = blob.lower()
        if 'unsupportedgeneratorshape' in low or 'refus' in low:
            b = 'refused-generator'
        elif 'link failed' in low or 'undefined symbol' in low or 'ld:' in low:
            b = 'link-fail'
        elif 'compilation failed' in low or 'error:' in low:
            b = 'compile-fail'
        else:
            b = 'build-fail'
        return report, b, blob[-600:]
    try:
        rp = subprocess.run([exe], capture_output=True, text=True, timeout=90, cwd=wd)
        return report, ('run-ok' if rp.returncode == 0 else 'run-nonzero'), \
            (rp.stdout + rp.stderr)[-400:]
    except subprocess.TimeoutExpired:
        return report, 'run-timeout', ''


def run():
    # §5.5 cutover: stackswitch is now the default backend (unset ==
    # stackswitch, not cpp -- see gimple_gen_coro.enabled()).
    tag = os.environ.get('MOJO_CORO', 'stackswitch')
    tgts = _targets()
    print(f'scoreboard tag={tag}  targets={len(tgts)}')
    results = {}
    with cf.ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 4))) as ex:
        futs = {ex.submit(_classify, r, s): r for r, s in tgts.items()}
        for i, f in enumerate(cf.as_completed(futs), 1):
            r, bucket, detail = f.result()
            results[r] = {'bucket': bucket, 'detail': detail}
            print(f'[{i:3d}/{len(tgts)}] {bucket:18s} {r}')
    buckets = {}
    for v in results.values():
        buckets[v['bucket']] = buckets.get(v['bucket'], 0) + 1
    summary = {'tag': tag, 'buckets': buckets, 'results': results}
    os.makedirs(os.path.join(HERE, 'build'), exist_ok=True)
    outp = os.path.join(HERE, 'build', f'coro_scoreboard.{tag}.json')
    json.dump(summary, open(outp, 'w'), indent=1, sort_keys=True)
    print('\n=== buckets ===')
    for b, n in sorted(buckets.items(), key=lambda kv: -kv[1]):
        print(f'  {n:4d}  {b}')
    print(f'\nwrote {outp}')
    return 0


# higher rank == better outcome
_RANK = {
    'timeout': 0, 'harness-error': 0, 'build-fail': 1, 'compile-fail': 2,
    'refused-generator': 3, 'link-fail': 4, 'run-timeout': 4, 'run-nonzero': 5,
    'compile-ok': 6, 'stackswitch-lowered': 7, 'run-ok': 9,
}


def diff(a, b):
    A = json.load(open(a)); B = json.load(open(b))
    ra, rb = A['results'], B['results']
    print(f'{"report":58s}  {A["tag"]:>18s} -> {B["tag"]:<18s}')
    improved = regressed = 0
    for k in sorted(set(ra) | set(rb)):
        ba = ra.get(k, {}).get('bucket', '-')
        bb = rb.get(k, {}).get('bucket', '-')
        if ba == bb:
            continue
        da, db = _RANK.get(ba, 0), _RANK.get(bb, 0)
        mark = '+' if db > da else ('-' if db < da else ' ')
        if db > da:
            improved += 1
        elif db < da:
            regressed += 1
        print(f'{mark} {k:56s}  {ba:>18s} -> {bb:<18s}')
    print(f'\nimproved: {improved}   regressed: {regressed}')
    return 1 if regressed else 0


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == '--diff':
        sys.exit(diff(sys.argv[2], sys.argv[3]))
    sys.exit(run())
