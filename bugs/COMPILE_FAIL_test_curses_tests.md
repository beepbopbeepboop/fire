# COMPILE_FAIL: Lib/test/curses_tests.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Error building: 'GimpleGen' object has no attribute '_lower_percent'
Traceback (most recent call last):
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo.py", line 269, in build_executable
    c_code = gimple_codegen.compile_to_gimple_cached(src, do_imports=True, filename=input_file)
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 16737, in compile_to_gimple_cached
    return cas.get_or_build_text(
           ~~~~~~~~~~~~~~~~~~~~~^
        key, '.ci',
        ^^^^^^^^^^^
        lambda: compile_to_gimple(mojo_src, do_imports, filename),
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        _compile_cache)
        ^^^^^^^^^^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/cas.py", line 371, in get_or_build_text
    text = build_fn()
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 16739, in <lambda>
    lambda: compile_to_gimple(mojo_src, do_imports, filename),
            ~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 16761, in compile_to_gimple
    return gen.gen_module(stmts)
           ~~~~~~~~~~~~~~^^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 15004, in gen_module
    func_parts.append(self.gen_func(stmt))
                      ~~~~~~~~~~~~~^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 12724, in gen_func
    self.gen_stmt(stmt)
    ~~~~~~~~~~~~~^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 9934, in gen_stmt
    getattr(self, handler_name)(node)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 10885, in _gen_stmt_ExprStmt
    self.lower_expr(node.value)
    ~~~~~~~~~~~~~~~^^^^^^^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 4570, in lower_expr
    return getattr(self, handler_name)(node)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 7886, in _lower_call
    return self._lower_method_call(node)
           ~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 6657, in _lower_method_call
    for ea in node.args[1:]: self.lower_expr(ea)
                             ~~~~~~~~~~~~~~~^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 4570, in lower_expr
    return getattr(self, handler_name)(node)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 5460, in _lower_binary
    return self._lower_percent(node)
           ^^^^^^^^^^^^^^^^^^^
AttributeError: 'GimpleGen' object has no attribute '_lower_percent'
```

Exit code: 1
Elapsed: 0.39s
