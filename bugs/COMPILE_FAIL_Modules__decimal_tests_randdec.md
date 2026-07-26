# COMPILE_FAIL: Modules/_decimal/tests/randdec.py

Source file: `/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randdec.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py: In function 'test_short_halfway_cases':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:211:11: warning: variable '_t121' set but not used [-Wunused-but-set-variable]
  211 |     '00000000000000000000000000000000000000000000000000' #...
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:209:11: warning: variable '_t119' set but not used [-Wunused-but-set-variable]
  209 |     '00000000000000000000000000000000000000000000000000' #...
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:207:11: warning: variable '_t117' set but not used [-Wunused-but-set-variable]
  207 |     # tough cases for ln etc.
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:205:11: warning: variable '_t115' set but not used [-Wunused-but-set-variable]
  205 |     '1',
      |           ^    
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:199:11: warning: variable '_t109' set but not used [-Wunused-but-set-variable]
  199 |     '0000000000000000001',
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:192:11: warning: variable '_t102' set but not used [-Wunused-but-set-variable]
  192 |     '00000000000000000000000001',
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:181:11: warning: variable '_t91' set but not used [-Wunused-but-set-variable]
  181 |     '000000000100000000000000000000000000000000000000000' #...
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:179:11: warning: variable '_t89' set but not used [-Wunused-but-set-variable]
  179 |     '000000000000000000000000000000000000000000000000005',
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:177:11: warning: variable '_t87' set but not used [-Wunused-but-set-variable]
  177 |     '000000000000000000000000000000000000000000000000000' #...
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:175:11: warning: variable '_t85' set but not used [-Wunused-but-set-variable]
  175 |     '000000000000000000000000000000000000000000000000001',
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:169:11: warning: variable '_t79' set but not used [-Wunused-but-set-variable]
  169 |     '000000000000000000000000000000000000000000000000000' #...
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:162:11: warning: variable '_t72' set but not used [-Wunused-but-set-variable]
  162 |     '0.9999999999999999999999999999999999999999999999999' #...
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:161:10: warning: variable 's' set but not used [-Wunused-but-set-variable]
  161 |     '0.99999999900000000025',
      |          ^
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:131:11: warning: variable '_t46' set but not used [-Wunused-but-set-variable]
  131 |             s = random.choice(signs)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:105:11: warning: variable 'upper' set but not used [-Wunused-but-set-variable]
  105 |     # with n
      |           ^~   
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py: In function 'test_halfway_cases':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:141:11: warning: variable '_t57' set but not used [-Wunused-but-set-variable]
  141 |             if random.choice([True, False]):
... (438 more lines)
```

Exit code: 1
Elapsed: 14.09s
