# COMPILE_FAIL: Tools/peg_generator/pegen/grammar.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:167:11: warning: unused variable '_tag' [-Wunused-variable]
  167 |         if not SIMPLE_STR and self.action:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:172:11: warning: unused variable '_tag' [-Wunused-variable]
  172 |     def __repr__(self) -> str:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:177:11: warning: unused variable '_tag' [-Wunused-variable]
  177 |             args.append(f"action={self.action!r}")
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:192:11: warning: unused variable '_tag' [-Wunused-variable]
  192 |             return f"{self.name}={self.item}"
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:201:13: warning: unused variable '_tag' [-Wunused-variable]
  201 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py: In function 'GrammarVisitor_visit':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:419:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:417:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:416:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:415:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:414:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:413:11: warning: variable 'visitor' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:412:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:411:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:410:10: warning: variable 'method' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:409:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:408:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:407:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:406:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:405:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py: In function 'GrammarVisitor_generic_visit':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:24:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   24 |             else:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:22:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   22 |                 for item in value:
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:21:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   21 |             if isinstance(value, list):
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py: In function 'Grammar___init__':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar.py:37:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   37 |         self.metas = dict(metas)
      | ^   
... (961 more lines)
```

Exit code: 1
Elapsed: 13.85s
