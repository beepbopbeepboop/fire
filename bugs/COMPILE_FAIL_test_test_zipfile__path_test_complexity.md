# COMPILE_FAIL: Lib/test/test_zipfile/_path/test_complexity.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:63:11: warning: unused variable '_tag' [-Wunused-variable]
   63 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:68:11: warning: unused variable '_tag' [-Wunused-variable]
   68 |     def test_baseline_regex_complexity(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:73:11: warning: unused variable '_tag' [-Wunused-variable]
   73 |             min_n=1,
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:88:11: warning: unused variable '_tag' [-Wunused-variable]
   88 |     def test_glob_width(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:97:13: warning: unused variable '_tag' [-Wunused-variable]
   97 |     @pytest.mark.flaky
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py: In function 'TestComplexity_test_implied_dirs_performance':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:29:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   29 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:29:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   29 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:220:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:218:9: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:217:10: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:216:11: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:215:10: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:214:10: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:213:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:212:10: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:211:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:210:11: warning: variable 'others' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:209:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:208:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:207:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:206:11: warning: variable 'best' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:205:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:204:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:203:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:202:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:201:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:200:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:199:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_complexity.py:198:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
... (535 more lines)
```

Exit code: 1
Elapsed: 13.48s
