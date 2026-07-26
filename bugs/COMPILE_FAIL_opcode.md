# COMPILE_FAIL: Lib/opcode.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/opcode.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py:381:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py:386:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py:391:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py:406:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py:415:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/opcode.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/Lib/opcode.py:20:15: error: invalid operands to binary % (have 'char *' and 'MojoList *')
   20 | opname = ['<%r>' % (op,) for op in range(max(opmap.values()) + 1)]
      |               ^
/Users/mrs/net/Python-3.14.6/Lib/opcode.py:37:1: warning: label 'bb_55' defined but not used [-Wunused-label]
   37 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/opcode.py:36:1: warning: label 'bb_49' defined but not used [-Wunused-label]
   36 | hasexc = [op for op in opmap.values() if _opcode.has_exc(op)]
      | ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/opcode.py:35:1: warning: label 'bb_43' defined but not used [-Wunused-label]
   35 | haslocal = [op for op in opmap.values() if _opcode.has_local(op)]
      | ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/opcode.py:32:1: warning: label 'bb_37' defined but not used [-Wunused-label]
   32 | hasjrel = hasjump  # for backward compatibility
      | ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/opcode.py:31:1: warning: label 'bb_31' defined but not used [-Wunused-label]
   31 | hasjump = [op for op in opmap.values() if _opcode.has_jump(op)]
      | ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/opcode.py:30:1: warning: label 'bb_25' defined but not used [-Wunused-label]
   30 | hasname = [op for op in opmap.values() if _opcode.has_name(op)]
      | ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/opcode.py:29:1: warning: label 'bb_19' defined but not used [-Wunused-label]
   29 | hasconst = [op for op in opmap.values() if _opcode.has_const(op)]
      | ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py:943:11: warning: variable '_t199' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py:926:11: warning: variable '_t182' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py:909:11: warning: variable '_t165' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py:888:11: warning: variable '_t144' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py:871:11: warning: variable '_t127' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py:854:11: warning: variable '_t110' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py:837:11: warning: variable '_t93' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py:742:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/opcode.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/opcode.py:140:13: warning: '_mojo_classattr_init' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py:433:15: warning: '_mojo_repr_dict' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py:404:15: warning: '_mojo_dispatch_repr' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py:395:12: warning: '_mojo_dispatch_is_dataclass' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/_opcode_metadata.py:390:19: warning: '_mojo_dispatch_fields' defined but not used [-Wunused-function]
... (21 more lines)
```

Exit code: 1
Elapsed: 9.48s
