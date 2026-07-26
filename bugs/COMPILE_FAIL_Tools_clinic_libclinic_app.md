# COMPILE_FAIL: Tools/clinic/libclinic/app.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py:61:11: warning: unused variable '_tag' [-Wunused-variable]
   61 | impl_definition block
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py:66:11: warning: unused variable '_tag' [-Wunused-variable]
   66 | impl_definition block
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py:71:11: warning: unused variable '_tag' [-Wunused-variable]
   71 | preset partial-buffer
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py:86:11: warning: unused variable '_tag' [-Wunused-variable]
   86 |         *,
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py:95:13: warning: unused variable '_tag' [-Wunused-variable]
   95 |         if printer:
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py: In function 'Clinic___init__':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py:115:16: error: 'Clinic' has no member named 'get_destination_buffer'; did you mean 'destination_buffers'?
  115 |         d = self.get_destination_buffer
      |                ^~~~~~~~~~~~~~~~~~~~~~
      |                destination_buffers
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py:163:19: error: expected expression before '(' token
  163 |         *args: str
      |                   ^
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py:157:1: warning: label 'bb_27' defined but not used [-Wunused-label]
  157 |             preset[name] = buffer
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py:157:1: warning: label 'bb_28' defined but not used [-Wunused-label]
  157 |             preset[name] = buffer
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py:156:1: warning: label 'bb_25' defined but not used [-Wunused-label]
  156 |             assert name in self.destination_buffers
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py:159:1: warning: label 'bb_26' defined but not used [-Wunused-label]
  159 |     def add_destination(
      | ^   ~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py:161:1: warning: label 'bb_24' defined but not used [-Wunused-label]
  161 |         name: str,
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py:156:1: warning: label 'bb_23' defined but not used [-Wunused-label]
  156 |             assert name in self.destination_buffers
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/app.py:164:1: warning: label 'bb_22' defined but not used [-Wunused-label]
  164 |     ) -> None:
      | ^   ~
... (700 more lines)
```

Exit code: 1
Elapsed: 14.18s
