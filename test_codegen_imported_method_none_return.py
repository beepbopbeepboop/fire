#!/usr/bin/env python3
"""Pin: an IMPORTED method's word return may be the shared None box (stage 5c, H1).

A per-file (`do_imports=False`) compile cannot see the defining unit's
decisions. A method whose body returns a MIXED field (a scalar beside `None`,
`self.v = None` + `self.bump` storing `1`) returns the boxed word, but the
importer's TU only knew `int64_t`. Printing was already right (the runtime's
word printer asks the box's kind), while `x is None` / `x == None` compared
the word with `0` and answered False where CPython answers True.

The fix: `module_gen`'s imported-struct-method loop records every
word-returning imported symbol (`_unknown_ret_word_syms`), `_emit_call` marks
that call result `_word_mark_dyn`, and `_lbt_boxed_none_compare` takes a dyn
word for `is`/`==` so the compare asks `mojo_word_is_none` — a
registered-pointer test, safe for a plain integer too.

Two fixtures, each built the way `build_stdlib_dylib.compile_module_to_c`
builds one dylib module (its own translation unit, no entry points), gcc
`-fgimple`, linked against `runtime/fire_runtime.c`, RUN, and compared with
CPython on the same two files:

  * mixed field: the box crosses and `is None` / `== None` / print / `+ 1`
    all match;
  * refs-only field (`self.s` receives only strings and `None`): the field is
    a `char *`, so `is None` keeps its NULL-pointer test and still matches.

Run: python3 tools/memslot.py --gb 8 --label imported-method-none -- \
         python3 test_codegen_imported_method_none_return.py
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from build_config import find_gcc  # noqa: E402
from build_stdlib_dylib import compile_module_to_c  # noqa: E402
import mojo.middle.cross_module as cross_module  # noqa: E402
from exec_budget import COMPILE_TIMEOUT_S, RUN_TIMEOUT_S  # noqa: E402

RUNTIME_DIR = os.path.join(HERE, 'runtime')
RUNTIME_C = os.path.join(RUNTIME_DIR, 'fire_runtime.c')
ENTRY_SRC = 'int main(void) { return 0; }\n'

# name -> (helper.py, main.py, expected stdout)
CASES = {
    'mixed_field_return': (
        'class Box:\n'
        '    def __init__(self):\n'
        '        self.v = None\n'
        '    def reset(self):\n'
        '        self.v = None\n'
        '    def bump(self):\n'
        '        self.v = 1\n'
        '    def set(self, x):\n'
        '        self.v = x\n'
        '    def get(self):\n'
        '        return self.v\n',
        'from helper import Box\n'
        '\n'
        'def main():\n'
        '    b = Box()\n'
        '    x = b.get()\n'
        '    print(x)\n'
        '    print(x is None)\n'
        '    print(x == None)\n'
        '    b.bump()\n'
        '    y = b.get()\n'
        '    print(y)\n'
        '    print(y + 1)\n'
        '    b.set("hi")\n'
        '    print(b.get())\n'
        '    print(b.get() == "hi")\n'
        '    print(b.get() != "no")\n'
        '    b.reset()\n'
        '    print(b.get())\n'
        '    print(b.get() is None)\n'
        '\n'
        'main()\n',
        'None\nTrue\nTrue\n1\n2\nhi\nTrue\nTrue\nNone\nTrue\n',
    ),
    # The refs-only slot (rule 1): its non-None stores are all references, so
    # the bare 0 IS None. H2's pre-pass publishes `put("x")` to the defining
    # unit (the field's class becomes 'refs') and the defining unit publishes
    # `get`'s `ret_class: refs` back, so the importer spells the unset value
    # `None` and the stored one `x`. Also pins that the mixed marking did not
    # over-reach onto a plain word return.
    'refs_only_field_return': (
        'class Label:\n'
        '    def __init__(self):\n'
        '        self.s = None\n'
        '    def put(self, s):\n'
        '        self.s = s\n'
        '    def clear(self):\n'
        '        self.s = None\n'
        '    def get(self):\n'
        '        return self.s\n',
        'from helper import Label\n'
        '\n'
        'def main():\n'
        '    a = Label()\n'
        '    print(a.get())\n'
        '    print(a.get() is None)\n'
        '    a.put("x")\n'
        '    print(a.get())\n'
        '    print(a.get() == "x")\n'
        '    a.clear()\n'
        '    print(a.get() is None)\n'
        '    print(a.get())\n'
        '\n'
        'main()\n',
        'None\nTrue\nx\nTrue\nTrue\nNone\n',
    ),
}


def _write(td: str, rel: str, src: str) -> str:
    path = os.path.join(td, rel)
    with open(path, 'w') as f:
        f.write(src)
    return path


def _cpython_stdout(td: str, entry: str) -> str:
    env = dict(os.environ)
    env['PYTHONPATH'] = td + (os.pathsep + env['PYTHONPATH']
                              if env.get('PYTHONPATH') else '')
    r = subprocess.run([sys.executable, entry], capture_output=True, text=True,
                       cwd=td, env=env, timeout=RUN_TIMEOUT_S)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    return r.stdout


def _run_case(name: str, helper_src: str, main_src: str, want: str) -> None:
    gcc = find_gcc()
    with tempfile.TemporaryDirectory() as td:
        helper_path = _write(td, 'helper.py', helper_src)
        main_path = _write(td, 'main.py', main_src)
        # Oracle: the fixture itself must be a valid program.
        assert _cpython_stdout(td, main_path) == want, f'[{name}] fixture'

        # H2's pre-pass: publish BOTH modules' calls to the other's callees
        # before either compiles (the whole-closure evidence pass), plus the
        # parent-side PROVISIONAL signatures `ret_class=refs` — exactly what
        # `build_stdlib_dylib.build` does in the parent process.
        cross_module.reset()
        cross_module.scan_module_calls(helper_src, 'helper')
        cross_module.scan_module_calls(main_src, 'main')
        cross_module.publish_source_signatures(
            [(helper_path, helper_src), (main_path, main_src)])
        snap_path = os.path.join(td, 'evidence.json')
        with open(snap_path, 'w') as f:
            json.dump(cross_module.snapshot(), f)

        objs = []
        for module, src, path in (('helper', helper_src, helper_path),
                                  ('main', main_src, main_path)):
            if module == 'main':
                # The IMPORTER is compiled in a FRESH process seeded only
                # from the parent's snapshot — the multi-process build's
                # shape. If this path did not carry `ret_class=refs`, the
                # importer would print the unset value as `0` and the case
                # below would fail.
                c_file = os.path.join(td, module + '.gen.c')
                r = subprocess.run(
                    [sys.executable, os.path.abspath(__file__),
                     '--compile-seeded', path, module, snap_path, c_file],
                    capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
                assert r.returncode == 0, (
                    f'[{name}] seeded importer compile failed:\n{r.stderr[:2000]}')
                with open(c_file) as f:
                    c_text = f.read()
                if 'refs_only' in name:
                    # The structural half of the proof: the fresh process
                    # used the refs-only spelling, which only the parent's
                    # published `ret_class` can have told it.
                    assert 'mojo_word_str_or_none' in c_text, (
                        f'[{name}] the seeded importer never used the '
                        f'refs-only spelling:\n{c_text[:2000]}')
            else:
                # The definer compiles in the parent with the evidence
                # registry filled; it publishes its own signatures too, but
                # the child above cannot see them (that is the point).
                c_text = compile_module_to_c(src, path, module,
                                             publish_signatures=True)
            assert c_text.strip(), f'[{name}] compile_module_to_c({module}) empty'
            c_file = os.path.join(td, module + '.gen.c')
            with open(c_file, 'w') as f:
                f.write(c_text)
            obj = c_file + '.o'
            r = subprocess.run([gcc, '-fgimple', f'-I{RUNTIME_DIR}', '-c',
                                c_file, '-o', obj],
                               capture_output=True, text=True,
                               timeout=COMPILE_TIMEOUT_S)
            assert r.returncode == 0, (
                f'[{name}] gcc -fgimple rejected {module}.py:\n'
                f'{r.stderr[:2000]}\n---\n{c_text}')
            objs.append(obj)

        entry_c = _write(td, 'entry.c', ENTRY_SRC)
        exe = os.path.join(td, 'prog')
        r = subprocess.run([gcc, '-o', exe, *objs, entry_c, RUNTIME_C],
                           capture_output=True, text=True,
                           timeout=COMPILE_TIMEOUT_S)
        assert r.returncode == 0, (
            f'[{name}] link failed:\n{r.stderr[:2000]}')
        r = subprocess.run([exe], capture_output=True, text=True,
                           timeout=RUN_TIMEOUT_S)
        assert r.returncode == 0, (name, r.returncode, r.stdout, r.stderr)
        assert r.stdout == want, (
            f'[{name}] the built program printed {r.stdout!r}; CPython '
            f'printed {want!r}')


def test_imported_method_none_return():
    for name, (helper_src, main_src, want) in CASES.items():
        _run_case(name, helper_src, main_src, want)


def _compile_seeded(path: str, module: str, snap_path: str, out_c: str) -> int:
    """Child-process half of the parallel-build proof: seed the registry from
    the parent's snapshot in a FRESH process (as a ProcessPoolExecutor worker
    does) and compile one module."""
    import json
    import mojo.middle.cross_module as cross_module
    cross_module.reset()
    with open(snap_path) as f:
        cross_module.seed(json.load(f))
    c_text = compile_module_to_c(open(path).read(), path, module)
    with open(out_c, 'w') as f:
        f.write(c_text)
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == '--compile-seeded':
        return _compile_seeded(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    test_imported_method_none_return()
    print(f'PASS: an imported method\'s boxed None return keeps `is None` / '
          f'`== None` in the per-file compile ({len(CASES)} programs linked '
          f'and run, each compared with CPython)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
