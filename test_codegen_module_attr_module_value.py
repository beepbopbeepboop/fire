#!/usr/bin/env python3
"""Regression test: a function read as a VALUE through a MODULE ATTRIBUTE
that is itself a module, in the per-file (`do_imports=False`) compile.

`import helper as h` where `helper.py` does `import impl as sub` makes
`h.sub` a module object, so `h.sub.double_it` is a real function value. The
CALL spelling `h.sub.double_it(21)` already lowers through
`emit_methods._lmc_two_hop_module_call` (`funcs_shared.module_receiver_ref`). The
VALUE spelling did not: `_lower_MemberExpr` had no branch for "the receiver is
a member read whose value is a module", so it lowered the receiver to a
dynamic getattr on the module marker and read `double_it` off that:

    _mojo_dispatch_getattr(_t2, "sub")          /* module marker: 0 */

which is a fatal `AttributeError: sub` the instant the statement runs. The
same happens for an unaliased dotted import (`import pkg.impl` then
`pkg.impl.double_it`), where the failing attribute is `"impl"`.

The fix answers the outer member against the resolved module through the same
module-qualified value machinery the one-level alias read already uses
(`_callable_value_symbol` -> `register_module_member_value`), so the
function's address is the definer's real symbol.

Every case is an end-to-end RUN compared with CPython's own stdout, and the
emitted C of the importing module must carry no dynamic getattr on a module
attribute name. A receiver that is NOT a module binding (a class instance's
field read) must keep its existing lowering, pinned by the last case.
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

IMPL_SRC = (
    'def double_it(x: int) -> int:\n'
    '    return x * 2\n'
    '\n'
    'def offset(x: int) -> int:\n'
    '    return x + 7\n'
)

HUB_SRC = 'import impl as sub\n'

ENTRY_SRC = 'int main(void) { return 0; }\n'

# name -> (files, entry module, expected stdout, value_read).
# `value_read` says whether the entry module must bind a function VALUE (and
# so must carry no dynamic getattr on a module attribute name).
CASES = {
    # VALUE spelling, two hops: `h.sub` is a module, `.double_it` its function.
    'value_two_hop_alias': (
        {'impl.py': IMPL_SRC,
         'helper.py': HUB_SRC,
         'main.py': ('import helper as h\n'
                     'f = h.sub.double_it\n'
                     'print(f(21))\n')},
        'main', '42\n', True),
    # The same VALUE read bound inside a function body.
    'value_two_hop_in_function': (
        {'impl.py': IMPL_SRC,
         'helper.py': HUB_SRC,
         'main.py': ('import helper as h\n'
                     'def go():\n'
                     '    g = h.sub.offset\n'
                     '    print(g(35))\n'
                     'go()\n')},
        'main', '42\n', True),
    # VALUE spelling through an unaliased dotted import: `pkg.impl` is a module.
    'value_dotted_import': (
        {'pkg/__init__.py': '',
         'pkg/impl.py': IMPL_SRC,
         'main.py': ('import pkg.impl\n'
                     'f = pkg.impl.double_it\n'
                     'print(f(21))\n')},
        'main', '42\n', True),
    # The CALL spellings of both shapes, which must stay green.
    'call_two_hop_alias': (
        {'impl.py': IMPL_SRC,
         'helper.py': HUB_SRC,
         'main.py': ('import helper as h\n'
                     'print(h.sub.double_it(21))\n')},
        'main', '42\n', False),
    'call_dotted_import': (
        {'pkg/__init__.py': '',
         'pkg/impl.py': IMPL_SRC,
         'main.py': ('import pkg.impl\n'
                     'print(pkg.impl.double_it(21))\n')},
        'main', '42\n', False),
    # The direct alias `import pkg.impl as i`: the alias binds the module
    # itself, so `i.double_it` was always a one-level alias read.
    'value_direct_alias': (
        {'pkg/__init__.py': '',
         'pkg/impl.py': IMPL_SRC,
         'main.py': ('import pkg.impl as i\n'
                     'f = i.double_it\n'
                     'print(f(21))\n')},
        'main', '42\n', True),
    # A plain same-module function value: no module attribute involved.
    'value_same_module_function': (
        {'main.py': ('def double_it(x: int) -> int:\n'
                     '    return x * 2\n'
                     'f = double_it\n'
                     'print(f(21))\n')},
        'main', '42\n', False),
    # A receiver that is NOT a module binding: `b.leaf` is a class instance's
    # field, so `.v` must keep the ordinary instance-field read (no module
    # resolution applies, and the value is the stored field, not a function).
    'non_module_receiver_keeps_lowering': (
        {'main.py': ('class Leaf:\n'
                     '    def __init__(self, v: int):\n'
                     '        self.v = v\n'
                     'class Box:\n'
                     '    def __init__(self, v: int):\n'
                     '        self.leaf = Leaf(v)\n'
                     'b = Box(21)\n'
                     'print(b.leaf.v)\n')},
        'main', '21\n', False),
}


def _module_name(rel: str) -> str:
    return rel[:-3].replace(os.sep, '.')


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

        # Package `__init__` files are import plumbing, not compiled modules.
        order = ([r for r in paths
                  if r.endswith('.py') and r != entry_rel
                  and os.path.basename(r) != '__init__.py'] + [entry_rel])
        objs = []
        for rel in order:
            module = _module_name(rel)
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
                # The defect: a module attribute read as a VALUE lowered to a
                # dynamic getattr on the module marker, named by the attribute.
                # `mojo_class_register(...)` names a class the importer
                # defines, which is legitimate; only a dispatch is the defect.
                # A CALL to the dynamic dispatch. The runtime's prototype
                # (`static int64_t _mojo_dispatch_getattr (...)`) and its
                # registration (`mojo_register_getattr_dispatch(
                # _mojo_dispatch_getattr)`) are not calls and are skipped.
                _dyn = [ln for ln in c_text.splitlines()
                        if re.search(r'\b_mojo_dispatch_getattr\s*\(', ln)
                        and not ln.lstrip().startswith('static')
                        and 'mojo_class_register' not in ln]
                if value_read and _dyn:
                    failures.append(
                        "the importer's C still reads a module attribute "
                        "through a dynamic getattr (the module marker is "
                        f"NULL at run time): {_dyn[0].strip()}")
                if value_read and not re.search(
                        r'_funcptr_\w*(?:double_it|offset)_\w+', c_text):
                    failures.append(
                        "the importer's C has no function-value symbol for "
                        "`double_it`/`offset` — the VALUE was not lowered to "
                        "a function")
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

    print(f"PASS: a function VALUE read through a module attribute that is "
          f"itself a module is a real function value in the per-file compile "
          f"({len(CASES)} shapes); each program runs and prints CPython's answer")
    return 0


if __name__ == '__main__':
    sys.exit(main())
