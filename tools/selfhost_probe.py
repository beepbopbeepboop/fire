#!/usr/bin/env python3
"""Build the self-hosted compiler once and compare its output with the reference's.

`test_selfhost.py` builds the binary into a temp dir and deletes it, so a failing
check says only "exit=1". This keeps the binary, then runs it on small probes and
diffs each `.ci` against `python3 fire.py --dump-full` of the same file, which is
how every startup crash and every wrong-output defect of the self-hosted compiler
was found (doc/GIR.md, "Selfhost closure"). Typical use:

    python3 tools/memcap.py --limit-gb 24 -- python3 tools/selfhost_probe.py build /tmp/shb
    python3 tools/selfhost_probe.py probe /tmp/shb prog1.mojo prog2.mojo
    # a crash: ASLR matters, lldb must run with it ON
    lldb -b -o 'settings set target.disable-aslr false' \
         -o 'run --dump-full prog.mojo' -o 'bt 12' /tmp/shb/mojo_selfhost
    # an AttributeError: break where it is raised
    lldb ... -o 'breakpoint set -n mojo_raise_attribute_error' ...

`build` takes about 15 minutes and 10 GB; `probe` takes seconds per file.
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
        finally:
            os.chdir(cwd)
    print('built', os.path.join(out_dir, 'mojo_selfhost'))
    return 0


def probe(out_dir: str, files: list) -> int:
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
        r = subprocess.run([exe, '--dump-full', src], cwd=work, capture_output=True, text=True)
        got_b = open(ref_path, 'rb').read() if os.path.exists(ref_path) else b''
        try:
            got_b.decode()
            utf8 = 'utf8-ok'
        except UnicodeDecodeError:
            utf8 = 'BAD-UTF8'
        got = got_b.decode('utf8', errors='replace')
        diff = list(difflib.unified_diff(ref.split('\n'), got.split('\n'), 'ref', 'self',
                                         lineterm='', n=0))
        verdict = 'identical' if not diff and r.returncode == 0 else 'DIFFERENT'
        if verdict != 'identical' or utf8 != 'utf8-ok':
            bad += 1
        print('%-28s rc=%-4d %s %s (%d diff lines)' % (name, r.returncode, utf8, verdict, len(diff)))
        if diff and '-v' in sys.argv:
            print('\n'.join(diff[:60]))
        if r.returncode != 0:
            print('   stderr:', r.stderr.strip()[:200])
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
