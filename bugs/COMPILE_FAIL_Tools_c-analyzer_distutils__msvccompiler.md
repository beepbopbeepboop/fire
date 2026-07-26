# COMPILE_FAIL: Tools/c-analyzer/distutils/_msvccompiler.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py:54:11: warning: unused variable '_tag' [-Wunused-variable]
   54 | def _find_vc2017():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py:59:11: warning: unused variable '_tag' [-Wunused-variable]
   59 |     result. It may be ignored when the path is not None.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py:64:11: warning: unused variable '_tag' [-Wunused-variable]
   64 |     root = os.environ.get("ProgramFiles(x86)") or os.environ.get("ProgramFiles")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py:79:11: warning: unused variable '_tag' [-Wunused-variable]
   79 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py:88:13: warning: unused variable '_tag' [-Wunused-variable]
   88 |     'x86_amd64' : 'x64',
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py: In function '_find_vc2015':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py:230:11: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py:229:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py:223:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py:220:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py:209:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py:207:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py:203:10: warning: unused variable '_t6' [-Wunused-variable]
  203 |         self.initialized = False
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py: In function '_find_vc2017':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py:93:11: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
   93 | def _find_vcvarsall(plat_spec):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py:78:10: warning: unused variable '_t21' [-Wunused-variable]
   78 |         return None, None
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py:57:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   57 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py: In function '_find_vcvarsall_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py:130:11: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
  130 |                 .format(exc.cmd))
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py:127:11: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
  127 |     except subprocess.CalledProcessError as exc:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/_msvccompiler.py:121:7: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
  121 | 
... (126 more lines)
```

Exit code: 1
Elapsed: 13.61s
