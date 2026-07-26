# COMPILE_FAIL: Tools/clinic/libclinic/converter.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py:103:11: warning: unused variable '_tag' [-Wunused-variable]
  103 |     c_init_default: str = ''
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py:108:11: warning: unused variable '_tag' [-Wunused-variable]
  108 |     # easily happen when using option groups--although
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py:113:11: warning: unused variable '_tag' [-Wunused-variable]
  113 |     # This value is specified as a string.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py:128:11: warning: unused variable '_tag' [-Wunused-variable]
  128 |     # Should Argument Clinic add a '&' before the name of
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py:137:13: warning: unused variable '_tag' [-Wunused-variable]
  137 |     #############################################################
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py: In function 'add_c_converter_cebb44':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py:352:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  352 |         """
      |          ^~  
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py:351:10: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  351 |         data is a CRenderData instance.
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py:347:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  347 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py: In function 'CConverterAutoRegister___init__':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py:65:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   65 |     parameters must be keyword-only.
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py:63:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   63 |     For the init function, self, name, function, and default
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py:62:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   62 |     """
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py:61:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   61 | class CConverter(metaclass=CConverterAutoRegister):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py:60:11: warning: variable 'converter_cls' set but not used [-Wunused-but-set-variable]
   60 | 
      |           ^            
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/converter.py:59:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   59 |         add_default_legacy_c_converter(converter_cls)
      |           ^~~
... (1622 more lines)
```

Exit code: 1
Elapsed: 14.19s
