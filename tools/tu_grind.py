#!/usr/bin/env python3
"""Per-translation-unit shimless grind harness.

For each source file (smallest first), compare

    MOJO_NO_SHIM=1 stage2/mojo --dump <file>     (compiled codegen)
    python3 fire.py --dump <file>                (reference codegen)

and classify the outcome:

    CRASH   the native binary died (signal / non-zero rc)
    EMPTY   it exited 0 but produced no .ci
    GCCERR  the native .ci does not pass `gcc -fgimple -fsyntax-only`
    DIFF    the native .ci compiles but is not byte-identical to python's
    OK      byte-identical

Both sides run from the repo root (the self-host reflection injection is
CWD-gated — see test_ab_shim's harness note), writing their .ci into
separate scratch dirs so neither clobbers the other.

Usage:
    tools/tu_grind.py [--limit N] [--only PAT] [--start-at FILE] [FILES...]
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
SCRATCH = os.environ.get('TU_SCRATCH',
                         os.path.join(os.environ.get('CLAUDE_JOB_DIR', '/tmp'), 'tu'))
GCC = os.environ.get('MOJO_GCC', '/opt/local/bin/gcc-mp-15')
STAGE2 = os.path.join(HERE, 'stage2', 'mojo')


def _run(cmd, cwd, timeout, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    try:
        p = subprocess.run(cmd, cwd=cwd, env=e, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -99, b'', b'TIMEOUT'


def classify(src, timeout=180):
    """Returns (status, detail). `src` is a path relative to the repo root."""
    base = os.path.basename(src).rsplit('.', 1)[0]
    nat_dir = os.path.join(SCRATCH, 'nat')
    py_dir = os.path.join(SCRATCH, 'py')
    os.makedirs(nat_dir, exist_ok=True)
    os.makedirs(py_dir, exist_ok=True)
    nat_ci = os.path.join(nat_dir, base + '.ci')
    py_ci = os.path.join(py_dir, base + '.ci')
    for f in (nat_ci, py_ci):
        if os.path.exists(f):
            os.unlink(f)

    abs_src = os.path.join(HERE, src)

    # Native. `--dump` writes <basename>.ci into CWD, so give it its own dir
    # but keep MOJO_HOME/PYTHONPATH pointed at the repo so imports resolve.
    rc, out, err = _run([STAGE2, '--dump', abs_src], cwd=nat_dir, timeout=timeout,
                        env={'MOJO_NO_SHIM': '1', 'MOJO_HOME': HERE,
                             'PYTHONPATH': HERE})
    if rc < 0 or rc >= 128 or rc not in (0,):
        return 'CRASH', 'rc=%d %s' % (rc, err.decode('utf8', 'replace')[-300:])
    if not os.path.exists(nat_ci) or os.path.getsize(nat_ci) == 0:
        return 'EMPTY', 'no .ci (rc=0)'

    # gcc syntax check on the native output
    rc2, _, err2 = _run([GCC, '-fgimple', '-fsyntax-only', '-I',
                         os.path.join(HERE, 'runtime'), '-x', 'c', nat_ci],
                        cwd=HERE, timeout=timeout)
    if rc2 != 0:
        n = err2.decode('utf8', 'replace').count('error:')
        first = [l for l in err2.decode('utf8', 'replace').splitlines()
                 if 'error:' in l][:1]
        return 'GCCERR', '%d errors; %s' % (n, first[0] if first else '')

    # Reference
    rc3, _, err3 = _run([sys.executable, os.path.join(HERE, 'fire.py'),
                         '--dump', abs_src], cwd=py_dir, timeout=timeout,
                        env={'MOJO_HOME': HERE, 'PYTHONPATH': HERE})
    if rc3 != 0 or not os.path.exists(py_ci):
        return 'PYFAIL', 'python side rc=%d' % rc3

    a = open(nat_ci, 'rb').read()
    b = open(py_ci, 'rb').read()
    if a == b:
        return 'OK', '%d bytes' % len(a)
    # first differing line
    la, lb = a.split(b'\n'), b.split(b'\n')
    for i in range(min(len(la), len(lb))):
        if la[i] != lb[i]:
            return 'DIFF', ('line %d of %d/%d\n  PY : %s\n  NAT: %s'
                            % (i + 1, len(lb), len(la),
                               lb[i].decode('utf8', 'replace')[:160],
                               la[i].decode('utf8', 'replace')[:160]))
    return 'DIFF', 'length %d vs %d (common prefix equal)' % (len(b), len(a))


def main(argv):
    limit = None
    only = None
    start_at = None
    files = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--limit':
            i += 1
            limit = int(argv[i])
        elif a == '--only':
            i += 1
            only = argv[i]
        elif a == '--start-at':
            i += 1
            start_at = argv[i]
        else:
            files.append(a)
        i += 1

    if not files:
        cands = []
        for f in sorted(os.listdir(HERE)):
            if not f.endswith('.py'):
                continue
            if f.startswith('test_') or f.startswith('_'):
                continue
            cands.append(f)
        cands.sort(key=lambda f: os.path.getsize(os.path.join(HERE, f)))
        files = cands

    if only:
        files = [f for f in files if only in f]
    if start_at:
        idx = [n for n, f in enumerate(files) if start_at in f]
        if idx:
            files = files[idx[0]:]
    if limit:
        files = files[:limit]

    counts = {}
    for f in files:
        st, det = classify(f)
        counts[st] = counts.get(st, 0) + 1
        line = '%-7s %-28s %s' % (st, f, det.replace('\n', '\n' + ' ' * 37))
        print(line, flush=True)
    print('\n== ' + '  '.join('%s=%d' % kv for kv in sorted(counts.items())),
          flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
