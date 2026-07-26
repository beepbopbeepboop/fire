# COMPILE_FAIL: Tools/clinic/libclinic/formatting.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py:29:11: warning: unused variable '_tag' [-Wunused-variable]
   29 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py:34:11: warning: unused variable '_tag' [-Wunused-variable]
   34 |         ("\\", "\\\\"),  # must be first!
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py:39:11: warning: unused variable '_tag' [-Wunused-variable]
   39 |     return text
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py:54:11: warning: unused variable '_tag' [-Wunused-variable]
   54 | def _break_trigraphs(s: str) -> str:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py:63:13: warning: unused variable '_tag' [-Wunused-variable]
   63 |     return s
      |             ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py: In function 'docstring_for_c_string_584a43':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py:248:7: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
  248 |             lines.extend([line, "\n"])
      |       ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py:246:10: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
  246 |         name, curly, trailing = trailing.partition("}")
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py:242:7: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
  242 |         if not curly:
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py:230:7: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
  230 |       * If the substitution text is empty, the source line
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py:228:7: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  228 |       * The strings substituted must be on lines by
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py:226:7: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  226 |     """
      |       ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py:216:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  216 |                 line += parameters.pop(0)
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py: In function '_quoted_for_c_string_584a43':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py:33:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   33 |     for old, new in (
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py: In function '_break_trigraphs_584a43':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/formatting.py:88:10: warning: variable '_t45' set but not used [-Wunused-but-set-variable]
   88 |         if not r.startswith((r'\0', r'\1')):
... (257 more lines)
```

Exit code: 1
Elapsed: 14.07s
