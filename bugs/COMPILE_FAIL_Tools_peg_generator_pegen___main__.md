# COMPILE_FAIL: Tools/peg_generator/pegen/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:43:11: warning: unused variable '_tag' [-Wunused-variable]
   43 |         if args.verbose:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:48:11: warning: unused variable '_tag' [-Wunused-variable]
   48 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:53:11: warning: unused variable '_tag' [-Wunused-variable]
   53 |     from pegen.build import build_python_parser_and_generator
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:68:11: warning: unused variable '_tag' [-Wunused-variable]
   68 |         if args.verbose:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:77:13: warning: unused variable '_tag' [-Wunused-variable]
   77 | )
      |             ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py: In function 'generate_c_code_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:288:11: warning: variable '_t81' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:287:11: warning: variable '_t80' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:285:11: warning: variable '_t78' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:279:11: warning: variable '_t72' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:278:11: warning: variable '_t71' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:257:11: warning: variable '_t51' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:253:11: warning: variable '_t48' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:249:11: warning: variable '_t45' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:245:11: warning: variable '_t42' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:242:11: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:240:9: warning: variable '_t37' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:219:10: warning: unused variable '_t16' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py: In function 'generate_python_code_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:127:11: warning: variable '_t66' set but not used [-Wunused-but-set-variable]
  127 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:126:11: warning: variable '_t65' set but not used [-Wunused-but-set-variable]
  126 | )
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:124:11: warning: variable '_t63' set but not used [-Wunused-but-set-variable]
  124 |     action="store_true",
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:118:11: warning: variable '_t57' set but not used [-Wunused-but-set-variable]
  118 |     metavar="OUT",
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/__main__.py:117:11: warning: variable '_t56' set but not used [-Wunused-but-set-variable]
  117 |     "--output",
      |           ^~~~
... (124 more lines)
```

Exit code: 1
Elapsed: 14.16s
