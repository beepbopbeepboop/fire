# COMPILE_FAIL: Lib/importlib/metadata/_collections.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:40:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:45:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:50:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:65:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:74:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py: In function 'FreezableDefaultDict___missing__':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:145:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:143:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:142:7: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py: In function 'FreezableDefaultDict_freeze':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:30:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   30 |         return cls(*map(str.strip, text.split("=", 1)))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:28:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   28 |     @classmethod
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:27:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   27 | class Pair(collections.namedtuple('Pair', 'name value')):
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:26:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   26 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py: In function 'Pair_parse':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:43:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:41:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:40:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:39:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:38:14: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:37:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:36:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:35:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:34:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:33:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:32:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:31:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:30:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   30 |         return cls(*map(str.strip, text.split("=", 1)))
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:29:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   29 |     def parse(cls, text):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py:31:1: error: invalid conversion in gimple call
int64_t

... (33 more lines)
```

Exit code: 1
Elapsed: 10.26s
