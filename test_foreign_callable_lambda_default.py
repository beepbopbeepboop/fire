from fire_compiler import LambdaExpr, MemberExpr, IdentExpr
from mojo.middle import types


def test_cpp_lambda_ctype_foreign_callable_default():
    lam = LambdaExpr(params=[('f', MemberExpr(obj=IdentExpr(name='csv'), member='reader'))], body=IdentExpr(name='f'))
    result = types._cpp_lambda_ctype(lam)
    assert result == types._FOREIGN_CALLABLES['csv.reader']
    assert result == 'std::function<int64_t()>'


if __name__ == '__main__':
    test_cpp_lambda_ctype_foreign_callable_default()
    print('ok')
