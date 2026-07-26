# COMPILE_FAIL: Lib/re/_constants.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py: In function '_alloc__NamedIntConstant':
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:98:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   98 |     'RANGE',
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py: In function 'PatternError___init__':
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:55:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   55 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:53:1: warning: label 'bb_13' defined but not used [-Wunused-label]
   53 |         super().__init__(msg)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:54:1: warning: label 'bb_12' defined but not used [-Wunused-label]
   54 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:49:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   49 |             if newline in pattern:
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:47:1: warning: label 'bb_11' defined but not used [-Wunused-label]
   47 |             self.lineno = pattern.count(newline, 0, pos) + 1
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:51:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   51 |         else:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:56:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   56 | # Backward compatibility after renaming in 3.13
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:60:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   60 |     def __new__(cls, value, name):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:57:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   57 | error = PatternError
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:46:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   46 |                 newline = b'\n'
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:50:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   50 |                 msg = '%s (line %d, column %d)' % (msg, self.lineno, self.colno)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:369:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:367:11: warning: variable '_t59' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:366:11: warning: variable '_t58' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:365:11: warning: variable '_t57' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:364:7: warning: variable '_t56' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:363:7: warning: variable '_t55' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:362:11: warning: variable '_t54' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:361:10: warning: variable '_t53' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:360:10: warning: variable '_t52' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:359:11: warning: variable '_t51' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/re/_constants.py:358:11: warning: variable '_t50' set but not used [-Wunused-but-set-variable]
... (147 more lines)
```

Exit code: 1
Elapsed: 11.05s
