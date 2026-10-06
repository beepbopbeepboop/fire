"""Helper module for test_import_integration.py's real compile+link+run
check: double_value/triple_value, distinct from test_helper.mojo's
double/add so the two import tests' resolved modules don't collide."""

def double_value(x: Int) -> Int:
    return x * 2

def triple_value(x: Int) -> Int:
    return x * 3
