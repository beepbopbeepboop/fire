# COMPILE_FAIL: Tools/peg_generator/pegen/c_generator.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py: In function '_alloc_CCallMakerVisitor':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py:129:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  129 |         non_exact_tokens: set[str],
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py: In function '_alloc_FunctionCall':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py:143:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  143 |             nodetype=NodeTypes.KEYWORD,
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py: In function 'FunctionCall___str__':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py:102:8: error: assignment to 'int64_t' {aka 'long long int'} from 'void *' makes integer from pointer without a cast [-Wint-conversion]
  102 |             parts.append(f"({', '.join(map(str, self.arguments))})")
      |        ^
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py:102:8: error: assignment to 'int64_t' {aka 'long long int'} from 'void *' makes integer from pointer without a cast [-Wint-conversion]
  102 |             parts.append(f"({', '.join(map(str, self.arguments))})")
      |        ^
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py:659:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  659 |                 self.print("if (_n == 0 || p->error_indicator) {")
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py:655:7: warning: variable '_t53' set but not used [-Wunused-but-set-variable]
  655 |                 is_gather=node.is_gather(),
      |       ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py:629:7: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
  629 | 
      |       ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py:623:7: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
  623 |             self.print("_res = NULL;")
      |       ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py:614:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
  614 |                 self._set_up_token_start_metadata_extraction()
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py:605:7: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  605 |             self._check_for_errors()
      |       ^  
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py: In function 'CCallMakerVisitor___init__':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py:134:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  134 |         self.cache: dict[str, str] = {}
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py:132:14: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  132 |         self.exact_tokens = exact_tokens
      |              ^~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py:131:14: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  131 |         self.gen = parser_generator
      |              ^~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py:130:14: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  130 |     ):
      |              ^  
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/c_generator.py:129:14: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  129 |         non_exact_tokens: set[str],
      |              ^~~
... (4890 more lines)
```

Exit code: 1
Elapsed: 13.72s
