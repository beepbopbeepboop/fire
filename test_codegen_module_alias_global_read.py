#!/usr/bin/env python3
"""Regression test: a module-alias-qualified global read in the per-file
(`do_imports=False`) single-module compile the bootstrap `--dump` stages use.

Bug (the per-file compile's module-alias branch answered a member read with
only `_callable_value_symbol`, so a data global — `h.CONST` — fell to the
generic dynamic-dispatch fallback): the importer's C carried

    _t1 = _main_globals.h;               /* module marker: 0 */
    _t2 = (void *)_t1;
    _t4 = _slit_10000;                   /* "CONST" */
    _t3 = _mojo_dispatch_getattr (_t2, _t4);

which is a dynamic getattr on the NULL module marker — exit 1,
`Unhandled exception: AttributeError: CONST`. The `from helper import CONST`
spelling already worked (the import scan registers the accessor and the bare
read routes through it), so the fix registers the SAME accessor for a
module-alias `import helper as h` — the same `<home module>__mojo_global_get_
<name>` symbol and C type, from the same sibling export table — and routes
`h.CONST` through it in `_lower_MemberExpr`'s alias branch, before the
dynamic fallback.

The branch stays behind the existing answers: a function (`_callable_value_
symbol`), a class, a submodule, and a name this module binds itself. A
qualified read is never shadowed by the importer's own binding (Python
scoping); a BARE read of the member name is not what the alias binds and is
not routed through the accessor — it falls through to the owned-global /
placeholder rules exactly as before.

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
    'CONST: int = 41\n'
    'def double_it(x: int) -> int:\n'
    '    return x * 2\n'
)

HELPER_WITH_CLASS_SRC = (
    'class Widget:\n'
    '    pass\n'
    'CONST: int = 41\n'
)

HELPER_BOOL_SRC = 'FLAG = True\n'

ENTRY_SRC = 'int main(void) { return 0; }\n'

# name -> (files, entry module, expected stdout, c_checks).
# c_checks is a list of (kind, payload):
#   ('accessor', symbol)       — the importer's C must contain the symbol
#   ('no_getattr', member)     — no `_mojo_dispatch_getattr` line may quote the member
#   ('no_accessor', symbol)    — the importer's C must NOT contain the symbol
CASES = {
    # The defect itself: a qualified scalar global read through the alias.
    'alias_global_read': (
        {'helper.py': HELPER_SRC,
         'main.py': 'import helper as h\nprint(h.CONST)\n'},
        'main', '41\n',
        [('accessor', 'helper__mojo_global_get_CONST'),
         ('no_getattr', 'CONST')]),
    # The same read from inside a function body: a function-scoped import
    # registers the accessor the same way (the registration is a whole-module
    # scan, into_defs=True) and the read routes through it.
    'alias_global_read_function_scope': (
        {'helper.py': HELPER_SRC,
         'main.py': ('def go():\n'
                     '    import helper as h\n'
                     '    return h.CONST\n'
                     'print(go())\n')},
        'main', '41\n',
        [('accessor', 'helper__mojo_global_get_CONST'),
         ('no_getattr', 'CONST')]),
    # Python shadowing: a name this module binds itself AFTER the import is
    # this module's — the bare read is this module's field, while the
    # qualified read is still the aliased module's global.
    'own_binding_shadows_bare_read': (
        {'helper.py': HELPER_SRC,
         'main.py': ('import helper as h\n'
                     'CONST = 99\n'
                     'print(h.CONST)\n'
                     'print(CONST)\n')},
        'main', '41\n99\n',
        [('accessor', 'helper__mojo_global_get_CONST'),
         ('no_getattr', 'CONST')]),
    # A function of the aliased module is still answered by the function
    # machinery (the value is the real function), never by the accessor.
    'alias_function_value_still_function': (
        {'helper.py': HELPER_SRC,
         'main.py': ('import helper as h\n'
                     'f = h.double_it\n'
                     'print(f(21))\n')},
        'main', '42\n',
        [('no_accessor', 'helper__mojo_global_get_double_it'),
         ('no_getattr', 'double_it')]),
    # A class value through the alias keeps its existing lowering (it must
    # not fall to a dynamic getattr of the class's name on the module marker).
    'alias_class_value_does_not_raise': (
        {'helper.py': HELPER_WITH_CLASS_SRC,
         'main.py': ('import helper as h\n'
                     'W = h.Widget\n'
                     'print(21)\n')},
        'main', '21\n',
        [('no_getattr', 'Widget')]),
    # A bool-valued global through the alias prints as a Python bool: the
    # accessor is a C `int`, so the definer's bool-ness must ride along
    # (`_imported_alias_global_bool`), exactly as the `from` spelling does.
    'alias_bool_global_prints_bool': (
        {'helper.py': HELPER_BOOL_SRC,
         'main.py': 'import helper as h\nprint(h.FLAG)\n'},
        'main', 'True\n',
        [('accessor', 'helper__mojo_global_get_FLAG'),
         ('no_getattr', 'FLAG')]),
    'from_import_bool_global_prints_bool': (
        {'helper.py': HELPER_BOOL_SRC,
         'main.py': 'from helper import FLAG\nprint(FLAG)\n'},
        'main', 'True\n',
        [('accessor', 'helper__mojo_global_get_FLAG'),
         ('no_getattr', 'FLAG')]),
    # The bare `from helper import CONST` spelling already worked and keeps
    # working through the same accessor.
    'from_import_bare_spelling': (
        {'helper.py': HELPER_SRC,
         'main.py': ('from helper import CONST\n'
                     'print(CONST)\n')},
        'main', '41\n',
        [('accessor', 'helper__mojo_global_get_CONST'),
         ('no_getattr', 'CONST')]),
}


def _c_checks_failures(name, c_text, checks):
    failures = []
    for kind, payload in checks:
        if kind == 'accessor':
            if payload not in c_text:
                failures.append(f"[{name}] the importer's C has no "
                                f"`{payload}` — the read did not lower to "
                                "the defining module's accessor")
        elif kind == 'no_accessor':
            if payload in c_text:
                failures.append(f"[{name}] the importer's C contains "
                                f"`{payload}` — a member that is not a "
                                "global must not be routed through the "
                                "accessor")
        elif kind == 'no_getattr':
            for ln in c_text.splitlines():
                if '_mojo_dispatch_getattr' in ln and f'"{payload}"' in ln:
                    failures.append(
                        f"[{name}] the importer's C still carries a member "
                        f"name as a dynamic-getattr string ({payload}) — "
                        "the read fell through to the runtime dispatch that "
                        "raises AttributeError on the NULL module marker")
                    break
    return failures


def _run_case(files, entry, want, c_checks, gcc):
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
                failures.extend(_c_checks_failures(entry, c_text, c_checks))
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
    for name, (files, entry, want, c_checks) in CASES.items():
        for failure in _run_case(files, entry, want, c_checks, gcc):
            failures.append(f"[{name}] {failure}")

    if failures:
        print("FAILED:")
        for failure in failures:
            print("  " + failure)
        return 1

    print(f"PASS: a module-alias-qualified global read is the defining "
          f"module's accessor in the per-file compile ({len(CASES)} shapes); "
          "each program runs and prints CPython's answer")
    return 0


if __name__ == '__main__':
    sys.exit(main())
