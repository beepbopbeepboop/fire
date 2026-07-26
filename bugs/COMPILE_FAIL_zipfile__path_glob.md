# COMPILE_FAIL: Lib/zipfile/_path/glob.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:32:11: warning: unused variable '_tag' [-Wunused-variable]
   32 |     def extend(self, pattern):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:37:11: warning: unused variable '_tag' [-Wunused-variable]
   37 |         matches newlines (valid on Unix).
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:42:11: warning: unused variable '_tag' [-Wunused-variable]
   42 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:57:11: warning: unused variable '_tag' [-Wunused-variable]
   57 |         '[^/]*\\.txt'
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:66:13: warning: unused variable '_tag' [-Wunused-variable]
   66 |     def replace(self, match):
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py: In function 'Translator___init__':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:24:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   24 |         self.seps = seps
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:24:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   24 |         self.seps = seps
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:24:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   24 |         self.seps = seps
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:24:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   24 |         self.seps = seps
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:24:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   24 |         self.seps = seps
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:178:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:176:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:175:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:174:9: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:173:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:172:13: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:171:13: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:170:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:169:9: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:168:7: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py: In function 'Translator_translate':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/_path/glob.py:38:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   38 | 
... (275 more lines)
```

Exit code: 1
Elapsed: 13.18s
