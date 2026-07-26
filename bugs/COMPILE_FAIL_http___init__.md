# COMPILE_FAIL: Lib/http/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:109:11: warning: unused variable '_tag' [-Wunused-variable]
  109 |         'Proxy Authentication Required',
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:114:11: warning: unused variable '_tag' [-Wunused-variable]
  114 |     GONE = (410, 'Gone',
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:119:11: warning: unused variable '_tag' [-Wunused-variable]
  119 |         'Precondition in headers is false')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:134:11: warning: unused variable '_tag' [-Wunused-variable]
  134 |         'Server refuses to brew coffee because it is a teapot')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:143:13: warning: unused variable '_tag' [-Wunused-variable]
  143 |     TOO_EARLY = (425, 'Too Early',
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py: In function 'HTTPStatus___new__':
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:231:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:229:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:228:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:227:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:226:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:225:10: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:224:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:223:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:222:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:221:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:220:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:219:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:218:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:217:11: warning: variable 'obj' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:216:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:215:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py: In function 'HTTPStatus_is_informational':
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:42:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   42 |     def is_redirection(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:40:9: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   40 | 
      |         ^  
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:39:7: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   39 |         return 200 <= self <= 299
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/http/__init__.py:38:9: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   38 |     def is_success(self):
... (167 more lines)
```

Exit code: 1
Elapsed: 9.65s
