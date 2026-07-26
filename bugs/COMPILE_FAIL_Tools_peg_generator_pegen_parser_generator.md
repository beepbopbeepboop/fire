# COMPILE_FAIL: Tools/peg_generator/pegen/parser_generator.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py: In function '_alloc_InitialNamesVisitor':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py:108:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  108 |         self.all_rules: dict[str, Rule] = self.rules.copy()  # Rules + temporal rules
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py: In function '_alloc_KeywordCollectorVisitor':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py:122:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  122 |     @property
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py: In function '_alloc_NullableVisitor':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py:136:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  136 |             self.level -= 1
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py: In function '_alloc_RuleCheckingVisitor':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py:150:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  150 |         keyword_collector = KeywordCollectorVisitor(self, self.keywords, self.soft_keywords)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py: In function '_alloc_RuleCollectorVisitor':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py:164:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  164 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py: In function 'RuleCollectorVisitor___init__':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py:527:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py:525:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py:524:14: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py: In function 'RuleCollectorVisitor_visit_Rule':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py:46:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   46 | class KeywordCollectorVisitor(GrammarVisitor):
      | ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py:44:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   44 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py:43:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   43 |         self.callmaker.visit(item)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py:42:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   42 |     def visit_NamedItem(self, item: NamedItem) -> None:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py: In function 'RuleCollectorVisitor_visit_NamedItem':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py:49:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   49 |     def __init__(self, gen: "ParserGenerator", keywords: dict[str, int], soft_keywords: set[str]):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py:47:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   47 |     """Visitor that collects all the keywords and soft keywords in the Grammar"""
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py:46:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   46 | class KeywordCollectorVisitor(GrammarVisitor):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/parser_generator.py:45:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   45 | 
... (1684 more lines)
```

Exit code: 1
Elapsed: 13.89s
