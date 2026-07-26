# COMPILE_FAIL: Tools/peg_generator/pegen/ast_dump.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py:21:11: warning: unused variable '_tag' [-Wunused-variable]
   21 |             level += 1
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py:26:11: warning: unused variable '_tag' [-Wunused-variable]
   26 |             sep = ", "
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py:31:11: warning: unused variable '_tag' [-Wunused-variable]
   31 |             keywords = annotate_fields
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py:46:11: warning: unused variable '_tag' [-Wunused-variable]
   46 |                     args.append(value)
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py:55:13: warning: unused variable '_tag' [-Wunused-variable]
   55 |                     value, simple = _format(value, level)
      |             ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py: In function '_alloc_ast_dump__format_env':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py:136:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py: In function 'ast_dump__format':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py:66:1: warning: label 'bb_21' defined but not used [-Wunused-label]
   66 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py:74:1: warning: label 'bb_20' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py:69:1: warning: label 'bb_19' defined but not used [-Wunused-label]
   69 |     return _format(node)[0]
      | ^   ~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py:67:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   67 |     if all(cls.__name__ != "AST" for cls in node.__class__.__mro__):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py:62:1: warning: label 'bb_18' defined but not used [-Wunused-label]
   62 |             if not node:
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py:78:1: warning: label 'bb_17' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py:72:1: warning: label 'bb_16' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py:61:1: warning: label 'bb_14' defined but not used [-Wunused-label]
   61 |         elif isinstance(node, list):
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py:65:1: warning: label 'bb_15' defined but not used [-Wunused-label]
   65 |         return repr(node), True
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py:55:1: warning: label 'bb_13' defined but not used [-Wunused-label]
   55 |                     value, simple = _format(value, level)
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/ast_dump.py:59:1: warning: label 'bb_12' defined but not used [-Wunused-label]
   59 |                 return "{}({})".format(node.__class__.__name__, ", ".join(args)), not args
... (196 more lines)
```

Exit code: 1
Elapsed: 13.88s
