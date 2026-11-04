from mojo.middle import types


def test_callable_ctype_str_return():
    c = types.callable_ctype([], 'char *')
    assert c == 'std::function<char *()>', c


def test_callable_ctype_ptr_return():
    c = types.callable_ctype([], 'MojoList *')
    assert c == 'std::function<MojoList *()>', c


def test_callable_ctype_str_ptr_params():
    c = types.callable_ctype(['char *', 'MojoList *'], 'char *')
    assert c == 'std::function<char *(char *, MojoList *)>', c
