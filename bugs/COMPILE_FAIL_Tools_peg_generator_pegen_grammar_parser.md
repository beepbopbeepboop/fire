# COMPILE_FAIL: Tools/peg_generator/pegen/grammar_parser.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py:93:11: warning: unused variable '_tag' [-Wunused-variable]
   93 |     @memoize
      |           ^~  
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py:98:11: warning: unused variable '_tag' [-Wunused-variable]
   98 |             (literal := self.expect("@"))
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py:103:11: warning: unused variable '_tag' [-Wunused-variable]
  103 |         ):
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py:118:11: warning: unused variable '_tag' [-Wunused-variable]
  118 |             (literal := self.expect("@"))
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py:127:13: warning: unused variable '_tag' [-Wunused-variable]
  127 |         self._reset(mark)
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py: In function 'GeneratedParser_start':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py:56:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   56 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py:70:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   70 |         ):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py:65:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   65 |         ):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py:54:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   54 |         self._reset(mark)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py:58:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   58 |     def grammar(self) -> Optional[Grammar]:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py:249:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  249 |         if (
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py:247:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  247 |             return Rhs ( [alt] + alts . alts )
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py:246:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  246 |         ):
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py:245:9: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  245 |             (alts := self.alts())
      |         ^  
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_parser.py:244:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
... (1965 more lines)
```

Exit code: 1
Elapsed: 13.63s
