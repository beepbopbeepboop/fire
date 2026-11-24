#!/usr/bin/env python3
"""The byte-identical oracle for behaviour-preserving backend changes (doc/GIR.md §5).

    python3 tools/c_oracle.py base  [--commit SHA] [--closure] [-j N]
    python3 tools/c_oracle.py check [--base SHA]   [--closure] [-j N] [--show N]

`base` hashes the C that the gimple backend generates for every program in
tools/pydiff_corpus, at commit SHA (default HEAD), in a scratch git worktree, and
caches the result in build/c_oracle/<sha>-<corpus>.json. A cached base is reused,
so a wave of workers pays for it once.

`check` hashes the WORKING TREE the same way and compares with the base (computed
first if it is not cached). Exit 0 when every program's C is identical; otherwise it
lists the programs whose C differs and exits 1.

TWO CORPORA, because the C++ coroutine printer is only reachable through the
second one. `tools/pydiff_corpus` holds no coroutine program and is compiled with
the DEFAULT coroutine backend (`mojo.middle.coro.enabled()` selects the A3
stack-switch lowering unless `MOJO_CORO=cpp`), so its companion `.cpp` text is
'' for every one of its 285 programs: hashing `c + '\0' + cpp` there can never see
a change in `mojo/backend_gimple/cpp_core.py` or `cpp_async.py` (measured
2026-11-21: 285 programs, 0 with a non-empty companion). `tools/cpp_corpus`
therefore holds coroutine programs only, is compiled in a child with
`MOJO_CORO=cpp`, and counts an EMPTY companion as an error rather than as a
hashable no-op -- so the corpus cannot silently stop exercising the C++ lowering.
Both corpora are hashed and compared by both `base` and `check`.

`--closure` adds the self-host check: `fire.py --dump-full fire.py`, the same
whole-closure dump `bootstrap-stage1-transitive` makes, and counts the weak
"unavailable in compiled mode" stub DEFINITIONS in it. `check --closure` fails when
a stub name appears that the base does not have. This is the only cheap check that
sees a call the self-hosted compiler cannot resolve (2026-11-21: every WordFacts
method was stubbed while the corpus hashes and a per-module `--dump` were clean). It
takes 5-8 minutes and about 6 GB, so the orchestrator runs it once per wave, not each
worker. It is reserved through tools/memslot.py.

Both sides compile the SAME corpus text (read from this checkout), with an empty
GMOJO_HOME, so the codegen cache cannot hide a difference.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(HERE, 'build', 'c_oracle')
CORPUS = 'tools/pydiff_corpus'
# The C++ coroutine printer's corpus (see the module docstring): compiled with
# MOJO_CORO=cpp, where every program MUST produce a companion .cpp.
CPP_CORPUS = 'tools/cpp_corpus'
STUB = re.compile(r'\{ mojo_print \(\(char \*\)"([^"]*): unavailable in compiled mode')
# The whole-closure dump peaks above 8 GB (measured 2026-11-22: the base dump was
# killed by memcap at the old 8 GB ceiling, a RESOURCE failure that the check then
# recorded as a stub list). 20 GB leaves room; the memslot reservation is the same class.
CLOSURE_GB = 20

# Run in a child, with cwd and sys.path set to the tree being measured.
CHILD = r'''
import hashlib, json, sys
sys.path.insert(0, '.')
from gimple_codegen import compile_to_gimple_with_cpp
for line in sys.stdin:
    rel, path = line.rstrip('\n').split('\t')
    try:
        c, cpp = compile_to_gimple_with_cpp(open(path).read(), filename=rel)
        h = hashlib.md5((c + '\0' + cpp).encode()).hexdigest()
    except BaseException as e:
        h = 'ERR ' + type(e).__name__
    print(json.dumps([rel, h]), flush=True)
'''

# The cpp-corpus child: `MOJO_CORO=cpp` is set in the ENV by `hash_tree`, so the
# backend is chosen before `gimple_codegen` is imported (`coro.enabled()` reads
# the variable at each compile, but importing the tree with the default already
# bound would be a second, avoidable way to get this wrong). An empty companion
# is an ERROR, not a hash: a program that stops driving the C++ lowering must
# fail the oracle loudly instead of contributing an unchangeable hash.
CPP_CHILD = r'''
import hashlib, json, sys
sys.path.insert(0, '.')
from gimple_codegen import compile_to_gimple_with_cpp
for line in sys.stdin:
    rel, path = line.rstrip('\n').split('\t')
    try:
        c, cpp = compile_to_gimple_with_cpp(open(path).read(), filename=rel)
        if not cpp.strip():
            h = 'ERR empty companion .cpp: this program no longer drives the C++ lowering'
        else:
            h = hashlib.md5((c + '\0' + cpp).encode()).hexdigest()
    except BaseException as e:
        h = 'ERR ' + type(e).__name__ + ': ' + str(e)[:160].replace('\n', ' ')
    print(json.dumps([rel, h]), flush=True)
'''


def git(*args, cwd=HERE) -> str:
    return subprocess.run(['git'] + list(args), cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def corpus(rel_dir: str = CORPUS) -> list:
    # Programs are Mojo source; `.py` is the older name for the Python-compatible
    # ones, and a Mojo-only program (a `struct`) has to be `.mojo` or the Python
    # scanners (`test_refusal_taxonomy.py`) read it as a Python file. The child
    # compiles the text either way, so the extension only has to be globbed.
    files = sorted(glob.glob(os.path.join(HERE, rel_dir, '*', '*.py'))
                   + glob.glob(os.path.join(HERE, rel_dir, '*', '*.mojo')))
    return [(os.path.relpath(f, HERE), f) for f in files]


def corpus_key(files: list, cpp_files: list) -> str:
    h = hashlib.md5()
    for rel, path in files + cpp_files:
        h.update(rel.encode() + b'\0' + open(path, 'rb').read() + b'\0')
    return h.hexdigest()[:10]


def hash_tree(tree: str, files: list, jobs: int, cpp: bool = False) -> dict:
    """{relpath: md5 of the generated C (+ the companion C++)} for `tree`.

    `cpp` selects the C++ coroutine corpus: the child runs with MOJO_CORO=cpp
    and refuses an empty companion (see CPP_CHILD)."""
    chunks = [files[i::jobs] for i in range(jobs)]
    procs = []
    for chunk in chunks:
        if not chunk:
            continue
        env = dict(os.environ, GMOJO_HOME=tempfile.mkdtemp(prefix='c_oracle_home_'),
                   PYTHONPATH=tree)
        if cpp:
            env['MOJO_CORO'] = 'cpp'
        p = subprocess.Popen([sys.executable, '-c', CPP_CHILD if cpp else CHILD],
                             cwd=tree, env=env,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True)
        p.stdin.write(''.join('%s\t%s\n' % (rel, path) for rel, path in chunk))
        p.stdin.close()
        procs.append(p)
    out = {}
    for p in procs:
        for line in p.stdout:
            rel, h = json.loads(line)
            out[rel] = h
        p.wait()
    missing = [rel for rel, _ in files if rel not in out]
    for rel in missing:
        out[rel] = 'ERR no result (the child died)'
    return out


def closure_stubs(tree: str) -> list:
    """Sorted names of the weak stubs in `tree`'s whole-closure dump."""
    tmp = tempfile.mkdtemp(prefix='c_oracle_closure_')
    env = dict(os.environ, GMOJO_HOME=tempfile.mkdtemp(prefix='c_oracle_home_'),
               PYTHONPATH=tree)
    cmd = [sys.executable, os.path.join(HERE, 'tools', 'memslot.py'), '--gb', str(CLOSURE_GB),
           '--label', 'c_oracle-closure', '--',
           sys.executable, os.path.join(tree, 'fire.py'), '--dump-full', os.path.join(tree, 'fire.py')]
    log = os.path.join(tmp, 'dump.log')
    with open(log, 'w') as lf:
        rc = subprocess.run(cmd, cwd=tmp, env=env, stdout=lf, stderr=subprocess.STDOUT).returncode
    ci = os.path.join(tmp, 'fire.ci')
    if not os.path.exists(ci):
        # Raise, never return a sentinel: a sentinel is cached as the base's
        # stub list, and every later check then reports the whole closure as
        # NEW stubs (measured 2026-11-22: the base dump failed silently and the
        # real stub set, which the tree shares, was reported as a regression).
        tail = open(log, errors='replace').read()[-800:]
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError('closure dump of %s produced no fire.ci (exit %s); tail:\n%s'
                           % (tree, rc, tail))
    names = sorted(set(STUB.findall(open(ci, errors='replace').read())))
    shutil.rmtree(tmp, ignore_errors=True)
    return names


