# COMPILE_FAIL: Error building: invalid literal for int() with base N: 'X'

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Error building: invalid literal for int() with base 0: '407__'
Traceback (most recent call last):
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo.py", line 269, in build_executable
    c_code = gimple_codegen.compile_to_gimple_cached(src, do_imports=True, filename=input_file)
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 16383, in compile_to_gimple_cached
    return cas.get_or_build_text(
           ~~~~~~~~~~~~~~~~~~~~~^
        key, '.ci',
        ^^^^^^^^^^^
        lambda: compile_to_gimple(mojo_src, do_imports, filename),
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        _compile_cache)
        ^^^^^^^^^^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/cas.py", line 364, in get_or_build_text
    text = build_fn()
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 16385, in <lambda>
    lambda: compile_to_gimple(mojo_src, do_imports, filename),
            ~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 16401, in compile_to_gimple
    stmts  = ast_rewriter.rewrite(Parser(tokens).with_filename(filename).parse_module())
                                  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo_compiler.py", line 1072, in parse_module
    stmts.append(self._parse_stmt())
                 ~~~~~~~~~~~~~~~~^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo_compiler.py", line 1153, in _parse_stmt
    if t.value in ("struct", "class"): return self._parse_struct()
                                              ~~~~~~~~~~~~~~~~~~^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo_compiler.py", line 1905, in _parse_struct
    body = self._parse_block()
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo_compiler.py", line 1113, in _parse_block
    stmts.append(self._parse_stmt())
                 ~~~~~~~~~~~~~~~~^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo_compiler.py", line 1152, in _parse_stmt
    self._advance(); return self._parse_funcdef([])
                            ~~~~~~~~~~~~~~~~~~~^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo_compiler.py", line 1852, in _parse_funcdef
    body = self._parse_block()
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo_compiler.py", line 1113, in _parse_block
    stmts.append(self._parse_stmt())
                 ~~~~~~~~~~~~~~~~^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo_compiler.py", line 1157, in _parse_stmt
    if t.value == "with": return self._parse_with()
                                 ~~~~~~~~~~~~~~~~^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo_compiler.py", line 2077, in _parse_with
    return WithStmt(items=items, body=self._parse_block())
                                      ~~~~~~~~~~~~~~~~~^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo_compiler.py", line 1113, in _parse_block
    stmts.append(self._parse_stmt())
                 ~~~~~~~~~~~~~~~~^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo_compiler.py", line 1258, in _parse_stmt
    expr = self._parse_expr(0)
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo_compiler.py", line 2272, in _parse_expr
    left = self._parse_unary()
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo_compiler.py", line 2332, in _parse_unary
    return self._parse_postfix()
           ~~~~~~~~~~~~~~~~~~~^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo_compiler.py", line 2497, in _parse_postfix
    first = self._parse_expr(0)
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo_compiler.py", line 2272, in _parse_expr
    left = self._parse_unary()
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo_compiler.py", line 2332, in _parse_unary
    return self._parse_postfix()
           ~~~~~~~~~~~~~~~~~~~^^
  File "/Users/mrs/net/chatgpt/claude/
```

## Affected files

- `Lib/test/test_string_literals.py`
