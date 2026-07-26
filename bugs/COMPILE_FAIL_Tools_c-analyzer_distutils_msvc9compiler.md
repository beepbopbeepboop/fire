# COMPILE_FAIL: Tools/c-analyzer/distutils/msvc9compiler.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py:91:11: warning: unused variable '_tag' [-Wunused-variable]
   91 |         """
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py:96:11: warning: unused variable '_tag' [-Wunused-variable]
   96 |         d = {}
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py:101:11: warning: unused variable '_tag' [-Wunused-variable]
  101 |             except RegError:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py:116:11: warning: unused variable '_tag' [-Wunused-variable]
  116 |         return s
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py:125:13: warning: unused variable '_tag' [-Wunused-variable]
  125 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py: In function 'Reg_get_value':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py:71:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   71 |         try:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py:68:1: warning: label 'bb_11' defined but not used [-Wunused-label]
   68 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py:84:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   84 |         return L
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py:79:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   79 |                 k = RegEnumKey(handle, i)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py:68:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   68 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py:72:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   72 |             handle = RegOpenKeyEx(base, key)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py:77:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   77 |         while True:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py:73:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   73 |         except RegError:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py:69:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   69 |     def read_keys(cls, base, key):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/msvc9compiler.py:328:1: warning: label 'bb_2' defined but not used [-Wunused-label]
... (1825 more lines)
```

Exit code: 1
Elapsed: 14.27s
