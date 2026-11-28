#!/usr/bin/env python3
"""Build the self-hosted compiler once and compare its output with the reference's.

`test_selfhost.py` builds the binary into a temp dir and deletes it, so a failing
check says only "exit=1". This keeps the binary, then runs it on small probes and
diffs each `.ci` against `python3 fire.py --dump-full` of the same file, which is
how every startup crash and every wrong-output defect of the self-hosted compiler
was found (doc/GIR.md, "Selfhost closure"). Typical use:

    python3 tools/memcap.py --limit-gb 30 -- python3 tools/selfhost_probe.py build <dir>
    python3 tools/memcap.py --limit-gb 24 -- python3 tools/selfhost_probe.py probe <dir> prog1.mojo
    python3 tools/memcap.py --limit-gb 24 -- python3 tools/selfhost_probe.py probe <dir> corpus pydiff:40
    # a crash: ASLR matters, lldb must run with it ON
    lldb -b -o 'settings set target.disable-aslr false' \
         -o 'run --dump-full prog.mojo' -o 'bt 12' /tmp/shb/mojo_selfhost
    # an AttributeError: break where it is raised
    lldb ... -o 'breakpoint set -n mojo_raise_attribute_error' ...

`SELFHOST_PROBE_DEBUG=1` on `build` adds -g1 so `bt` in lldb shows `file.py:line`.
`build` takes about 15 minutes and 10 GB; `probe` takes seconds per file. ALWAYS run under tools/memcap.py
(above), and ONE build or probe at a time: a reboot on 2026-11-27 followed several builds and a
probe run going at once.

On top of memcap, every run of the built binary is bounded here too: a wall-clock limit and a
resident-set limit, and a child that passes either is stopped with a plain SIGTERM (this tool's own
child) and reported as TIMEOUT / RSS-LIMIT. memcap is the machine-wide guard; this one just makes
the verdict say which run was the runaway.

Program sets: `corpus` is tools/selfhost_programs/*.mojo (small programs, one defect class each);
`pydiff:N` is the first N programs of tools/pydiff_ok.txt.
"""
import difflib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def build(out_dir: str) -> int:
    sys.path.insert(0, ROOT)
    import tempfile
    import test_selfhost as T
    if os.environ.get('SELFHOST_PROBE_DEBUG'):
        # `-g1`: lldb then maps a crash frame to the compiler's own .py line (the
        # `#line` directives), which names the `for`/call a bare address cannot.
        import functools
        sys.path.insert(0, ROOT)
        import fire
        fire.build_executable = functools.partial(
            fire.build_executable, debug_flag='-g1', opt_flag='-O1')
        # macOS keeps DWARF in the .o files, which `build_executable` deletes after
        # linking; `dsymutil` right after the link folds it into `<exe>.dSYM`.
        _real_run = fire.subprocess.run

        def _run_with_dsym(cmd, *a, **k):
            r = _real_run(cmd, *a, **k)
            if (isinstance(cmd, list) and '-o' in cmd and r.returncode == 0
                    and os.path.basename(cmd[cmd.index('-o') + 1]) == 'mojo_selfhost'):
                _real_run(['dsymutil', cmd[cmd.index('-o') + 1]], capture_output=True)
            return r
        fire.subprocess.run = _run_with_dsym
    os.makedirs(out_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        cwd = os.getcwd()
        os.chdir(td)
        try:
            exe = T.build(td)
            if not exe:
                print('build failed')
                return 1
            shutil.copy(exe, os.path.join(out_dir, 'mojo_selfhost'))
            if os.path.isdir(exe + '.dSYM'):
                dst = os.path.join(out_dir, 'mojo_selfhost.dSYM')
                shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(exe + '.dSYM', dst)
        finally:
            os.chdir(cwd)
    print('built', os.path.join(out_dir, 'mojo_selfhost'))
    return 0


MAX_SECONDS = 120
MAX_RSS_GB = 12


def _rss_gb(pid: int) -> float:
    r = subprocess.run(['ps', '-o', 'rss=', '-p', str(pid)], capture_output=True, text=True)
    try:
        return int(r.stdout.strip()) / (1024.0 * 1024.0)
    except ValueError:
        return 0.0


def run_bounded(cmd: list, cwd: str) -> tuple:
    """`(returncode, stderr, note)` for one run of `cmd`, stopped with SIGTERM if it passes
    MAX_SECONDS of wall clock or MAX_RSS_GB of resident memory (polled every 0.1 s). Output goes
    to files, not pipes, so a chatty child cannot block on a full pipe while it is being watched."""
    import tempfile
    import time
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        p = subprocess.Popen(cmd, cwd=cwd, stdout=out, stderr=err)
        start = time.time()
        note = ''
        while p.poll() is None:
            if time.time() - start > MAX_SECONDS:
                note = 'TIMEOUT'
            elif _rss_gb(p.pid) > MAX_RSS_GB:
                note = 'RSS-LIMIT'
            if note:
                p.terminate()
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                break
            time.sleep(0.1)
        err.seek(0)
        return p.returncode if p.returncode is not None else -1, err.read().decode('utf8', 'replace'), note


def expand(files: list) -> list:
    """`corpus` and `pydiff:N` stand for the durable program sets (see the module docstring)."""
    out: list = []
    for f in files:
        if f == 'corpus':
            d = os.path.join(HERE, 'selfhost_programs')
            out += [os.path.join(d, n) for n in sorted(os.listdir(d)) if n.endswith('.mojo')]
        elif f.startswith('pydiff:'):
            names = [ln.strip() for ln in open(os.path.join(HERE, 'pydiff_ok.txt'))
                     if ln.strip() and not ln.startswith('#')]
            import tempfile
            stage = tempfile.mkdtemp(prefix='pydiff_probe_')
            for n in names[:int(f.split(':')[1])]:
                dst = os.path.join(stage, n.replace('/', '_')[:-3] + '.mojo')
                shutil.copy(os.path.join(HERE, 'pydiff_corpus', n), dst)
                out.append(dst)
        else:
            out.append(f)
    return out


def probe(out_dir: str, files: list) -> int:
    files = expand(files)
    exe = os.path.join(out_dir, 'mojo_selfhost')
    work = os.path.join(out_dir, 'probe')
    os.makedirs(work, exist_ok=True)
    bad = 0
    for f in files:
        name = os.path.splitext(os.path.basename(f))[0]
        src = os.path.join(work, name + '.mojo')
        shutil.copy(f, src)
        subprocess.run([sys.executable, os.path.join(ROOT, 'fire.py'), '--dump-full', src],
                       cwd=work, capture_output=True, text=True)
        ref_path = os.path.join(work, name + '.ci')
        ref = open(ref_path, encoding='utf8', errors='replace').read() if os.path.exists(ref_path) else ''
        if os.path.exists(ref_path):
            os.replace(ref_path, os.path.join(work, name + '.ref'))
        rc, stderr, note = run_bounded([exe, '--dump-full', src], work)
        got_b = open(ref_path, 'rb').read() if os.path.exists(ref_path) else b''
        try:
            got_b.decode()
            utf8 = 'utf8-ok'
        except UnicodeDecodeError:
            utf8 = 'BAD-UTF8'
        got = got_b.decode('utf8', errors='replace')
        diff = list(difflib.unified_diff(ref.split('\n'), got.split('\n'), 'ref', 'self',
                                         lineterm='', n=0))
        verdict = 'identical' if not diff and rc == 0 else 'DIFFERENT'
        if verdict != 'identical' or utf8 != 'utf8-ok':
            bad += 1
        print('%-28s rc=%-4d %s %s (%d diff lines)%s' % (name, rc, utf8, verdict, len(diff),
                                                   ' ' + note if note else ''))
        if diff and '-v' in sys.argv:
            print('\n'.join(diff[:60]))
        if rc != 0:
            print('   stderr:', stderr.strip()[:200])
    return 1 if bad else 0


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == 'build':
        return build(sys.argv[2])
    if len(sys.argv) >= 4 and sys.argv[1] == 'probe':
        return probe(sys.argv[2], [a for a in sys.argv[3:] if a != '-v'])
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
