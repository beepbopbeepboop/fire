# COMPILE_FAIL: Lib/idlelib/hyperparser.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:54:11: warning: unused variable '_tag' [-Wunused-variable]
   54 |             r = text.tag_prevrange("console", index)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:59:11: warning: unused variable '_tag' [-Wunused-variable]
   59 |             stopatindex = "%d.end" % lno
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:64:11: warning: unused variable '_tag' [-Wunused-variable]
   64 |             parser.set_lo(0)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:79:11: warning: unused variable '_tag' [-Wunused-variable]
   79 |         self.set_index(index)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:88:13: warning: unused variable '_tag' [-Wunused-variable]
   88 |         if indexinrawtext < 0:
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py: In function 'HyperParser___init___index2line':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:194:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  194 |                 i -= 1
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:192:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  192 |                 i -= 2
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:191:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  191 |             if i - 2 >= limit and ('a' + str[i - 2:pos]).isidentifier():
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:190:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  190 |                 i -= 4
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:36:1: error: invalid types in conversion to integer
   36 |         lno = index2line(text.index(index))
      | ^
char *
double
_t3 = (char *) _t1;
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py: In function 'HyperParser___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:76:1: warning: label 'bb_14' defined but not used [-Wunused-label]
   76 |                          self.bracketing[i-1][1]
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:76:1: warning: label 'bb_18' defined but not used [-Wunused-label]
   76 |                          self.bracketing[i-1][1]
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:76:1: warning: label 'bb_16' defined but not used [-Wunused-label]
   76 |                          self.bracketing[i-1][1]
      | ^    
... (2166 more lines)
```

Exit code: 1
Elapsed: 11.94s
