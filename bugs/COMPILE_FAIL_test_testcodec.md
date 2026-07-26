# COMPILE_FAIL: Lib/test/testcodec.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py: In function '_alloc_Codec':
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:42:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   42 | })
      | ^~  
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:56:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:61:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:66:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:81:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:90:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py: In function 'Codec_encode':
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:161:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:159:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:158:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:157:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:156:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py: In function 'Codec_decode':
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:26:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   26 |     pass
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:24:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   24 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:23:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   23 |     pass
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:22:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   22 | class StreamWriter(Codec,codecs.StreamWriter):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:21:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   21 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py: In function 'StreamWriter_encode':
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:30:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   30 | def getregentry():
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:28:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   28 | ### encodings module API
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:27:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   27 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/testcodec.py:26:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   26 |     pass
      |           ^  
... (94 more lines)
```

Exit code: 1
Elapsed: 13.76s
