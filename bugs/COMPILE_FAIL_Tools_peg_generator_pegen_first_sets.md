# COMPILE_FAIL: Tools/peg_generator/pegen/first_sets.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py: In function '_alloc_FirstSetCalculator':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py:50:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   50 |             new_terminals = self.visit(other)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py: In function 'FirstSetCalculator___init__':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py:225:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py:223:13: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py:222:13: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py:221:14: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py:220:14: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py:219:7: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py:218:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py:217:14: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py: In function 'FirstSetCalculator_calculate':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py:63:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   63 |                 continue
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py:58:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   58 |             # it means that the item is completely nullable and we should
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py:46:11: warning: variable 'name' set but not used [-Wunused-but-set-variable]
   46 |     def visit_Alt(self, item: Alt) -> set[str]:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py: In function 'FirstSetCalculator_visit_Alt':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py:62:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   62 |             if "" in new_terminals:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py:60:7: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   60 |             # one fails to parse.
      |       ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py:54:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   54 |             if to_remove:
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py:52:13: warning: variable 'to_remove' set but not used [-Wunused-but-set-variable]
   52 |                 to_remove |= new_terminals
      |             ^   ~~~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py: In function 'FirstSetCalculator_visit_Cut':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py:78:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   78 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py: In function 'FirstSetCalculator_visit_Group':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py:86:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   86 |         return self.visit(item.item)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py: In function 'FirstSetCalculator_visit_PositiveLookahead':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py:89:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   89 |         return self.visit(item.node)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/first_sets.py: In function 'FirstSetCalculator_visit_NegativeLookahead':
... (95 more lines)
```

Exit code: 1
Elapsed: 13.72s
