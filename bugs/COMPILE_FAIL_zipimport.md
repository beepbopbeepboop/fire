# COMPILE_FAIL: Lib/zipimport.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/zipimport.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py:110:11: warning: unused variable '_tag' [-Wunused-variable]
  110 |             return _bootstrap.spec_from_loader(fullname, self, is_package=module_info)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py:115:11: warning: unused variable '_tag' [-Wunused-variable]
  115 |             # We're only interested in the last path component of fullname
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py:120:11: warning: unused variable '_tag' [-Wunused-variable]
  120 |                 # package. Return the string representing its path,
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py:135:11: warning: unused variable '_tag' [-Wunused-variable]
  135 |         """
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py:144:13: warning: unused variable '_tag' [-Wunused-variable]
  144 |         the file wasn't found.
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py: In function 'zipimporter___init__':
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py:103:1: warning: label 'bb_26' defined but not used [-Wunused-label]
  103 |     def find_spec(self, fullname, target=None):
      | ^   ~
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py:105:1: warning: label 'bb_25' defined but not used [-Wunused-label]
  105 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py:98:1: warning: label 'bb_24' defined but not used [-Wunused-label]
   98 |         self.prefix = _bootstrap_external._path_join(*prefix[::-1])
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py:126:1: warning: label 'bb_23' defined but not used [-Wunused-label]
  126 |                 return spec
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py:110:1: warning: label 'bb_22' defined but not used [-Wunused-label]
  110 |             return _bootstrap.spec_from_loader(fullname, self, is_package=module_info)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py:102:1: warning: label 'bb_21' defined but not used [-Wunused-label]
  102 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py:113:1: warning: label 'bb_15' defined but not used [-Wunused-label]
  113 |             # therefore possibly a portion of a namespace package.
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py:118:1: warning: label 'bb_20' defined but not used [-Wunused-label]
  118 |             if _is_dir(self, modpath):
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py:110:1: warning: label 'bb_19' defined but not used [-Wunused-label]
  110 |             return _bootstrap.spec_from_loader(fullname, self, is_package=module_info)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/zipimport.py:89:1: warning: label 'bb_18' defined but not used [-Wunused-label]
... (1912 more lines)
```

Exit code: 1
Elapsed: 13.37s
