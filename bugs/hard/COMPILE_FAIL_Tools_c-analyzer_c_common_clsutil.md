# COMPILE_FAIL (hard): Tools/c-analyzer/c_common/clsutil.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py`

Root cause: see `CODEGEN_dynamic_attribute_on_generic_object.md` in this
directory (that file has the minimal test case). Summary: `Slot.
__set_name__`'s `cls.__slot_names__ = []` sets a dynamic attribute on a
generically-typed object (`cls: type`); this codegen has no `__dict__`-
style dynamic attribute storage for non-struct objects at all. Re-confirmed
reproducing as of 2026-08-05 (unchanged by commit 12ff719 — a different
bug entirely).

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py:59:11: warning: unused variable '_tag' [-Wunused-variable]
   59 |     def __set__(self, obj, value):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py:64:11: warning: unused variable '_tag' [-Wunused-variable]
   64 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py:69:11: warning: unused variable '_tag' [-Wunused-variable]
   69 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py:84:11: warning: unused variable '_tag' [-Wunused-variable]
   84 |         cls.__del__ = __del__
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py:93:13: warning: unused variable '_tag' [-Wunused-variable]
   93 |         self.instances[id(obj)] = value
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py: In function 'Slot___init__':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py:177:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py:175:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py:174:14: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py:173:14: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py:172:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py:171:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py:170:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py: In function 'Slot___set_name__':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py:39:6: error: request for member '__slot_names__' in something not a structure or union
   39 |             slotnames = cls.__slot_names__ = []
      |      ^
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py:42:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   42 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py:51:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   51 |             else:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py:45:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   45 |             return self
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py:44:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   44 |         if obj is None:  # called on the class
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py:41:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   41 |         self._ensure___del__(cls, slotnames)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/clsutil.py:81:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   81 |                 delattr(_self, name)
... (437 more lines)
```

Exit code: 1
Elapsed: 14.73s
