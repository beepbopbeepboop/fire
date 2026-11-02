#!/usr/bin/env python3
"""Quick regression for bytes-pattern re.compile / fnmatch."""
import os, shutil, subprocess, sys, sysconfig, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = r'''
import fnmatch, os, re

ROOT = "@ROOT@"

def names(d):
    # a generator, as glob's _iterdir is: the coroutine path is the one that lowers
    # os.scandir, and the bytes-vs-str choice is made at run time from the argument
    with os.scandir(d) as it:
        for entry in it:
            yield entry.name

print(fnmatch.translate("*.py"))
print(fnmatch.fnmatch(b"a.py", b"*.py"), fnmatch.fnmatch(b"a.txt", b"*.py"))
print(re.compile(".*").search("abc").span())
print(re.compile(b".*").search(b"abc").span())
print(re.compile(b".*").match(b"abc").span())
print(re.compile(b".*").fullmatch(b"abc").span())
print(re.compile(b"a").match(b"a") is not None, re.compile(b"a").match(b"b") is not None)
print(re.compile(b"(?s:.*\\.py)\\z").match(b"a.py") is not None)
print(sorted(names(ROOT)))
print(sorted(names(ROOT.encode())))
'''

def main():
    prog = tempfile.mkdtemp(prefix='re_reg_')
    tree = os.path.join(prog, 'tree')
    os.makedirs(tree)
    for name in ('a.py', 'b.txt'):
        open(os.path.join(tree, name), 'w').close()
    # fnmatch is compiled from its CPython source, as a sibling of the driver
    # (test_glob_compiled.py does the same): a module the binary does not
    # compile is a stub that raises at run time
    lib = sysconfig.get_paths()['stdlib']
    shutil.copy(os.path.join(lib, 'fnmatch.py'), prog)
    drv_path = os.path.join(prog, 'drv.py')
    with open(drv_path, 'w') as f:
        f.write(DRIVER.replace('@ROOT@', tree))
    cpy = subprocess.run([sys.executable, drv_path], capture_output=True, text=True)
    if cpy.returncode != 0:
        print('FAIL the driver does not run under CPython (the expected output is not valid)\n' + cpy.stderr[-1500:])
        return 1
    want = cpy.stdout
    exe = os.path.join(prog, 'drv')
    b = subprocess.run([sys.executable, os.path.join(HERE, 'fire.py'), 'build', drv_path, '-o', exe], capture_output=True, text=True)
    if not os.path.exists(exe):
        print('FAIL build missing\n', (b.stdout+b.stderr)[-1500:])
        return 1
    run = subprocess.run([exe], capture_output=True)
    got = run.stdout.decode('utf-8', 'replace')
    if run.returncode != 0:
        print('FAIL the compiled driver exits %d\n%s' % (run.returncode, run.stderr.decode('utf-8', 'replace')[-800:]))
        return 1
    if got != want:
        print('FAIL compiled re bytes differs from CPython')
        print('--- CPython ---')
        print(want)
        print('--- compiled ---')
        print(got)
        return 1
    print('PASS compiled re bytes matches CPython')
    return 0
if __name__ == '__main__':
    sys.exit(main())
