# COMPILE_FAIL: Lib/idlelib/pyparse.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py:81:11: warning: unused variable '_tag' [-Wunused-variable]
   81 | _closere = re.compile(r"""
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py:86:11: warning: unused variable '_tag' [-Wunused-variable]
   86 |     |   raise
      |           ^~~ 
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py:91:11: warning: unused variable '_tag' [-Wunused-variable]
   91 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py:106:11: warning: unused variable '_tag' [-Wunused-variable]
  106 |     Anything not specifically mapped otherwise becomes 'x'.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py:115:13: warning: unused variable '_tag' [-Wunused-variable]
  115 |         return 120  # ord('x')
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py: In function 'ParseMap___missing__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py:238:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  238 |             if ch == '\n':
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py:236:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  236 |                 continue
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py: In function 'Parser___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py:123:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  123 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py:121:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  121 | trans.update((ord(c), ord(')')) for c in ")}]")  # close brackets => ')'.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py:120:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  120 | trans.update((ord(c), ord('(')) for c in "({[")  # open brackets => '(';
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py: In function 'Parser_set_code':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py:133:1: warning: label 'bb_6' defined but not used [-Wunused-label]
  133 |         self.code = s
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py:133:1: warning: label 'bb_7' defined but not used [-Wunused-label]
  133 |         self.code = s
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py:133:1: warning: label 'bb_5' defined but not used [-Wunused-label]
  133 |         self.code = s
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyparse.py:133:1: warning: label 'bb_4' defined but not used [-Wunused-label]
  133 |         self.code = s
... (3384 more lines)
```

Exit code: 1
Elapsed: 10.28s
