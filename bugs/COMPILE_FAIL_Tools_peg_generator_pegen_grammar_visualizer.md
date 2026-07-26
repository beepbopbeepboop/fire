# COMPILE_FAIL: Tools/peg_generator/pegen/grammar_visualizer.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py: In function '_alloc_ASTGrammarPrinter':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py:36:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   36 |         line = prefix + ("└──" if istail else "├──") + value + "\n"
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py: In function 'ASTGrammarPrinter_children':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py:178:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py:176:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py: In function 'ASTGrammarPrinter_name':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py:33:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   33 |         children = list(self.children(node))
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py:30:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   30 |             printer(self.print_nodes_recursively(rule))
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py: In function 'ASTGrammarPrinter_print_grammar_ast':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py:33:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   33 |         children = list(self.children(node))
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py:39:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   39 |         if not children:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py:44:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   44 |             line += self.print_nodes_recursively(child, prefix + sufix, False)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py:40:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   40 |             return line
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py:50:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   50 | def main() -> None:
      | ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py:48:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
   48 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py:47:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
   47 |         return line
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py:46:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
   46 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py:45:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
   45 |         line += self.print_nodes_recursively(last, prefix + sufix, True)
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py:44:10: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   44 |             line += self.print_nodes_recursively(child, prefix + sufix, False)
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py:43:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   43 |         for child in children:
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/grammar_visualizer.py:42:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
... (83 more lines)
```

Exit code: 1
Elapsed: 13.92s
