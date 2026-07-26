# COMPILE_FAIL: Tools/clinic/libclinic/dsl_parser.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py:150:64: error: expected ';', ',' or ')' before 'typedef'
  150 |     *,
      |                                                                ^      
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py: In function '_alloc_FunctionNames':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py:195:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  195 |     def infer(self, line: str) -> int:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py: In function '_alloc_IndentStack':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py:209:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  209 |         current = self.indents[-1]
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py: At top level:
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py:448:4: error: 'dslparser__dispatch_t' has no member named 'directive_class'; did you mean 'directive_dump'?
  448 | 
      |    ^              
      |    directive_dump
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py:448:69: error: expected ';', ',' or ')' before 'typedef'
  448 | 
      |                                                                     ^      
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py:448:98: error: expected '}' before 'DSLParser_directive_class'
  448 | 
      |                                                                                                  ^                        
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py:436:58: note: to match this '{'
  436 |             self.disable_fastcall = True
      |                                                          ^
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py: In function 'eval_ast_expr_cebb44':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py:759:11: warning: variable 'namespace' set but not used [-Wunused-but-set-variable]
  759 |     #         with X spaces such that F < X < P.  (As before, F is the indent
      |           ^~~~~~~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py:755:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  755 |     #         docstrings.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py:748:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  748 |     #             part of the per-parameter docstring.
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py: In function 'IndentStack___init__':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py:178:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  178 |         if not self.indents:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py:176:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  176 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py:175:14: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  175 |         self.margin: str | None = None
      |              ^~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py:174:14: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  174 |         self.indents: list[int] = []
      |              ^~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/dsl_parser.py: In function 'IndentStack__ensure':
... (11222 more lines)
```

Exit code: 1
Elapsed: 14.46s
