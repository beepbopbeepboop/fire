"""Regression for PARSER_backtick_string_literals: backtick-quoted module names."""
from fire_compiler import Parser, py_tokenize


def test_from_import_backtick_dotted():
    src = "from `foo.bar` import x\n"
    tree = Parser(py_tokenize(src)).parse_module()
    assert tree[0].module == "`foo.bar`"


def test_import_backtick_dotted():
    src = "import `foo.bar`\n"
    tree = Parser(py_tokenize(src)).parse_module()
    assert tree[0].module == "`foo.bar`"


if __name__ == "__main__":
    test_from_import_backtick_dotted()
    test_import_backtick_dotted()
    print("ok")
