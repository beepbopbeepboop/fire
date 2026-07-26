# COMPILE_FAIL: Lib/idlelib/outwin.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py: In function '_alloc_OutputWindow':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py:54:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   54 |     except TypeError:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py: In function 'compile_progs':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py:256:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py:246:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py: In function 'file_line_helper_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py:60:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   60 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py:42:10: warning: unused variable '_t12' [-Wunused-variable]
   42 |         if match:
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py:35:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   35 |     a tuple of the file name and line number.  If it doesn't match
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py:31:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   31 |     """Extract file name and line number from line of text.
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py: In function 'OutputWindow___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py:79:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   79 |         EditorWindow.__init__(self, *args)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py:77:7: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   77 | 
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py:76:7: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   76 |     allow_code_context = False
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py:75:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   75 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py:74:10: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   74 |     ]
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py:73:7: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   73 |         ("Go to file/line", "<<goto-file-line>>", None),
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py:72:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   72 |         (None, None, None),
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py:71:7: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   71 |         ("Paste", "<<paste>>", "rmenu_check_paste"),
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py:70:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   70 |         ("Copy", "<<copy>>", "rmenu_check_copy"),
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/outwin.py:69:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
... (471 more lines)
```

Exit code: 1
Elapsed: 10.89s
