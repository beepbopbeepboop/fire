# COMPILE_FAIL: Error building: 'X' codec can't decode byte NxfN in position N: invalid start byte

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Error building: 'utf-8' codec can't decode byte 0xf6 in position 8: invalid start byte
Traceback (most recent call last):
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo.py", line 269, in build_executable
    c_code = gimple_codegen.compile_to_gimple_cached(src, do_imports=True, filename=input_file)
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 16382, in compile_to_gimple_cached
    deps_digest=_dep_sources_digest(mojo_src, filename))
                ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 16359, in _dep_sources_digest
    _scan(mojo_src, os.path.dirname(os.path.abspath(filename)) if filename else '')
    ~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 16353, in _scan
    text = f.read()
  File "<frozen codecs>", line 325, in decode
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xf6 in position 8: invalid start byte

```

## Affected files

- `Lib/test/test_utf8source.py`
