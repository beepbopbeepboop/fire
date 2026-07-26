# COMPILE_FAIL: Tools/c-analyzer/c_analyzer/info.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:67:11: warning: unused variable '_tag' [-Wunused-variable]
   67 |             return resolved, None
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:72:11: warning: unused variable '_tag' [-Wunused-variable]
   72 |         if extra:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:77:11: warning: unused variable '_tag' [-Wunused-variable]
   77 |         elif typedeps in (None, UNKNOWN):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:92:11: warning: unused variable '_tag' [-Wunused-variable]
   92 |         elif item.kind is KIND.STRUCT or item.kind is KIND.UNION:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:101:13: warning: unused variable '_tag' [-Wunused-variable]
  101 |         elif typedecl and not isinstance(typedecl, TypeDeclaration):
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function 'SystemType___init__':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:227:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  227 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:225:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  225 |         self.item.fix_filename(relroot, **kwargs)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function 'Analyzed_is_target':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:38:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   38 |     def from_raw(cls, raw, **extra):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:36:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   36 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:47:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   47 |             return cls(raw, **extra)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:38:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   38 |     def from_raw(cls, raw, **extra):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:36:9: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   36 | 
      |         ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:35:9: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   35 |             return False
      |         ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:34:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   34 |         else:
      |           ^~~
... (2301 more lines)
```

Exit code: 1
Elapsed: 13.82s
