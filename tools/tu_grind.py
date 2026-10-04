#!/usr/bin/env python3
"""Per-translation-unit native-codegen grind harness.

For each source file (smallest first), compare

    stage2/mojo --dump <file>                    (compiled/native codegen)
    python3 fire.py --dump <file>                (reference codegen)

and classify the outcome:

    CRASH   the native binary died (signal / non-zero rc)
    EMPTY   it exited 0 but produced no .ci
    GCCERR  the native .ci does not pass `gcc -fgimple -fsyntax-only`
    DIFF    the native .ci compiles but is not byte-identical to python's
    OK      byte-identical

Both sides run from the repo root (the self-host reflection injection is
CWD-gated — see test_ab_native's harness note), writing their .ci into
separate scratch dirs so neither clobbers the other.

That scratch is a PRIVATE directory per run (`formal/lean.py::scratch_dir`, the
same helper the two x86-64 model scripts use), removed when the run ends. It was
a fixed name under `$CLAUDE_JOB_DIR` or `/tmp`, which is the three-part defect
`test_formal_sweep_truth.py::TestScratchDirEstate` guards for the Lean half: a
path that may not be writable, a path SHARED between two concurrent runs — so
the second writer's `.ci` is what the first run's `gcc` reads — and no cleanup.
`TU_SCRATCH` is still honoured, and a directory named there is KEPT, which is
the reason the override exists: a caller that wants to read the `.ci` files a run
produced asks for a directory of its own.

Usage:
    tools/tu_grind.py [--limit N] [--only PAT] [--start-at FILE] [FILES...]
"""
import contextlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, HERE)

# The one private-scratch helper in the tree, rather than a second
# mkdtemp-and-rmtree here: `tools/tu_grind.py` and the two x86-64 model scripts
# want the same three properties (unique, inside `TMPDIR`, removed on the way
# out including when the body raises), and two implementations of them is how
# one of the two stops getting them.
from formal.lean import scratch_dir

GCC = os.environ.get('MOJO_GCC', '/opt/local/bin/gcc-mp-15')
STAGE2 = os.path.join(HERE, 'stage2', 'mojo')


@contextlib.contextmanager
def scratch():
    """The directory this run writes its two `.ci` sides into.

    A `TU_SCRATCH` directory is used as it stands and KEPT, which is the reason
    the override exists: a caller that wants to read the `.ci` files a run
    produced names a directory of its own, and quietly deleting them would make
    the override useless. Without it the directory is `scratch_dir`'s — unique
    per call, inside `TMPDIR`, removed on the way out including when the body
    raises, which is the `finally` inside the helper rather than one here.

    `CLAUDE_JOB_DIR` is deliberately gone: it scoped a path whose NAME was
    fixed, and the name no longer is. `mkdtemp` is unique per call, so two runs
    cannot collide whether or not anything set an environment variable, and it
    honours `TMPDIR`, which is what puts it inside a worktree's own `.tmp`.
    """
    keep = os.environ.get('TU_SCRATCH')
    if keep:
        os.makedirs(keep, exist_ok=True)
        yield keep
        return
    with scratch_dir('tu_grind') as path:
        yield path


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


def classify(src, scratch, timeout=180):
    """Returns (status, detail). `src` is a path relative to the repo root."""
    base = os.path.basename(src).rsplit('.', 1)[0]
    nat_dir = os.path.join(scratch, 'nat')
    py_dir = os.path.join(scratch, 'py')
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
                        env={'MOJO_HOME': HERE, 'PYTHONPATH': HERE})
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
    with scratch() as scratch_dir_path:
        for f in files:
            st, det = classify(f, scratch_dir_path)
            counts[st] = counts.get(st, 0) + 1
            line = '%-7s %-28s %s' % (st, f, det.replace('\n', '\n' + ' ' * 37))
            print(line, flush=True)
    print('\n== ' + '  '.join('%s=%d' % kv for kv in sorted(counts.items())),
          flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
