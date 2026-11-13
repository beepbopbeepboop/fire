# CODEGEN: `re.sub(pat, lambda ..., src)` passes the lambda's ADDRESS as the replacement string, so the compiled result is garbage

Status: OPEN. Filed 2026-11-12 by the regex-table worker on HEAD aacfc103f (the table-address fix landed just before; this bug is independent of it). It was masked inside `__GIMPLE` bodies until that fix, because the same method body did not compile at all; it reproduces on a plain top-level function on any earlier HEAD.

## Symptom

A compiled program printing `re.sub(pattern, lambda ..., s)` returns bytes read out of the lambda's machine code instead of the lambda's string. In a method body, the exact shape fire_compiler.py's `Parser._merge_string_literals` uses (line 7364) is wrong:

    import re

    class P:
        def merge(self, raws):
            _merged = ''
            for _r in raws:
                _inner = _r
                _inner = re.sub(r'(\\N\{[^{}]*\})|([{}])',
                                lambda _m: _m.group(1) if _m.group(1)
                                else _m.group(2) * 2,
                                _inner)
                _merged += _inner
            return _merged

    print(P().merge(["a{b}c"]))

CPython prints `a{{b}}c`. The compiled program prints
`a\xfd{\xb0\xa9\xfd\x03b\xfd{\xb0\xa9\xfd\x03c` (the replacement inserted between
`a`/`b` and `b`/`c` is the lambda's code/pointer, read as a C string).

## Root cause

The generated code takes the replacement-STRING path with a function pointer as
the string:

    _t6 = _funcptr_P__merge_lambda_1;                      /* void * */
    _t5 = mojo_regex_sub_str (_t2, _t3, _t4, 1, 0, _t6, s);

`emit_loops.py`'s `_re_sub_repl_is_callback` only answers True for an
`IdentExpr` (a closure or a bare top-level `def` name); a `LambdaExpr` argument
is not one, so it is classified as a replacement string and never reaches
`_lower_re_sub_callback` (which already has a non-`IdentExpr` fallback that
lowers the expression and passes the resulting pointer as the callback).

## Next step

1. Reproduce cheaply: compile the snippet above with
   `gimple_codegen._run_pipeline(src, do_imports=True)[0]`, gcc it as C
   (`gcc -fgimple -x c -Iruntime`, link `runtime/fire_runtime.c`) and diff the
   run against CPython.
2. Treat `LambdaExpr` as a callback in `_re_sub_repl_is_callback`. Before
   landing, check the CAPTURING-lambda case: `_lower_re_sub_callback`'s
   fallback passes `(void *)0` as the environment, so a lambda that captures a
   local needs the closure env wired like the `_closure_envs` branch, or the
   lowering must refuse loudly rather than read the wrong env.
3. The quick test is a new case in `test_gimple.py` (this same program, run
   vs CPython) plus `test_runtime_re.py` staying green.

## Done when

The compiled snippet prints `a{{b}}c` like CPython, and the new
`test_gimple.py` case and `test_runtime_re.py` pass. Then delete this doc in
that commit.