def base_path(sha: str, ckey: str) -> str:
    return os.path.join(CACHE, '%s-%s.json' % (sha[:12], ckey))


def compute_base(sha: str, files: list, cpp_files: list, jobs: int, closure: bool) -> dict:
    os.makedirs(CACHE, exist_ok=True)
    path = base_path(sha, corpus_key(files, cpp_files))
    data = json.load(open(path)) if os.path.exists(path) else {}
    if 'hashes' in data and 'cpp' in data and (not closure or 'stubs' in data):
        return data
    wt = os.path.join(tempfile.gettempdir(), 'c_oracle_wt_' + sha[:12])
    if os.path.exists(wt):
        subprocess.run(['git', 'worktree', 'remove', '--force', wt], cwd=HERE,
                       capture_output=True)
    git('worktree', 'add', '-q', '--detach', wt, sha)
    try:
        if 'hashes' not in data:
            print('c_oracle: hashing %d programs at %s ...' % (len(files), sha[:12]), flush=True)
            data['hashes'] = hash_tree(wt, files, jobs)
        if 'cpp' not in data:
            print('c_oracle: hashing %d coroutine programs (C++ lowering) at %s ...'
                  % (len(cpp_files), sha[:12]), flush=True)
            data['cpp'] = hash_tree(wt, cpp_files, jobs, cpp=True)
        if closure and 'stubs' not in data:
            print('c_oracle: closure dump at %s (5-8 min) ...' % sha[:12], flush=True)
            data['stubs'] = closure_stubs(wt)
    finally:
        subprocess.run(['git', 'worktree', 'remove', '--force', wt], cwd=HERE, capture_output=True)
    data['commit'] = sha
    json.dump(data, open(path, 'w'), indent=1, sort_keys=True)
    return data


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('mode', choices=['base', 'check'])
    ap.add_argument('--commit', '--base', dest='commit', default='HEAD')
    ap.add_argument('--closure', action='store_true')
    ap.add_argument('-j', type=int, default=4)
    ap.add_argument('--show', type=int, default=20)
    a = ap.parse_args(argv)
    sha = git('rev-parse', a.commit)
    files = corpus()
    cpp_files = corpus(CPP_CORPUS)
    if not cpp_files:
        print('c_oracle: %s holds no programs: the C++ coroutine lowering '
              'would be unhashable (see the module docstring)' % CPP_CORPUS)
        return 1
    base = compute_base(sha, files, cpp_files, a.j, a.closure)
    if a.mode == 'base':
        print('c_oracle: base %s cached (%d programs, %d coroutine%s)' % (
            sha[:12], len(base['hashes']), len(base['cpp']),
            ', %d closure stubs' % len(base['stubs']) if 'stubs' in base else ''))
        return 0
    print('c_oracle: hashing %d programs in the working tree ...' % len(files), flush=True)
    now = hash_tree(HERE, files, a.j)
    diff = [rel for rel, _ in files if now.get(rel) != base['hashes'].get(rel)]
    rc = 0
    if diff:
        rc = 1
        print('c_oracle: %d of %d programs generate DIFFERENT C than %s:' % (
            len(diff), len(files), sha[:12]))
        for rel in diff[:a.show]:
            print('  %s  (base %s, now %s)' % (rel, base['hashes'].get(rel), now.get(rel)))
        if len(diff) > a.show:
            print('  ... and %d more' % (len(diff) - a.show))
    else:
        print('c_oracle: all %d programs generate identical C to %s' % (len(files), sha[:12]))
    print('c_oracle: hashing %d coroutine programs (C++ lowering) in the working tree ...'
          % len(cpp_files), flush=True)
    now_cpp = hash_tree(HERE, cpp_files, a.j, cpp=True)
    # A refused or empty companion in the WORKING TREE is a failure whatever the
    # base says: base and work can agree on "ERR ..." only by both having stopped
    # exercising the lowering, which is exactly the state this corpus exists to
    # make impossible (the 285-program corpus compared equal that way for months).
    cpp_bad = [rel for rel, _ in cpp_files if str(now_cpp.get(rel, '')).startswith('ERR')]
    cpp_diff = [rel for rel, _ in cpp_files
                if rel not in cpp_bad and now_cpp.get(rel) != base['cpp'].get(rel)]
    if cpp_bad:
        rc = 1
        print('c_oracle: %d of %d coroutine programs produce NO C++ companion '
              '(the C++ lowering is not exercised):' % (len(cpp_bad), len(cpp_files)))
        for rel in cpp_bad[:a.show]:
            print('  %s  (%s)' % (rel, now_cpp.get(rel)))
        if len(cpp_bad) > a.show:
            print('  ... and %d more' % (len(cpp_bad) - a.show))
    if cpp_diff:
        rc = 1
        print('c_oracle: %d of %d coroutine programs generate DIFFERENT C++ than %s:' % (
            len(cpp_diff), len(cpp_files), sha[:12]))
        for rel in cpp_diff[:a.show]:
            print('  %s  (base %s, now %s)' % (rel, base['cpp'].get(rel), now_cpp.get(rel)))
        if len(cpp_diff) > a.show:
            print('  ... and %d more' % (len(cpp_diff) - a.show))
    if not cpp_bad and not cpp_diff:
        print('c_oracle: all %d coroutine programs generate identical C++ companion to %s'
              % (len(cpp_files), sha[:12]))
    if a.closure:
        stubs = closure_stubs(HERE)
        new = sorted(set(stubs) - set(base.get('stubs', [])))
        if new:
            rc = 1
            print('c_oracle: the closure dump has %d NEW stub(s) (self-host cannot resolve them):' % len(new))
            for n in new:
                print('  ' + n)
        else:
            print('c_oracle: closure dump: no new stubs (%d, base %d)' % (
                len(stubs), len(base.get('stubs', []))))
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
