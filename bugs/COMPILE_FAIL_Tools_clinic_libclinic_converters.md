# COMPILE_FAIL: Tools/clinic/libclinic/converters.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py:700:11: warning: unused variable '_tag' [-Wunused-variable]
  700 |             converter: str | None = None,
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py:705:11: warning: unused variable '_tag' [-Wunused-variable]
  705 |             if subclass_of:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py:710:11: warning: unused variable '_tag' [-Wunused-variable]
  710 |             self.format_unit = 'O!'
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py:725:11: warning: unused variable '_tag' [-Wunused-variable]
  725 | #  rwbuffer: any object supporting the buffer interface, but must be writeable
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py:734:13: warning: unused variable '_tag' [-Wunused-variable]
  734 |     pass
      |             ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py: In function 'BaseUnsignedIntConverter_use_converter':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py:30:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   30 |     def parse_arg(self, argname: str, displayname: str, *, limited_capi: bool) -> str | None:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py:1106:1: warning: label 'bb_3' defined but not used [-Wunused-label]
 1106 |                     if (PyObject_GetBuffer({argname}, &{paramname}, PyBUF_SIMPLE) != 0) {{{{
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py:1099:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1099 |                         goto exit;
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py:1097:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
 1097 |                     const char *ptr = PyUnicode_AsUTF8AndSize({argname}, &len);
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py:1096:10: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
 1096 |                     Py_ssize_t len;
      |          ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py:1095:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
 1095 |                 if (PyUnicode_Check({argname})) {{{{
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py:1094:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
 1094 |             return self.format_code("""
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py:1093:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
 1093 |         elif self.format_unit == 's*':
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py:1092:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
 1092 |             )
      |       ^  
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converters.py:1091:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
... (3682 more lines)
```

Exit code: 1
Elapsed: 14.03s
