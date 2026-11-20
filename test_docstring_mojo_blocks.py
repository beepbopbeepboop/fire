import fire_compiler as F

from mojo.middle.docstring_blocks import (
    DocstringCodeBlock,
    extract_module_docstring_mojo_blocks,
    extract_mojo_code_blocks_from_string_literal,
)


def test_extracts_mojo_block_from_module_docstring_with_positions():
    src = (
        '"""Module doc.\n'
        "\n"
        "Example:\n"
        "```mojo\n"
        "import x\n"
        "print(1)\n"
        "```\n"
        '"""\n'
        "\n"
        "var y = 1\n"
    )
    stmts = F.Parser(F.py_tokenize(src)).parse_module()
    blocks = extract_module_docstring_mojo_blocks(stmts, source=src)
    assert len(blocks) == 1
    b = blocks[0]
    assert isinstance(b, DocstringCodeBlock)
    assert b.language == "mojo"
    assert b.code == "import x\nprint(1)\n"
    # Opening fence is the ```mojo line in the source file.
    assert b.fence_line == 4
    assert b.fence_col == 1
    # Code content starts on the line after the fence.
    assert b.line == 5
    assert b.col == 1
    assert b.end_fence_line == 7


def test_untagged_fenced_block_is_extracted():
    src = '"""\n```\nfrom m import f\n```\n"""\n'
    stmts = F.Parser(F.py_tokenize(src)).parse_module()
    blocks = extract_module_docstring_mojo_blocks(stmts, source=src)
    assert len(blocks) == 1
    assert blocks[0].language is None
    assert blocks[0].code == "from m import f\n"


def test_non_mojo_tagged_block_is_not_extracted():
    src = '"""\n```python\nprint(1)\n```\n"""\n'
    stmts = F.Parser(F.py_tokenize(src)).parse_module()
    blocks = extract_module_docstring_mojo_blocks(stmts, source=src)
    assert blocks == []


def test_no_module_docstring_yields_no_blocks():
    src = "var x = 1\n"
    stmts = F.Parser(F.py_tokenize(src)).parse_module()
    assert extract_module_docstring_mojo_blocks(stmts, source=src) == []


def test_extraction_does_not_affect_parsing():
    src = '"""\n```mojo\nfn main(): pass\n```\n"""\nfn main():\n    pass\n'
    stmts = F.Parser(F.py_tokenize(src)).parse_module()
    blocks = extract_module_docstring_mojo_blocks(stmts, source=src)
    assert len(blocks) == 1
    assert blocks[0].code == "fn main(): pass\n"
    # Module still parses normally (docstring + function).
    assert len(stmts) == 2
    assert isinstance(stmts[0], F.ExprStmt)
    assert isinstance(stmts[1], F.FunctionDef)
    assert stmts[1].name == "main"


def test_extract_from_string_literal_directly():
    src = '"""```mojo\nlet a = 1\n```"""\n'
    stmts = F.Parser(F.py_tokenize(src)).parse_module()
    lit = stmts[0].value
    blocks = extract_mojo_code_blocks_from_string_literal(lit, source=src)
    assert len(blocks) == 1
    assert blocks[0].code == "let a = 1\n"
    assert blocks[0].language == "mojo"


if __name__ == '__main__':
    # Registered as a `cmd` job whose command is `python3 <this file>`, so with
    # no `__main__` the interpreter ran only the top level (imports + defs) and
    # exited 0 -- none of the `test_*` functions below ever ran. Same no-op
    # class as the no-op registered-job class. Every function
    # here is fixture-free, so they can be run directly.
    import traceback

    _cases = [(n, f) for n, f in sorted(globals().items())
              if n.startswith('test') and callable(f)]
    _failed = 0
    for _n, _f in _cases:
        try:
            _f()
        except Exception:
            traceback.print_exc()
            print('FAIL ' + _n)
            _failed += 1
        else:
            print('PASS ' + _n)
    if _failed:
        raise SystemExit('%d failure(s) of %d' % (_failed, len(_cases)))
    print('%d passed, 0 failed' % len(_cases))
