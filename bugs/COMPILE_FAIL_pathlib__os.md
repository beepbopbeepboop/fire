# COMPILE_FAIL: Lib/pathlib/_os.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py:107:11: warning: unused variable '_tag' [-Wunused-variable]
  107 |         Copy from one file to another using CopyFile2 (Windows only).
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py:112:11: warning: unused variable '_tag' [-Wunused-variable]
  112 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py:117:11: warning: unused variable '_tag' [-Wunused-variable]
  117 |     """
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py:132:11: warning: unused variable '_tag' [-Wunused-variable]
  132 |                         raise err
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py:141:13: warning: unused variable '_tag' [-Wunused-variable]
  141 |                         raise err
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py: In function '_get_copy_blocksize_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py:328:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  328 |             try:
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py:326:10: warning: unused variable '_t7' [-Wunused-variable]
  326 |         ignore_errors is true."""
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py:320:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  320 |     def __repr__(self):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py: In function 'copyfileobj_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py:144:14: error: request for member 'errno' in something not a structure or union
  144 |                     _copy_file_range(source_fd, target_fd)
      |              ^ 
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py:153:14: error: request for member 'errno' in something not a structure or union
  153 |                 except OSError as err:
      |              ^ 
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py:160:14: error: request for member 'errno' in something not a structure or union
  160 |             raise err
      |              ^~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py:167:16: error: request for member 'errno' in something not a structure or union
  167 | 
      |                ^ 
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py:158:8: error: request for member 'filename' in something not a structure or union
  158 |             err.filename = source_f.name
      |        ^ 
/Users/mrs/net/Python-3.14.6/Lib/pathlib/_os.py:159:8: error: request for member 'filename2' in something not a structure or union
  159 |             err.filename2 = target_f.name
      |        ^ 
... (2776 more lines)
```

Exit code: 1
Elapsed: 9.78s
