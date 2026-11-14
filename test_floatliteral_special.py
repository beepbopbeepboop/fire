def test_floatliteral_special_values():
    from myinterpreter import Interpreter
    interp = Interpreter('<test>', ['<test>'])
    # Test the four special values
    src = '''
def main():
    a = FloatLiteral.infinity
    b = FloatLiteral.negative_infinity
    c = FloatLiteral.negative_zero
    d = FloatLiteral.nan
    return (a, b, c, d)
'''
    from fire_compiler import py_tokenize, Parser
    tokens = py_tokenize(src)
    stmts = Parser(tokens).parse_module()
    for stmt in stmts:
        interp.execute(stmt)
    result = interp.scope.get('main')()
    assert result[0] == float('inf')
    assert result[1] == float('-inf')
    assert result[2] == float('-0.0')
    assert str(result[3]) == str(float('nan')) or result[3] != result[3]  # NaN check

if __name__ == '__main__':
    test_floatliteral_special_values()
    print("ok")
