# COMPILE_FAIL: Lib/test/test_zipfile64.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:67:11: warning: unused variable '_tag' [-Wunused-variable]
   67 |             self.assertIsNone(zipfp.testzip())
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:72:11: warning: unused variable '_tag' [-Wunused-variable]
   72 |         with TemporaryFile() as f:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:77:11: warning: unused variable '_tag' [-Wunused-variable]
   77 |     @requires_zlib()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:92:11: warning: unused variable '_tag' [-Wunused-variable]
   92 |         # This test checks that more than 64k files can be added to an archive,
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:101:13: warning: unused variable '_tag' [-Wunused-variable]
  101 |         with zipfile.ZipFile(TESTFN, mode="r") as zipf2:
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py: In function 'TestsWithSourceFile_setUp':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:33:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   33 |         self.data = '\n'.join(line_gen).encode('ascii')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:33:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   33 |         self.data = '\n'.join(line_gen).encode('ascii')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:33:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   33 |         self.data = '\n'.join(line_gen).encode('ascii')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:33:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   33 |         self.data = '\n'.join(line_gen).encode('ascii')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:204:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:202:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:201:10: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:200:7: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:199:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:198:10: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:197:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:196:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:195:14: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:194:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:193:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:192:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:191:11: warning: variable 'line_gen' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:190:7: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:189:9: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile64.py:188:11: warning: variable 'i' set but not used [-Wunused-but-set-variable]
... (1078 more lines)
```

Exit code: 1
Elapsed: 13.19s
