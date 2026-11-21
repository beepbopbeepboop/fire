#!/usr/bin/env python3
"""Regression test: `f = <module alias>.<function>` — a function VALUE read
through a bare `import MOD as alias`, in the per-file (`do_imports=False`)
single-module compile the bootstrap `--dump` stages use.

Bug (fixed here; the `CODEGEN_selfhost_stage2_attributeerror_comptimevar_node`
doc is deleted with this fix): `_lower_MemberExpr` answered
"the function `f` as a bare C value" only when `f` was already in
`func_return_types` — a table that holds THIS module's own `def`s plus the
defs of modules a whole-program INLINE compile pulled in. A per-file compile
inlines nothing, so `_as_comptimevar_node = _fc._as_comptimevar_node`
(`import fire_compiler as _fc`) missed that branch and fell through to the
generic dynamic-dispatch fallback:

    _t102 = (void *)_root_globals._fc;          /* module marker: 0 */
    _t104 = _slit_10199;                        /* "_as_comptimevar_node" */
    _t103 = _mojo_dispatch_getattr (_t102, _t104);

which is a NULL receiver, i.e. a fatal, uncaught
`AttributeError: _as_comptimevar_node` the instant the statement runs — for
the stage2 binary that is at startup of EVERY `--dump` (measured: 1-2 s,
exit 1, `bootstrap-stage2-dumps:v.mojo` and siblings). `f(21)` at module
scope and the same read bound inside a function both take this path; the
`from MOD import function` spelling already worked because the import scan
resolves it to a real extern, which is what made the workaround look
correct.

The fix registers the member through the SAME writer the module-qualified
CALL path uses (`funcs_shared.register_module_member_function`), so
`_func_csym` gets the definer's qualifier + overload suffix and the
`_gmp_emit_imported_symbol_stubs` pass emits the matching extern. The test
is an end-to-end RUN against CPython's own stdout rather than a C-text
assertion alone, so a value that compiles but calls the wrong address is a
failure too.
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from build_config import find_gcc  # noqa: E402
from build_stdlib_dylib import compile_module_to_c  # noqa: E402
from exec_budget import COMPILE_TIMEOUT_S, RUN_TIMEOUT_S  # noqa: E402

HELPER_SRC = (
    'def double_it(x: int) -> int:\n'
    '    return x * 2\n'
    '\n'
    'def offset(x: int) -> int:\n'
    '    return x + 7\n'
)

# MODULE-scope and FUNCTION-scope both bind a function VALUE through the
# alias: the first is the exact shape comptime.py had, the second the same
# lowering reached from inside a body (a different scope frame, same branch).
MAIN_SRC = (
    'import helper as h\n'
    '\n'
    'f = h.double_it\n'
    '\n'
    'def go():\n'
    '    g = h.offset\n'
    '    print(f(21))\n'
    '    print(g(35))\n'
    '\n'
    'go()\n'
)

ENTRY_SRC = 'int main(void) { return 0; }\n'


def main() -> int:
    gcc = find_gcc()
    failures = []
    with tempfile.TemporaryDirectory() as td:
        paths = {}
        for name, src in (('helper', HELPER_SRC), ('main', MAIN_SRC)):
            paths[name] = os.path.join(td, name + '.py')
            with open(paths[name], 'w') as fh:
                fh.write(src)
        with open(os.path.join(td, 'entry.c'), 'w') as fh:
            fh.write(ENTRY_SRC)

        # Oracle: the fixture must be a valid program, or a compile refusal
        # below would be a harness mistake rather than a compiler bug.
        py = subprocess.run([sys.executable, paths['main']],
                            capture_output=True, text=True, cwd=td,
                            env=dict(os.environ, PYTHONPATH=td),
                            timeout=RUN_TIMEOUT_S)
        if py.returncode != 0:
            print(f"FAIL: CPython on the fixture exited {py.returncode} "
                  f"({py.stderr[:400]}) — the fixture itself is wrong")
            return 1
        want = py.stdout
        if want.strip() != '42\n42':
            print(f"FAIL: CPython printed {want!r}, expected '42\\n42' — "
                  "the fixture is not the shape this test pins")
            return 1

        objs = []
        for name in ('helper', 'main'):
            try:
                c_text = compile_module_to_c(
                    open(paths[name]).read(), paths[name], name)
            except Exception as e:  # noqa: BLE001 — reported, not swallowed
                failures.append(f"compile_module_to_c({name}) raised "
                                f"{type(e).__name__}: {e}")
                c_text = ''
            if not c_text or not c_text.strip():
                failures.append(f"compile_module_to_c({name}) produced no C")
                continue
            if name == 'main':
                # Non-vacuity + the defect itself: the VALUE has to be the
                # registered function's address, not a runtime attribute read
                # on the alias's placeholder module marker.
                if not re.search(r'_funcptr_helper_double_it_\w+', c_text):
                    failures.append(
                        "the importer's C has no `_funcptr_helper_double_it_*`"
                        " — `f = h.double_it` was not lowered to a function"
                        " value")
                if not re.search(r'extern\s+[^;]*\bhelper_double_it_\w+\s*\(', c_text):
                    failures.append(
                        "the importer's C has no `extern ... helper_double_it_"
                        "* (...)` declaration for the value it takes")
                if '"double_it"' in c_text or '"offset"' in c_text:
                    failures.append(
                        "the importer's C still carries the member NAME as a "
                        "dynamic-getattr string — the read fell through to the"
                        " runtime dispatch that raises AttributeError on the "
                        "NULL module marker")
            c_file = os.path.join(td, name + '.gen.c')
            obj = os.path.join(td, name + '.o')
            with open(c_file, 'w') as fh:
                fh.write(c_text)
            cc = subprocess.run(
                [gcc, '-fgimple', '-I', str(ROOT / 'runtime'), '-c',
                 c_file, '-o', obj],
                capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
            if cc.returncode != 0:
                failures.append(f"gcc -fgimple rejected {name}'s C:\n"
                                f"{cc.stderr[:2000]}")
            else:
                objs.append(obj)

        if len(objs) == 2:
            exe = os.path.join(td, 'prog')
            link = subprocess.run(
                [gcc, '-o', exe, *objs, os.path.join(td, 'entry.c'),
                 str(ROOT / 'runtime' / 'fire_runtime.c')],
                capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
            if link.returncode != 0:
                failures.append("link failed (the registered symbol and the "
                                f"emitted extern disagree):\n{link.stderr[:2000]}")
            else:
                # The module's own top-level runs from a loader constructor,
                # which fires before the trivial `main` the entry supplies.
                run = subprocess.run([exe], capture_output=True, text=True,
                                     timeout=RUN_TIMEOUT_S)
                if run.returncode != 0:
                    failures.append(
                        f"the built program exited {run.returncode}; stderr: "
                        f"{run.stderr[:800]!r}")
                elif run.stdout != want:
                    failures.append(
                        f"the built program printed {run.stdout!r}; CPython "
                        f"printed {want!r}")

    if failures:
        print("FAILED:")
        for f in failures:
            print("  " + f)
        return 1

    print("PASS: `f = <module alias>.<function>` is a real function value in "
          "the per-file compile; the program runs and prints CPython's answer")
    return 0


if __name__ == '__main__':
    sys.exit(main())
