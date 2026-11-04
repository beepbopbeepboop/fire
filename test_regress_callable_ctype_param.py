"""Regression for PLAN_summarize-stats step 4: `types.callable_ctype` builds
parameterized `std::function<R(P...)>` slot signatures. Covers both the
bare-ctype-string form and the `(name, ctype)` pair form, for pointer and
plain returns.
"""
from mojo.middle import types


def test_callable_ctype_parameterized():
    # parameterized std::function slots
    ct = types.callable_ctype(['int64_t', 'char *'], 'int64_t')
    assert ct == 'std::function<int64_t(int64_t, char *)>'
    ct2 = types.callable_ctype([], 'char *')
    assert ct2 == 'std::function<char *()>'
    ct3 = types.callable_ctype([('x', 'MojoList *')], 'MojoDict *')
    assert ct3 == 'std::function<MojoDict *(MojoList *)>'


def test_callable_ctype_str_return():
    c = types.callable_ctype([], 'char *')
    assert c == 'std::function<char *()>', c


def test_callable_ctype_ptr_return():
    c = types.callable_ctype([], 'MojoList *')
    assert c == 'std::function<MojoList *()>', c


def test_callable_ctype_str_ptr_params():
    c = types.callable_ctype(['char *', 'MojoList *'], 'char *')
    assert c == 'std::function<char *(char *, MojoList *)>', c
