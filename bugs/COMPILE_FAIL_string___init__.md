# COMPILE_FAIL: Lib/string/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/string/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-06)

Re-ran; the stale doc's `AttributeError: 'GimpleGen' object has no
attribute '_struct_bases'` CRASH is FIXED (that attribute exists now —
compilation gets much further). Current error:

```
error: request for member 'pattern' in something not a structure or union
error: invalid conversion in gimple call
```

The first is ALREADY a confirmed real-world instance in
`bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md` (`Template.
__init_subclass__`: `pat = cls.pattern = re.compile(...)` — opaque
`cls` class-object parameter). Not re-investigated; see that doc's
implementation plan. The second (`invalid conversion in gimple call`,
`Lib/string/__init__.py:140`/`:162`) not investigated further this
session — same generic shape as the two other still-open "invalid
conversion in gimple call" sites already noted in
`bugs/COMPILE_FAIL_importlib__bootstrap_external.md` (with/branch
return-type unification, not root-caused there either); plausibly
related but not confirmed.

```
Error building: 'GimpleGen' object has no attribute '_struct_bases'
Traceback (most recent call last):
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo.py", line 269, in build_executable
    c_code = gimple_codegen.compile_to_gimple_cached(src, do_imports=True, filename=input_file)
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 16672, in compile_to_gimple_cached
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
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 16674, in <lambda>
    lambda: compile_to_gimple(mojo_src, do_imports, filename),
            ~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 16696, in compile_to_gimple
    return gen.gen_module(stmts)
           ~~~~~~~~~~~~~~^^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 14958, in gen_module
    func_parts.append(self._gen_struct_method(stmt.name, m, overload_id))
                      ~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 13359, in _gen_struct_method
    self.gen_stmt(stmt)
    ~~~~~~~~~~~~~^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 9892, in gen_stmt
    getattr(self, handler_name)(node)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 10843, in _gen_stmt_ExprStmt
    self.lower_expr(node.value)
    ~~~~~~~~~~~~~~~^^^^^^^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 4570, in lower_expr
    return getattr(self, handler_name)(node)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 7822, in _lower_call
    return self._lower_method_call(node)
           ~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 6092, in _lower_method_call
    for b in (self._struct_bases.get(cur_struct) or []) if cur_struct else ():
              ^^^^^^^^^^^^^^^^^^
AttributeError: 'GimpleGen' object has no attribute '_struct_bases'. Did you mean: '_struct_layout'?
```

Exit code: 1
Elapsed: 0.25s
