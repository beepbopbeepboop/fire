# COMPILE_FAIL: Lib/test/test_type_cache.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py:111:11: warning: unused variable '_tag' [-Wunused-variable]
  111 |         class HolderSub(Holder):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py:116:11: warning: unused variable '_tag' [-Wunused-variable]
  116 |             HolderSub.value
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py:121:11: warning: unused variable '_tag' [-Wunused-variable]
  121 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py:136:11: warning: unused variable '_tag' [-Wunused-variable]
  136 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py:145:13: warning: unused variable '_tag' [-Wunused-variable]
  145 |         if type_get_version(type_) == 0:
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py: In function 'clear_type_cache':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py:275:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  275 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py:274:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  274 |         del to_bool_1
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py:271:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  271 |             not instance
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py:268:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  268 |         self._assign_valid_version_or_skip(H)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py: In function 'TypeCacheTests_test_tp_version_tag_unique':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py:55:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   55 |                          msg=f"{all_version_tags} contains non-unique versions")
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py:60:1: warning: label 'bb_11' defined but not used [-Wunused-label]
   60 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py:55:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   55 |                          msg=f"{all_version_tags} contains non-unique versions")
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py:51:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   51 |             tp_version_tag_after = type_get_version(X)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_cache.py:43:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   43 |         all_version_tags = []
      | ^   
... (1205 more lines)
```

Exit code: 1
Elapsed: 15.30s
