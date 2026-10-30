"""Regression for check_all callable-param for-loop refusal."""
import gimple_codegen, test_gimple_generator_runner as t

def test_check_all_refusal_named():
    # The refusal must NAME the callable-local case (check(...)), not a flat CallExpr.
    t.test_generator_refused("check_all_callable_local", """\
def check_all(analysis, checks, *, failfast=False):
    for check in checks or ():
        for data, failure in check(analysis):
            yield data, failure

def main():
    pass
""", "callable-valued local/parameter 'check(...)'")
