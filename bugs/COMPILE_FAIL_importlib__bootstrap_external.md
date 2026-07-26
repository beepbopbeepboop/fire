# COMPILE_FAIL: Lib/importlib/_bootstrap_external.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py: In function '_alloc_SourceFileLoader':
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py:236:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  236 | # Deprecated.
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py: In function '_alloc_SourcelessFileLoader':
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py:250:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  250 |     The debug_override parameter is deprecated. If debug_override is not None,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py: In function '_alloc__NamespacePath':
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py:264:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  264 |     path = _os.fspath(path)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py: In function '_make_relax_case__relax_case':
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py:923:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  923 |     def __eq__(self, other):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py:921:9: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  921 |         self.path = path
      |         ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py:920:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  920 |         self.name = fullname
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py: In function '_make_relax_case':
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py:107:10: warning: variable 'key' set but not used [-Wunused-but-set-variable]
  107 |         root = ""
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py:98:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
   98 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py:84:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   84 | def _unpack_uint64(data):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py: In function '_pack_uint32_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py:86:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   86 |     assert len(data) == 8
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py:85:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   85 |     """Convert 8 bytes in little-endian to an integer."""
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py:79:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   79 | def _pack_uint32(x):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py: In function '_unpack_uint64_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py:92:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   92 |     return int.from_bytes(data, 'little')
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py:86:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   86 |     assert len(data) == 8
      |          ^~~
... (7565 more lines)
```

Exit code: 1
Elapsed: 10.68s
