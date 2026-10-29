"""Regression test for bug:COMPILE_FAIL_Tools_scripts_summarize_stats
Reproduces the closure-factory refusal: a nested def whose body has
exactly one nested def (the closure) and a final return of it.
"""

CLOSURE_FACTORY_SRC = (
    'def t0():\n'
    '    def calc_hist(key: int, den: int):\n'
    '        def calc(stats: int) -> int:\n'
    '            return stats * key + den\n'
    '        return calc\n'
    '    def gen():\n'
    '        yield calc_hist(1, 2)(10)\n'
    '    return next(gen())\n'
    '\n'
    'def main():\n'
    '    print(t0())\n')

def test_generator_closure_factory_refused():
    import gimple_codegen as G
    try:
        G.compile_to_gimple_with_cpp(CLOSURE_FACTORY_SRC, do_imports=False)
    except RuntimeError as e:
        msg = str(e)
    else:
        msg = None
    assert msg is not None, 'closure factory now compiles: drop doc entry'
    assert "unresolved callee 'calc_hist(...)'" in msg, f"unexpected msg: {msg!r}"
