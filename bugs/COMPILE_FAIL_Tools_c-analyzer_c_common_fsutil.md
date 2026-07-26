# COMPILE_FAIL: Tools/c-analyzer/c_common/fsutil.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:63:11: warning: unused variable '_tag' [-Wunused-variable]
   63 |     else:
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:68:11: warning: unused variable '_tag' [-Wunused-variable]
   68 |     return filename
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:73:11: warning: unused variable '_tag' [-Wunused-variable]
   73 |         filenames = (os.path.abspath(v) for v in filenames)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:88:11: warning: unused variable '_tag' [-Wunused-variable]
   88 |         filename = os.path.normpath(filename)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:97:13: warning: unused variable '_tag' [-Wunused-variable]
   97 |         if fixroot:
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py: In function 'create_backup_1ce6ce':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:44:14: error: request for member 'filename' in something not a structure or union
   44 |         return os.path.abspath(filename)
      |              ^~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:322:11: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
  322 | # XXX posix-only?
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:321:11: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
  321 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:319:10: warning: unused variable '_t32' [-Wunused-variable]
  319 | ##################################
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py: In function 'fix_filename_b1ff88':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:47:8: error: assignment to 'int64_t' {aka 'long long int'} from 'char *' makes integer from pointer without a cast [-Wint-conversion]
   47 |     return _fix_filename(filename, relroot)
      |        ^
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:37:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   37 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py: In function '_fix_filename_08338c':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:91:7: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
   91 |         return filename
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:76:7: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
   76 |         filenames = (_fix_filename(v, relroot) for v in filenames)
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:57:7: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   57 |     if filename.startswith(_badprefix):
... (246 more lines)
```

Exit code: 1
Elapsed: 14.67s
