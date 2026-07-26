# COMPILE_FAIL: Tools/peg_generator/pegen/validator.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py:59:11: warning: unused variable '_tag' [-Wunused-variable]
   59 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py:64:11: warning: unused variable '_tag' [-Wunused-variable]
   64 |     """
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py:69:11: warning: unused variable '_tag' [-Wunused-variable]
   69 |     def visit_Cut(self, node: Alt, parents: tuple[Any, ...] = ()) -> None:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py:84:11: warning: unused variable '_tag' [-Wunused-variable]
   84 |             validator.validate_rule(rule_name, rule)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py:93:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py: In function 'GrammarValidator___init__':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py:182:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py:180:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py:179:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py: In function 'GrammarValidator_validate_rule':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py:26:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   26 |             for other_alt in alts_to_consider:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py:24:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   24 |         for index, alt in enumerate(node.alts):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py:23:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   23 |     def visit_Rhs(self, node: Rhs) -> None:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py:22:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   22 | class SubRuleValidator(GrammarValidator):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py:21:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   21 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py:20:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   20 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py:19:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   19 |         self.rulename = None
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py: In function 'SubRuleValidator___init__':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py:27:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   27 |                 self.check_intersection(alt, other_alt)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/validator.py:25:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
... (481 more lines)
```

Exit code: 1
Elapsed: 13.79s
