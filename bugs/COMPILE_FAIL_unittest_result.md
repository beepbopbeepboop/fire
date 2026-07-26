# COMPILE_FAIL: Lib/unittest/result.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:91:11: warning: unused variable '_tag' [-Wunused-variable]
   91 |                         output += '\n'
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:96:11: warning: unused variable '_tag' [-Wunused-variable]
   96 |                     self._original_stderr.write(STDERR_LINE % error)
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:101:11: warning: unused variable '_tag' [-Wunused-variable]
  101 |             self._stdout_buffer.truncate()
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:116:11: warning: unused variable '_tag' [-Wunused-variable]
  116 |         self.errors.append((test, self._exc_info_to_string(err, test)))
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:125:13: warning: unused variable '_tag' [-Wunused-variable]
  125 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py: In function '_alloc_failfast_inner_env':
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:283:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py: In function 'failfast_inner':
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:19:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   19 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:316:1: warning: label 'bb_3' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:306:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:304:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:303:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:302:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:301:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:300:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:299:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:298:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:297:9: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:296:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:295:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:294:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:293:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:292:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:291:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py: In function 'TestResult___init__':
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:54:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   54 |         self._mirrorOutput = False
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/result.py:52:9: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
   52 |         self._original_stdout = sys.stdout
      |         ^~~~
... (1357 more lines)
```

Exit code: 1
Elapsed: 14.51s
