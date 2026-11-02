"""Regression for bug CODEGEN_dict_comprehension_repr_is_separately_broken.
Pinned test: int-key dict comprehension must print unquoted integer keys.
"""

def test_dict_comprehension_int_key_repr():
    result = str({i: 1 for i in range(3)})
    assert result == "{0: 1, 1: 1, 2: 1}", f"int key repr broken: {result}"

def test_dict_comprehension_zero_value_repr():
    result = str({"k0": 0, "k1": 1})
    assert result == "{'k0': 0, 'k1': 1}", f"zero value repr broken: {result}"
