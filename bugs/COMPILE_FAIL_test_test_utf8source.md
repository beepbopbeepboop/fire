# COMPILE_FAIL: Lib/test/test_utf8source.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8source.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Error building: 'utf-8' codec can't decode byte 0xf6 in position 8: invalid start byte
Traceback (most recent call last):
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/mojo.py", line 269, in build_executable
    c_code = gimple_codegen.compile_to_gimple_cached(src, do_imports=True, filename=input_file)
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 17026, in compile_to_gimple_cached
    deps_digest=_dep_sources_digest(mojo_src, filename))
                ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 17003, in _dep_sources_digest
    _scan(mojo_src, os.path.dirname(os.path.abspath(filename)) if filename else '')
    ~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/mrs/net/chatgpt/claude/mojo-reference/gimple_codegen.py", line 16997, in _scan
    text = f.read()
  File "<frozen codecs>", line 325, in decode
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xf6 in position 8: invalid start byte
```

Exit code: 1
Elapsed: 13.85s
