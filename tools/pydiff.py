#!/usr/bin/env python3
"""Run small Python programs through CPython and through the gimple backend,
and report every program whose compiled result differs.

    python3 tools/pydiff.py DIR_OR_FILE... [-j N] [--out DIR] [--show]

Each `.py` file is one program. It must be deterministic, print its results,
read no input and no files, and finish in a few seconds.

Verdicts, one per program:

    OK        same stdout and same exit code as CPython
    WRONG     the compiled program ran to its end and printed something else.
              This is the worst class: nothing told the user.
    CRASH     the compiled program died (signal, or a different exit code)
    GCC       the compiler produced C that gcc rejected
    REFUSED   the compiler said "cannot compile ..." (an honest refusal)
    ERROR     the compiler itself raised some other exception
    TIMEOUT   compile or run took too long
    PYFAIL    CPython itself failed: the program is not a valid test

`--out DIR` writes, for each program that is not OK, `NAME.txt` with both
outputs and the compiler's message. `--show` prints them. The exit code is 0
when no program is WRONG, CRASH, GCC, ERROR or TIMEOUT.

This is a finder, not a gate: it is not registered in tools/suite.py. A
program it finds becomes a bug doc in bugs/ and, once fixed, a case in
test_gimple_runner.py.
"""
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_TIMEOUT_S = 20
COMPILE_TIMEOUT_S = 300
BAD = ('WRONG', 'CRASH', 'GCC', 'ERROR', 'TIMEOUT')


def one(path: str) -> dict:
    """Compile and run one program in THIS process's child; return its verdict."""
    src = open(path).read()
    py = subprocess.run([sys.executable, path], capture_output=True, text=True,
                        timeout=RUN_TIMEOUT_S, cwd=tempfile.gettempdir())
    if py.returncode != 0:
        return {'verdict': 'PYFAIL', 'detail': py.stderr[-600:]}
    sys.path.insert(0, HERE)
    import test_gimple_runner as R
    try:
        exe = R.compile_mojo_to_gimple_exe(src, filename=path)
    except RuntimeError as e:
        msg = str(e)
        if 'gcc -fgimple compilation failed' in msg:
            errs = [l for l in msg.splitlines() if 'error' in l]
            return {'verdict': 'GCC', 'detail': '\n'.join(errs[:6]) or msg[-600:]}
        if 'cannot compile' in msg:
            return {'verdict': 'REFUSED', 'detail': msg[:600]}
        return {'verdict': 'ERROR', 'detail': 'RuntimeError: ' + msg[:600]}
    except SyntaxError as e:
        return {'verdict': 'REFUSED', 'detail': 'SyntaxError: ' + str(e)[:600]}
    except Exception as e:
        return {'verdict': 'ERROR', 'detail': type(e).__name__ + ': ' + str(e)[:600]}
    try:
        got = subprocess.run([exe], capture_output=True, text=True,
                             timeout=RUN_TIMEOUT_S, errors='replace')
    except subprocess.TimeoutExpired:
        return {'verdict': 'TIMEOUT', 'detail': 'the compiled program did not finish'}
    finally:
        try:
            os.unlink(exe)
        except OSError:
            pass
    if got.returncode != py.returncode:
        return {'verdict': 'CRASH', 'want': py.stdout, 'got': got.stdout,
                'detail': 'exit %d, CPython exit %d\n%s' % (
                    got.returncode, py.returncode, got.stderr[-400:])}
    if got.stdout != py.stdout:
        return {'verdict': 'WRONG', 'want': py.stdout, 'got': got.stdout, 'detail': ''}
    return {'verdict': 'OK'}


def run_child(path: str) -> dict:
    """Run `one(path)` in a separate interpreter, so one program's crash or
    leftover compiler state cannot touch the next."""
    try:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), '--one', path],
                           capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S,
                           cwd=HERE)
    except subprocess.TimeoutExpired:
        return {'verdict': 'TIMEOUT', 'detail': 'compile did not finish'}
    for line in reversed(r.stdout.splitlines()):
        if line.startswith('PYDIFF '):
            return json.loads(line[7:])
    return {'verdict': 'ERROR', 'detail': 'the compiler process died (exit %d)\n%s' % (
        r.returncode, r.stderr[-600:])}


def first_difference(want: str, got: str) -> str:
    w, g = want.splitlines(), got.splitlines()
    for i in range(max(len(w), len(g))):
        a = w[i] if i < len(w) else '<no line>'
        b = g[i] if i < len(g) else '<no line>'
        if a != b:
            return 'line %d\n  CPython : %s\n  compiled: %s' % (i + 1, a[:200], b[:200])
    return 'the outputs differ only in trailing whitespace'


def report(name: str, res: dict) -> str:
    out = ['%s  %s' % (res['verdict'], name)]
    if 'want' in res:
        out.append(first_difference(res['want'], res['got']))
    if res.get('detail'):
        out.append(res['detail'].rstrip())
    return '\n'.join(out)


def main(argv: list) -> int:
    if len(argv) == 2 and argv[0] == '--one':
        try:
            res = one(argv[1])
        except subprocess.TimeoutExpired:
            res = {'verdict': 'TIMEOUT', 'detail': 'CPython or gcc did not finish'}
        print('PYDIFF ' + json.dumps(res))
        return 0
    jobs, out_dir, show, paths = 8, None, False, []
    i = 0
    while i < len(argv):
        if argv[i] == '-j':
            jobs = int(argv[i + 1]); i += 2
        elif argv[i] == '--out':
            out_dir = argv[i + 1]; i += 2
        elif argv[i] == '--show':
            show = True; i += 1
        else:
            paths.append(argv[i]); i += 1
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, names in os.walk(p):
                files += [os.path.join(root, n) for n in sorted(names) if n.endswith('.py')]
        else:
            files.append(p)
    files = [os.path.abspath(f) for f in files]
    if not files:
        raise SystemExit(__doc__)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        results = list(ex.map(run_child, files))
    tally = {}
    for f, res in zip(files, results):
        v = res['verdict']
        tally[v] = tally.get(v, 0) + 1
        if v == 'OK':
            continue
        name = os.path.relpath(f)
        text = report(name, res)
        if show:
            print(text + '\n')
        else:
            print('%-8s %s' % (v, name))
        if out_dir:
            with open(os.path.join(out_dir, os.path.basename(f)[:-3] + '.txt'), 'w') as fh:
                fh.write(text + '\n')
                if 'want' in res:
                    fh.write('\n--- CPython stdout ---\n' + res['want'])
                    fh.write('\n--- compiled stdout ---\n' + res['got'])
    print('%d programs: %s' % (len(files), ', '.join(
        '%s %d' % (k, tally[k]) for k in sorted(tally))))
    return 1 if any(tally.get(k) for k in BAD) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
