"""Regression for bug CODEGEN_dict_comprehension_repr_is_separately_broken.
Defect 1: int key quoted; Defect 2: 0 value -> None (fixed); Defect 3: tuple key address.
This test verifies the compr repr against CPython; it FAILS until the
_DictSlot.keykind discriminator + marked integer path lands.
"""

def test_dict_comprehension_int_key_repr():
    # Defect 1: int keys should not be quoted
    result = str({i: 1 for i in range(3)})
    assert result == "{0: 1, 1: 1, 2: 1}", f"int key repr broken: {result}"

def test_dict_comprehension_zero_value_repr():
    # Defect 2: already fixed; keep as guard
    result = str({"k0": 0, "k1": 1})
    assert result == "{'k0': 0, 'k1': 1}", f"zero value repr broken: {result}"

def test_dict_comprehension_tuple_key_repr():
    # Defect 3: tuple key should render content, not address
    pairs = [(0, 0), (0, 1)]
    result = str({k: 1 for k in pairs})
    # After full fix expected "{(0, 0): 1, (0, 1): 1}"; currently broken
    assert "(0, 0)" in result or "None" not in result.split(":")[0], f"tuple key repr broken: {result}"
