# COMPILE_FAIL: Lib/test/test_ucn.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:62:11: warning: unused variable '_tag' [-Wunused-variable]
   62 |         ]
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:67:11: warning: unused variable '_tag' [-Wunused-variable]
   67 |             string
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:72:11: warning: unused variable '_tag' [-Wunused-variable]
   72 |             name = "LATIN SMALL LETTER %s" % char.upper()
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:87:11: warning: unused variable '_tag' [-Wunused-variable]
   87 |         self.checkletter("HANGUL SYLLABLE PAN", "\ud310")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:96:13: warning: unused variable '_tag' [-Wunused-variable]
   96 |     def test_cjk_unified_ideographs(self):
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py: In function 'UnicodeNamesTest_checkletter':
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:358:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:356:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:355:11: warning: variable 'res' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:354:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:353:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:352:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:351:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:350:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:349:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:348:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:347:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:346:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:345:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:344:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py: In function 'UnicodeNamesTest_test_general':
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:78:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   78 |         self.checkletter("HANGUL SYLLABLE GGWEOSS", "\uafe8")
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:76:11: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
   76 |     def test_hangul_syllables(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:75:10: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
   75 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:74:10: warning: variable '_t37' set but not used [-Wunused-but-set-variable]
   74 |             self.assertEqual(unicodedata.name(code), name)
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_ucn.py:73:10: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
... (2534 more lines)
```

Exit code: 1
Elapsed: 15.22s
