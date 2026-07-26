# COMPILE_FAIL: Lib/test/test_warnings/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py:1123:11: warning: unused variable '_tag' [-Wunused-variable]
 1123 |             wmod.filterwarnings('default', category=UserWarning)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py:1128:11: warning: unused variable '_tag' [-Wunused-variable]
 1128 |                     'foo', UserWarning, 'bar', 1,
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py:1133:11: warning: unused variable '_tag' [-Wunused-variable]
 1133 |             linecache.clearcache()
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py:1148:11: warning: unused variable '_tag' [-Wunused-variable]
 1148 |         wmod = self.module
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py:1157:13: warning: unused variable '_tag' [-Wunused-variable]
 1157 |         # warn_explicit() shouldn't cause an assertion failure in case of a
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py: In function 'warnings_state_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py:60:1: warning: label 'bb_25' defined but not used [-Wunused-label]
   60 |         warning_tests.warnings = original_warnings
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py:2050:11: warning: variable '_t102' set but not used [-Wunused-but-set-variable]
 2050 |             pass
      |           ^ ~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py:2049:11: warning: variable '_t101' set but not used [-Wunused-but-set-variable]
 2049 |         def b():
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py:2038:11: warning: variable '_t90' set but not used [-Wunused-but-set-variable]
 2038 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py:2033:11: warning: variable '_t85' set but not used [-Wunused-but-set-variable]
 2033 |         class Base:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py:2030:11: warning: variable '_t82' set but not used [-Wunused-but-set-variable]
 2030 |         init_subclass_saw = None
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py:2027:10: warning: unused variable '_t79' [-Wunused-variable]
 2027 |         self.assertIs(init_subclass_saw, C)
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py:2009:11: warning: variable 'context' set but not used [-Wunused-but-set-variable]
 2009 |                 pass
      |           ^     ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py:2006:11: warning: variable '_t60' set but not used [-Wunused-but-set-variable]
 2006 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_warnings/__init__.py:2002:11: warning: variable '_t57' set but not used [-Wunused-but-set-variable]
... (50370 more lines)
```

Exit code: 1
Elapsed: 14.97s
