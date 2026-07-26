# COMPILE_FAIL: CC ERROR: lvalue required as left operand of assignment

**5 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/stat.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/stat.py:173:11: warning: unused variable '_tag' [-Wunused-variable]
  173 |             else:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/stat.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/stat.py:178:11: warning: unused variable '_tag' [-Wunused-variable]
  178 |             if index == 0:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/stat.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/stat.py:183:11: warning: unused variable '_tag' [-Wunused-variable]
  183 |     return "".join(perm)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/stat.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/stat.py:198:11: warning: unused variable '_tag' [-Wunused-variable]
  198 | FILE_ATTRIBUTE_NO_SCRUB_DATA = 131072
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/stat.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/stat.py:207:13: warning: unused variable '_tag' [-Wunused-variable]
  207 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/stat.py: In function 'S_IMODE_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/stat.py:329:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/stat.py: In function 'S_IFMT_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/stat.py:30:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   30 |     """
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/stat.py: In function 'S_ISDIR_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/stat.py:36:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   36 | S_IFDIR  = 0o040000  # directory
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/stat.py: In function 'S_ISCHR_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/stat.py:57:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   57 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/stat.py: In function 'S_ISBLK_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/stat.py:61:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   61 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/stat.py: In function 'S_ISREG_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/stat.py:65:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   65 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/stat.py: In function 'S_ISFIFO_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/stat.py:69:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   69 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/stat.py: In function 'S_ISLNK_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/stat.py:73:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   73 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/stat.py: In function 'S_ISSOCK_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/stat.py:77:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   77 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/stat.py: In function 'S_ISDOOR_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/stat.py:81:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   81 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/stat.py: In function 'S_ISPORT_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/stat.py:85:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   85 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/stat.py: In function 'S_ISWHT_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/stat.py:89:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   89 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/stat.py: In function 'filemode_0c85c9':
/Users/mrs/net/Python-3.14
```

## Affected files

- `Lib/stat.py`
- `Lib/test/libregrtest/setup.py`
- `Lib/test/test_importlib/test_threaded_import.py`
- `Lib/test/test_tracemalloc.py`
- `Tools/peg_generator/pegen/testutil.py`
