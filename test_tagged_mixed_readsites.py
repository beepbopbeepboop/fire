#!/usr/bin/env python3
"""Read-site regressions for a name bound to a tagged generator word AND to a
value of another C type (the box of step 2 of docs/tagged_generator_mixed_type-plan.md).

Each case is a Mojo program whose loop variable is stored into a mixed name and
then read by an operation the step 2 parts did not cover. The program is built
through the real CLI (`fire.py build`, the path users run, which links the
generator runtime itself) and its stdout must equal CPython's on the same text.

Usage:  python3 test_tagged_mixed_readsites.py <case>   (one case)
        python3 test_tagged_mixed_readsites.py          (every case)

Exit 0 when every selected case matches CPython, 1 otherwise.
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(ROOT, 'fire.py')
TIMEOUT_S = 600

# Case name -> (doc that owns it, program). The doc is the part that must make
# the case pass; the program is the same text for Mojo and CPython.
CASES = {
    # Part 1: the builtin casts int() and float() on a double box. int(x) printed
    # the raw double; float(x) + 1.0 read the box pointer's bits as a double.
    'double_box_casts': (
        'bugs/mid/CODEGEN_tagged_generator_mixed_type_step2-part1.md',
        """\
def g():
    yield 1
    yield 2.5
    yield 3
def main():
    x = 0.5
    for v in g():
        x = v
        print(int(x))
        print(float(x) + 1.0)
main()
""",
    ),
    # Part 2: binary operators whose operands are a str box. x * 2 printed a
    # pointer-sized integer; x + x (box + box) did the same.
    'str_box_binops': (
        'bugs/mid/CODEGEN_tagged_generator_mixed_type_step2-part2.md',
        """\
def g():
    yield 1
    yield "a"
    yield 3
def main():
    x = 0
    for v in g():
        x = v
        print(x * 2)
        print(x + x)
main()
""",
    ),
}


def _cpython_stdout(src: str, wd: str) -> str:
    p = os.path.join(wd, 'ref.py')
    with open(p, 'w') as f:
        f.write(src)
    r = subprocess.run([sys.executable, p], capture_output=True, text=True,
                       timeout=TIMEOUT_S)
    if r.returncode != 0:
        raise RuntimeError(f"the CPython reference program failed: {r.stderr}")
    return r.stdout


def _compiled_stdout(src: str, wd: str) -> str:
    # fire.py must run as a script from ROOT (it imports build_config from its
    # own directory), so the source and exe live in the scratch dir and only
    # the fire.py path is absolute.
    mojo = os.path.join(wd, 'prog.mojo')
    exe = os.path.join(wd, 'prog.exe')
    with open(mojo, 'w') as f:
        f.write(src)
    b = subprocess.run([sys.executable, FIRE, 'build', mojo, '-o', exe],
                       capture_output=True, text=True, timeout=TIMEOUT_S, cwd=wd)
    if b.returncode != 0:
        raise RuntimeError(f"fire.py build failed:\n{b.stdout}{b.stderr}")
    r = subprocess.run([exe], capture_output=True, text=True, timeout=TIMEOUT_S)
    return r.stdout


def run_case(name: str) -> bool:
    doc, src = CASES[name]
    wd = tempfile.mkdtemp(prefix=f'readsite_{name}_')
    try:
        want = _cpython_stdout(src, wd)
        got = _compiled_stdout(src, wd)
    except Exception as e:
        print(f"FAIL  {name} ({doc}): {e}")
        return False
    if got == want:
        print(f"PASS  {name}")
        return True
    print(f"FAIL  {name} ({doc}): CPython {want!r}, compiled {got!r}")
    return False


def main(argv):
    names = argv[1:] or list(CASES)
    unknown = [n for n in names if n not in CASES]
    if unknown:
        print(f"unknown case(s): {', '.join(unknown)}; known: {', '.join(CASES)}")
        return 2
    results = [run_case(n) for n in names]
    print(f"\n{sum(results)} passed, {len(results) - sum(results)} failed")
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
