# COMPILE_FAIL: Lib/unittest/main.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py:76:11: warning: unused variable '_tag' [-Wunused-variable]
   76 |             self.module = module
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py:81:11: warning: unused variable '_tag' [-Wunused-variable]
   81 |         self.failfast = failfast
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py:86:11: warning: unused variable '_tag' [-Wunused-variable]
   86 |         self.durations = durations
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py:101:11: warning: unused variable '_tag' [-Wunused-variable]
  101 |         self.testLoader = testLoader
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py:110:13: warning: unused variable '_tag' [-Wunused-variable]
  110 |             self._discovery_parser.print_help()
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py: In function '_convert_name_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py:311:10: warning: variable '_t80' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py:309:10: warning: variable '_t78' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py:299:10: warning: variable '_t68' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py:297:10: warning: variable '_t66' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py:290:7: warning: variable '_t59' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py:287:7: warning: variable '_t56' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py:275:11: warning: variable '_t44' set but not used [-Wunused-but-set-variable]
  275 |                 sys.exit(_NO_TESTS_EXITCODE)
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py:263:7: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
  263 |                                                  warnings=self.warnings)
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py:259:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
  259 |                     # didn't accept the tb_locals or durations argument
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py:256:7: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
  256 |                                                  tb_locals=self.tb_locals,
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py:249:7: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
  249 |         if isinstance(self.testRunner, type):
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py:243:10: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  243 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py:232:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  232 |         self.start = '.'
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/unittest/main.py: In function '_convert_select_pattern_0c85c9':
... (1742 more lines)
```

Exit code: 1
Elapsed: 14.39s
