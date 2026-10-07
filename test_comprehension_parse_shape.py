"""Parser-shape pinning test: `Comprehension`'s field names for dict
comprehensions.

`fire_compiler.Comprehension` stores, for a dict comprehension, the KEY
expression in `.element` and the VALUE expression in `.value`. The VALUE
used to be carried in a field literally named `key`, whose comment said
"dict key" — the opposite of its contents — and `formal/model.py`'s arm
that classifies dict comprehensions carried the same inversion in its
comment. The field is now named `value` (and the misleading comments are
gone); this pins the shape so the names cannot silently drift again.
"""
import sys
import fire_compiler as N

_PASS = 0
_FAIL = 0


def _parse(src: str):
    return N.Parser(N.py_tokenize(src)).parse_module()


def check(name: str, cond: bool, detail: str = ""):
    global _PASS, _FAIL
    if cond:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}  {detail}")
        _FAIL += 1


def run_tests():
    mod = _parse("x = {k: 1 for k in d}\n")
    c = mod[0].value
    check("dict_comp_kind", c.kind == "dict", repr(c.kind))
    check("dict_comp_element_is_the_key_expr",
          isinstance(c.element, N.IdentExpr) and c.element.name == "k",
          repr(c.element))
    check("dict_comp_value_is_the_value_expr",
          isinstance(c.value, N.IntLiteral) and c.value.value == 1,
          repr(c.value))

    mod = _parse("x = [k for k in d]\n")
    c = mod[0].value
    check("list_comp_kind", c.kind == "list", repr(c.kind))
    check("list_comp_has_no_value", c.value is None, repr(c.value))

    mod = _parse("x = {k for k in d}\n")
    c = mod[0].value
    check("set_comp_has_no_value", c.value is None, repr(c.value))

    mod = _parse("x = {k: v for k, v in d.items()}\n")
    c = mod[0].value
    check("dict_comp_element_is_key_value_is_value",
          isinstance(c.element, N.IdentExpr) and c.element.name == "k"
          and isinstance(c.value, N.IdentExpr) and c.value.name == "v",
          repr((c.element, c.value)))


if __name__ == "__main__":
    run_tests()
    print(f"{_PASS} passed, {_FAIL} failed")
    sys.exit(1 if _FAIL else 0)
