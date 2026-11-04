from mojo.middle import types


def test_callable_ctype_parameterized():
    # parameterized std::function slots
    ct = types.callable_ctype(['int64_t', 'char *'], 'int64_t')
    assert ct == 'std::function<int64_t(int64_t, char *)>'
    ct2 = types.callable_ctype([], 'char *')
    assert ct2 == 'std::function<char *()>'
    ct3 = types.callable_ctype([('x', 'MojoList *')], 'MojoDict *')
    assert ct3 == 'std::function<MojoDict *(MojoList *)>'
