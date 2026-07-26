# COMPILE_FAIL: Tools/check-c-api-docs/main.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py:55:11: warning: unused variable '_tag' [-Wunused-variable]
   55 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py:60:11: warning: unused variable '_tag' [-Wunused-variable]
   60 |     them = "it" if singular else "them"
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py:65:11: warning: unused variable '_tag' [-Wunused-variable]
   65 |         textwrap.dedent(
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py:80:11: warning: unused variable '_tag' [-Wunused-variable]
   80 |     """
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py:89:13: warning: unused variable '_tag' [-Wunused-variable]
   89 |         if documented and (name in IGNORED):
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py: In function 'found_undocumented_fa7153':
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py:296:11: warning: variable '_t54' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py: In function 'found_ignored_documented_fa7153':
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py:96:11: warning: variable '_t48' set but not used [-Wunused-but-set-variable]
   96 |         if not API_NAME_REGEX.fullmatch(name):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py: In function '_alloc_scan_file_for_docs_check_for_name_env':
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py:72:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   72 |         + MISTAKE
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py: In function 'scan_file_for_docs_check_for_name':
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py:115:1: warning: label 'bb_9' defined but not used [-Wunused-label]
  115 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py:112:1: warning: label 'bb_12' defined but not used [-Wunused-label]
  112 |         name = inline.group(2)
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py:98:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   98 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py:102:1: warning: label 'bb_11' defined but not used [-Wunused-label]
  102 |         name = macro.group(1)
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py:95:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   95 |         name = function.group(2)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/check-c-api-docs/main.py:93:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   93 | 
      | ^   
... (194 more lines)
```

Exit code: 1
Elapsed: 13.64s
