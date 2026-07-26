# COMPILE_FAIL: Lib/zipfile/_path/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:93:11: warning: unused variable '_tag' [-Wunused-variable]
   93 |     def __getstate__(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:98:11: warning: unused variable '_tag' [-Wunused-variable]
   98 |         super().__init__(*args, **kwargs)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:103:11: warning: unused variable '_tag' [-Wunused-variable]
  103 |     A ZipFile subclass that ensures that implied directories
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:118:11: warning: unused variable '_tag' [-Wunused-variable]
  118 |     def namelist(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:127:13: warning: unused variable '_tag' [-Wunused-variable]
  127 |         If the name represents a directory, return that name
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py: In function '_parents_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:290:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  290 |     ...
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:287:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  287 |     >>> zf.filename = None
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py: In function '_ancestry_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:89:11: warning: variable 'tail' set but not used [-Wunused-but-set-variable]
   89 |         self.__args = args
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:75:11: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
   75 | def _difference(minuend, subtrahend):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:70:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
   70 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:66:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
   66 |     while path.rstrip(posixpath.sep):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:56:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   56 |     ['b']
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:52:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   52 |     ['/b/d', '/b']
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/__init__.py:46:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   46 |     Given a path with elements separated by
      |          ^~~
... (2270 more lines)
```

Exit code: 1
Elapsed: 13.28s
