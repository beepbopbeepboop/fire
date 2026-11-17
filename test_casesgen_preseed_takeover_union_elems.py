#!/usr/bin/env python3
"""Regression: two generator bugs that broke compiling the CPython
`Tools/cases_generator` set (see
COMPILE_FAIL_Tools_cases_generator_analyzer-part3-part2, doc deleted with the fix):

  (1) Preseed claimant takeover: when a sibling module's class name is one of
      this compiler's own preseeded AST names (`IfStmt`), the sibling's real
      layout must take over the bare C name -- no `parsing_IfStmt` struct
      minting, and no compiler-layout phantom (`then_body`/`elifs`) left
      behind in the generated C.

  (2) Union annotation element seed: a field annotated `list[Stmt] | None`
      must keep its list element type when the annotation is a union, so a
      loop over the field iterates typed elements (`mojo_list_get_int` +
      `(Stmt *)` + static virtual dispatch) instead of boxed objects
      (`mojo_list_get_boxed` + dynamic getattr, which cannot find trampoline
      methods -> `AttributeError: tokens` at run time).

Checks (through compile_to_gimple(do_imports=True); same fixture set as
test_sibling_ast_name_collision.py, which skips when the CPython source tree
is absent -- $PYTHON_SRC, default /Users/mrs/net/Python-3.14.6):
  (a) no `typedef struct parsing_IfStmt` in the generated C;
  (b) exactly one `typedef struct IfStmt`, carrying `if_;` and no
      `then_body;`/`elifs;`, and no other IfStmt-family typedef carrying
      `then_body;`;
  (c) in the `__mgco_MacroIfStmt_tokens_body` trampoline, the loop over
      `self->else_body` fetches typed elements (`mojo_list_get_int` +
      `(Stmt *)` + the static virtual dispatch call) in the window before the
      first boxed fetch (which belongs to the `yield from` driver);
  (d) gcc -fgimple -fsyntax-only accepts the generated C with no `error:`.

Run: `python3 test_casesgen_preseed_takeover_union_elems.py`
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from build_config import find_gcc
from gimple_codegen import compile_to_gimple

SCRATCH = os.path.join(HERE, '.tmp')
os.makedirs(SCRATCH, exist_ok=True)

PY_SRC = os.environ.get('PYTHON_SRC', '/Users/mrs/net/Python-3.14.6')
CG_DIR = os.path.join(PY_SRC, 'Tools', 'cases_generator')
SIBLINGS = ['parsing.py', 'lexer.py', 'plexer.py', 'cwriter.py']

MAIN_SRC = '''import parsing

def f() -> int:
    return 0
'''


def _ifstmt_typedefs(c_src: str) -> list:
    """Return [(name, body)] for every IfStmt-family struct typedef."""
    out = []
    for name in re.findall(r'typedef struct (\w*IfStmt\w*) \{', c_src):
        m = re.search(r'typedef struct %s \{(.*?)\} %s;'
                      % (re.escape(name), re.escape(name)), c_src, re.S)
        if m:
            out.append((name, m.group(1)))
    return out


def _trampoline_body(c_src: str, func: str) -> str | None:
    """Return the C body of a `__mgco_*_body` trampoline function."""
    m = re.search(r'void %s \(int64_t __c, [A-Za-z_]+ \* self\)\n\{'
                  % re.escape(func), c_src)
    if not m:
        return None
    rest = c_src[m.end():]
    m2 = re.search(r'^\}', rest, re.M)
    return rest[:m2.start()] if m2 else None


def main() -> int:
    if not os.path.isfile(os.path.join(CG_DIR, 'parsing.py')):
        print('SKIP  test_casesgen_preseed_takeover_union_elems: '
              f'{CG_DIR}/parsing.py absent')
        return 0

    tmp = tempfile.mkdtemp(dir=SCRATCH)
    try:
        for name in SIBLINGS:
            shutil.copy(os.path.join(CG_DIR, name), tmp)
        main_path = os.path.join(tmp, 'main.py')
        with open(main_path, 'w') as f:
            f.write(MAIN_SRC)

        cwd, old_path = os.getcwd(), list(sys.path)
        os.chdir(tmp)
        sys.path.insert(0, tmp)
        try:
            c_src = compile_to_gimple(MAIN_SRC, do_imports=True,
                                      filename=main_path)
        finally:
            os.chdir(cwd)
            sys.path[:] = old_path

        failures = []

        # (a) no module-qualified mint for the claimed preseed name.
        if re.search(r'typedef struct parsing_IfStmt\b', c_src):
            failures.append('generated C mints `typedef struct parsing_IfStmt`')

        # (b) a single real-layout IfStmt, no compiler-layout phantom.
        typedefs = _ifstmt_typedefs(c_src)
        bare = [body for name, body in typedefs if name == 'IfStmt']
        if len(bare) != 1:
            failures.append(f'expected exactly one `typedef struct IfStmt`, '
                            f'found {len(bare)}')
        else:
            body = bare[0]
            for field in ('if_', 'condition', 'body', 'else_', 'else_body'):
                if not re.search(r'\b%s;' % field, body):
                    failures.append(f'IfStmt typedef lacks field {field!r}')
            for field in ('then_body', 'elifs'):
                if re.search(r'\b%s;' % field, body):
                    failures.append(f'IfStmt typedef carries the compiler-'
                                    f'layout field {field!r}')
        for name, body in typedefs:
            # `ComptimeIfStmt` is the compiler's own AST node (a different
            # class, never claimed by the sibling); its then_body is legit.
            if name == 'ComptimeIfStmt':
                continue
            if name != 'IfStmt' and re.search(r'\bthen_body;', body):
                failures.append(f'phantom compiler-layout typedef '
                                f'`{name}` still carries then_body')

        # (c) the union-annotated else_body loop is typed.
        tbody = _trampoline_body(c_src, '__mgco_MacroIfStmt_tokens_body')
        if tbody is None:
            failures.append('trampoline `__mgco_MacroIfStmt_tokens_body` '
                            'not found in the generated C')
        else:
            idx = tbody.find('= self->else_body;')
            if idx < 0:
                failures.append('no `self->else_body` loop in the trampoline')
            else:
                # The window is the else_body loop's element fetch: it ends at
                # the first `mojo_list_get_boxed` after the field load. Post-fix
                # that first boxed fetch belongs to the `yield from
                # stmt.tokens()` driver (dynamic iterable dispatch — expected);
                # pre-fix it was the loop's own element read, so the window held
                # no `mojo_list_get_int` and the test failed.
                end = tbody.find('mojo_list_get_boxed', idx)
                window = tbody[idx:end if end > idx else idx + 4000]
                if 'mojo_list_get_int' not in window:
                    failures.append('else_body loop does not use '
                                    'mojo_list_get_int (element type lost)')
                if '(Stmt *)' not in window:
                    failures.append('else_body loop lacks the (Stmt *) cast')
                if '_mojo_virt_parsing_Stmt_tokens' not in window:
                    failures.append('else_body loop lacks the static virtual '
                                    'dispatch call')

        # (d) the generated C compiles.
        cfile = os.path.join(tmp, 'main.c')
        with open(cfile, 'w') as f:
            f.write(c_src)
        r = subprocess.run([find_gcc(), '-fgimple', '-fsyntax-only',
                            '-I' + os.path.join(HERE, 'runtime'), cfile],
                           capture_output=True, text=True)
        errors = [ln for ln in r.stderr.splitlines() if 'error:' in ln]
        if r.returncode != 0 or errors:
            failures.append(f'gcc -fgimple reports {len(errors)} error(s); '
                            f'first: {errors[:1]}')

        if failures:
            for msg in failures:
                print(f'FAIL  test_casesgen_preseed_takeover_union_elems  {msg}')
            return 1
        print('PASS  test_casesgen_preseed_takeover_union_elems')
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
