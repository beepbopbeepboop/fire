#!/usr/bin/env python3
"""Regression: a FUNCTION-SCOPED aliased import (`from R import f as g`
inside a function body) of a str-returning function, where R re-exports f
from a sibling, must declare the extern under the SAME C name every call
site uses.

Symptom this pins: the import-extern preamble declared `extern char * nq (...)`
(the local alias) guarded and called under the mangled symbol. Two causes:
the function-scoped pre-pass rewrote the defining signature's name to the
alias, so the preamble's original-name -> C-symbol rename was a no-op; and the
preamble re-resolved the mangled name after the function scope had been
popped, dropping the module qualifier. gcc then reports `implicit declaration`
and `int` -> `char *` conversions.

Run:  python3 test_gimple_function_scoped_alias_extern.py
"""
import os
import re
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import build_config  # noqa: E402
import gimple_codegen  # noqa: E402

RUNTIME_INC = os.path.join(_HERE, 'runtime')

FILES = {
    # Re-export layout: the function is defined in p/sub.py and reached
    # through the package, so the alias binding goes through a re-export.
    'p/__init__.py': 'from .sub import name_of\n',
    'p/sub.py': (
        'def name_of(x: Int64) -> String:\n'
        '    return "n" + String(x)\n'
    ),
    'p/main.py': (
        'def build() -> String:\n'
        '    from p import name_of as nq\n'
        '    return nq(3)\n'
        '\n'
        'def main():\n'
        '    print(build())\n'
        '\n'
        'main()\n'
    ),
}


def _compile_single_tu(entry_src, entry_path):
    return gimple_codegen._run_pipeline(
        entry_src, filename=entry_path, do_imports=True)[0]


def main():
    failures = []
    with tempfile.TemporaryDirectory() as td:
        for rel, body in FILES.items():
            fp = os.path.join(td, rel)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, 'w') as fh:
                fh.write(body)
        entry = os.path.join(td, 'p', 'main.py')
        c_src = _compile_single_tu(FILES['p/main.py'], entry)

        # The call site inside build(): the name the call is emitted under.
        m = re.search(r'char \* build \(void\)\n\{.*?_t1 = (\w+) \(', c_src,
                      re.S)
        if not m:
            failures.append('could not find the call to nq inside build()')
        else:
            callee = m.group(1)
            # 1. The ALIAS must never be declared as a C function: the
            #    extern has to be named the way the call site names it.
            if re.search(r'extern [^\n]*\bnq \(', c_src):
                failures.append(
                    'extern declares the LOCAL alias `nq` (call site uses '
                    f'`{callee}`)')
            # 2. Every call-site name must be declared or defined.
            if not re.search(r'\b%s \(' % re.escape(callee), c_src):
                failures.append(f'call-site symbol `{callee}` is never declared')

        # 3. gcc on the unit: no implicit declaration, no char*<-int.
        c_file = os.path.join(td, 'alias_extern.c')
        with open(c_file, 'w') as fh:
            fh.write(c_src)
        cc = subprocess.run(
            [build_config.find_gcc(), '-fgimple', '-fsyntax-only', '-Os', '-g',
             '-ftrivial-auto-var-init=zero', f'-I{RUNTIME_INC}', c_file],
            capture_output=True, text=True, timeout=120)
        if 'implicit declaration' in cc.stderr or 'int-conversion' in cc.stderr \
                or 'makes pointer from integer' in cc.stderr:
            failures.append('gcc: ' + cc.stderr.strip()[:800])
        elif cc.returncode != 0:
            failures.append('gcc -fsyntax-only failed: ' + cc.stderr.strip()[:800])

    if failures:
        for f in failures:
            print('FAIL  function_scoped_alias_extern:', f)
        return 1
    print('PASS  function_scoped_alias_extern')
    return 0


if __name__ == '__main__':
    sys.exit(main())
