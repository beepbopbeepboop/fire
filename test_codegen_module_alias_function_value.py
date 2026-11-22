#!/usr/bin/env python3
"""Regression test: a function read as a VALUE through a bare
`import MOD as alias`, in the per-file (`do_imports=False`) single-module
compile the bootstrap `--dump` stages use.

Bug (fixed here; `bugs/CODEGEN_selfhost_stage2_attributeerror_comptimevar_node.md`
stays open until the bootstrap chain it needs is re-enabled, and this file is
its named quick pin): `_lower_MemberExpr` answered
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
`_gmp_emit_imported_symbol_stubs` pass emits the matching extern. A member
the aliased module only RE-EXPORTS is resolved through the same hop walk
(`_find_symbol_home_module` with `want_name`), for both the VALUE and the
CALL spelling, including a re-export that RENAMES
(`from impl import double_it as dt`).

Every case is an end-to-end RUN against CPython's own stdout rather than a
C-text assertion alone, so a value that compiles but calls the wrong address
is a failure too.
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

ENTRY_SRC = 'int main(void) { return 0; }\n'

# name -> (files, entry module, expected stdout, value_read).
# Each entry module is compiled through `compile_module_to_c` — the
# per-file `do_imports=False` path `fire.py --dump` uses — then every
# module in the case is linked with the runtime and RUN.
CASES = {
    # MODULE-scope and FUNCTION-scope both bind a function VALUE through the
    # alias: the first is the exact shape comptime.py had, the second the same
    # lowering reached from inside a body.
    'value_module_and_function_scope': (
        {'helper.py': HELPER_SRC,
         'main.py': ('import helper as h\n'
                     '\n'
                     'f = h.double_it\n'
                     '\n'
                     'def go():\n'
                     '    g = h.offset\n'
                     '    print(f(21))\n'
                     '    print(g(35))\n'
                     '\n'
                     'go()\n')},
        'main', '42\n42\n', True),
    # A re-export that RENAMES: `dt` is bound in helper's namespace but the
    # definition is impl's `double_it`, and the mangled symbol is keyed on
    # the DEFINER's spelling.
    'value_through_renamed_reexport': (
        {'impl.py': HELPER_SRC,
         'helper.py': 'from impl import double_it as dt\n',
         'main.py': 'import helper as h\nf = h.dt\nprint(f(21))\n'},
        'main', '42\n', True),
    # The same renamed re-export, CALLED through the alias (the CALL
    # spelling shares the hop walk).
    'call_through_renamed_reexport': (
        {'impl.py': HELPER_SRC,
         'helper.py': 'from impl import double_it as dt\n',
         'main.py': 'import helper as h\nprint(h.dt(21))\n'},
        'main', '42\n', False),
    # A re-export under its own name, called through the alias.
    'call_through_reexport': (
        {'impl.py': HELPER_SRC,
         'helper.py': 'from impl import double_it\n',
         'main.py': 'import helper as h\nprint(h.double_it(21))\n'},
        'main', '42\n', False),
    # A parameter default bound to a module-alias function value (the
    # default-parameter path reaches `_callable_value_symbol` directly).
    'value_as_parameter_default': (
        {'helper.py': HELPER_SRC,
         'main.py': ('import helper as h\n'
                     'def go(g=h.double_it):\n'
                     '    print(g(21))\n'
                     'go()\n')},
        'main', '42\n', True),
    # A function-scoped import whose alias is used as a VALUE.
    'value_function_scoped_import': (
        {'helper.py': HELPER_SRC,
         'main.py': ('def go():\n'
                     '    import helper as h\n'
                     '    f = h.double_it\n'
                     '    return f(21)\n'
                     'print(go())\n')},
        'main', '42\n', True),
}


def _run_case(files, entry, want, value_read, gcc):
    failures = []
    with tempfile.TemporaryDirectory() as td:
        paths = {}
        for rel, src in files.items():
            path = os.path.join(td, rel)
            if os.path.dirname(path):
                os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w') as fh:
                fh.write(src)
            paths[rel] = path
        entry_rel = entry + '.py'

        # Oracle: the fixture must be a valid program, or a compile refusal
        # below would be a harness mistake rather than a compiler bug.
        py = subprocess.run([sys.executable, paths[entry_rel]],
                            capture_output=True, text=True, cwd=td,
                            env=dict(os.environ, PYTHONPATH=td),
                            timeout=RUN_TIMEOUT_S)
        if py.returncode != 0:
            failures.append(f"CPython on the fixture exited {py.returncode} "
                            f"({py.stderr[:400]}) — the fixture itself is wrong")
            return failures
        if py.stdout != want:
            failures.append(f"CPython printed {py.stdout!r}, expected "
                            f"{want!r} — the fixture is not the shape this "
                            "test pins")
            return failures

        objs = []
        order = ([r for r in paths
                  if r.endswith('.py') and r != entry_rel] + [entry_rel])
        for rel in order:
            module = rel[:-3].replace(os.sep, '.')
            try:
                c_text = compile_module_to_c(open(paths[rel]).read(),
                                             paths[rel], module)
            except Exception as e:  # noqa: BLE001 — reported, not swallowed
                failures.append(f"compile_module_to_c({module}) raised "
                                f"{type(e).__name__}: {e}")
                continue
            if not c_text or not c_text.strip():
                failures.append(f"compile_module_to_c({module}) produced no C")
                continue
            if rel == entry_rel:
                # The defect itself: a function VALUE must be the registered
                # function's address, not a runtime attribute read on the
                # alias's placeholder module marker.
                if '_mojo_dispatch_getattr' in c_text and re.search(
                        r'"(double_it|dt)"', c_text):
                    failures.append(
                        "the importer's C still carries a member NAME as a "
                        "dynamic-getattr string — the read fell through to "
                        "the runtime dispatch that raises AttributeError on "
                        "the NULL module marker")
                if value_read and not re.search(
                        r'_funcptr_\w*double_it_\w+', c_text):
                    failures.append(
                        "the importer's C has no `_funcptr_*double_it_*` — "
                        "the function VALUE was not lowered to a function")
            c_file = os.path.join(td, rel.replace(os.sep, '_') + '.gen.c')
            obj = c_file + '.o'
            with open(c_file, 'w') as fh:
                fh.write(c_text)
            cc = subprocess.run(
                [gcc, '-fgimple', '-I', str(ROOT / 'runtime'), '-c',
                 c_file, '-o', obj],
                capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
            if cc.returncode != 0:
                failures.append(f"gcc -fgimple rejected {module}'s C:\n"
                                f"{cc.stderr[:2000]}")
            else:
                objs.append(obj)

        if len(objs) == len(order):
            entry_c = os.path.join(td, 'entry.c')
            with open(entry_c, 'w') as fh:
                fh.write(ENTRY_SRC)
            exe = os.path.join(td, 'prog')
            link = subprocess.run(
                [gcc, '-o', exe, *objs, entry_c,
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
    return failures


def main() -> int:
    gcc = find_gcc()
    failures = []
    for name, (files, entry, want, value_read) in CASES.items():
        for failure in _run_case(files, entry, want, value_read, gcc):
            failures.append(f"[{name}] {failure}")

    if failures:
        print("FAILED:")
        for failure in failures:
            print("  " + failure)
        return 1

    print(f"PASS: a function VALUE read through a module alias is a real "
          f"function value in the per-file compile ({len(CASES)} shapes); "
          "each program runs and prints CPython's answer")
    return 0


if __name__ == '__main__':
    sys.exit(main())
