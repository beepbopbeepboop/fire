#!/usr/bin/env python3
"""Regression: a lifted closure must see a plain function-body
`import <module> as <alias>` and lower `<alias>.<func>(...)` to the
defining module's QUALIFIED symbol.

Symptom this pins (the self-host link's unqualified `_conforms_to`
reference from the lifted `_comptime_conforms_to_pred` lambdas):
a lifted closure seeded its import scope from `_func_import_frames` and a
pre-scan of its own body, but the collector recorded only
`FromImportStmt` bindings. A plain `import M as A` alias was therefore
invisible in the lifted body: the receiver read fell through to the
`(int64_t)0;  /* ct param or undeclared: A */` placeholder and the call
resolved on a placeholder `int64_t`, emitting the bare member name (an
undefined symbol at link in the self-host build) or a
`int64_t.<member>() stubbed` silent zero.

The test compiles a minimal self-contained repro: a defining module with
a free function, consumed by functions whose bodies `import` it under the
alias `_comptime_eval` (a spelling that overlaps the comptime machinery's
own `_comptime_*` names) and then call through that alias from a lifted
lambda and from a nested `def`. It also pins the two non-regressions in
the doc's acceptance: a direct (non-lifted) alias call stays qualified,
and a closure over a genuine local value still reads it from its env.

Run:  python3 test_codegen_selfhost_link_two_unqualified_calls_part1.py
"""
import os
import re
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import gimple_codegen  # noqa: E402

ALIAS = '_comptime_eval'
FUNC = 'twiddle'

FILES = {
    'p/__init__.py': '',
    'p/defs.py': (
        'def twiddle(x: Int64) -> Int64:\n'
        '    return x + 1\n'
    ),
    'p/main.py': (
        'def make_pred() -> Int64:\n'
        f'    import p.defs as {ALIAS}\n'
        f'    return lambda t: {ALIAS}.{FUNC}(t)\n'
        '\n'
        'def make_pred_def() -> Int64:\n'
        f'    import p.defs as {ALIAS}\n'
        '    def pred(t):\n'
        f'        return {ALIAS}.{FUNC}(t)\n'
        '    return pred\n'
        '\n'
        'def direct() -> Int64:\n'
        f'    import p.defs as {ALIAS}\n'
        f'    return {ALIAS}.{FUNC}(7)\n'
        '\n'
        'def make_capture(n: Int64) -> Int64:\n'
        '    return lambda t: t + n\n'
        '\n'
        'def main():\n'
        '    f = make_pred()\n'
        '    g = make_pred_def()\n'
        '    print(f(3) + g(4) + direct() + make_capture(5)(1))\n'
        '\n'
        'main()\n'
    ),
}


def _function_body(c_src, symbol):
    """The `{...}` body of the DEFINITION named `symbol` (forward
    declarations end in `;` and are skipped), or None."""
    for m in re.finditer(r'\b%s\s*\([^;{}]*\)\s*\{' % re.escape(symbol), c_src):
        start = m.end() - 1
        depth = 0
        for i in range(start, len(c_src)):
            if c_src[i] == '{':
                depth += 1
            elif c_src[i] == '}':
                depth -= 1
                if depth == 0:
                    return c_src[start:i + 1]
    return None


def _compile():
    with tempfile.TemporaryDirectory() as td:
        for rel, body in FILES.items():
            fp = os.path.join(td, rel)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, 'w') as fh:
                fh.write(body)
        entry = os.path.join(td, 'p', 'main.py')
        return gimple_codegen._run_pipeline(
            FILES['p/main.py'], filename=entry, do_imports=True)[0]


def _check_lifted(failures, c_src, label, symbol):
    body = _function_body(c_src, symbol)
    if body is None:
        failures.append(f'{label}: no definition of `{symbol}` in the output')
        return
    # 1. The call goes through the defining module's qualified symbol.
    if f'p_defs_{FUNC}_' not in body:
        failures.append(
            f'{label}: lifted body does not call the qualified '
            f'`p_defs_{FUNC}_...` symbol; body:\n{body}')
    # 2. No bare/unqualified call to the member.
    if re.search(r'(?<![\w.])%s\s*\(' % re.escape(FUNC), body):
        failures.append(
            f'{label}: lifted body emits a bare `{FUNC}(...)` call; '
            f'body:\n{body}')
    # 3. The alias is not lowered as an unknown-value placeholder...
    if re.search(r'(?:ct param|undeclared):\s*%s\b' % re.escape(ALIAS), body):
        failures.append(
            f'{label}: module alias `{ALIAS}` lowered as an '
            f'undeclared/ct-param placeholder; body:\n{body}')
    # ...and is not read from the closure env as a value.
    if re.search(r'_env->%s\b' % re.escape(ALIAS), body):
        failures.append(
            f'{label}: module alias `{ALIAS}` read from the closure env; '
            f'body:\n{body}')


def main():
    failures = []
    c_src = _compile()

    # The lifted lambda and the nested `def` are the two lifted-closure
    # shapes: the lambda is lowered while the enclosing body runs, the
    # nested def is emitted from the whole-module pre-scan.
    _check_lifted(failures, c_src, 'lifted lambda', 'make_pred_lambda_1')
    _check_lifted(failures, c_src, 'lifted nested def', 'make_pred_def_pred')

    # A direct (non-lifted) alias call keeps today's qualified lowering.
    direct = _function_body(c_src, 'direct')
    if direct is None:
        failures.append('no definition of `direct` in the output')
    else:
        if f'p_defs_{FUNC}_' not in direct:
            failures.append(
                'direct alias call is not module-qualified; body:\n' + direct)
        if re.search(r'(?<![\w.])%s\s*\(' % re.escape(FUNC), direct):
            failures.append(
                'direct alias call emits a bare member name; body:\n' + direct)

    # A genuine captured value is still read from the closure env. The
    # lifted symbol's numeric suffix is assigned by a whole-TU counter, so
    # find the closure by its env read rather than by name.
    capture_body = None
    for m in re.finditer(
            r'__GIMPLE[^\n]*?\b(\w+)\s*\([^;{}]*\)\s*\{', c_src):
        body = _function_body(c_src, m.group(1))
        if body and re.search(r'_env->n\b', body):
            capture_body = body
            break
    if capture_body is None:
        failures.append(
            'a captured local value is no longer read from the closure env')

    if failures:
        for f in failures:
            print('FAIL  selfhost_link_two_unqualified_calls_part1:', f)
        return 1
    print('PASS  selfhost_link_two_unqualified_calls_part1')
    return 0


if __name__ == '__main__':
    sys.exit(main())
