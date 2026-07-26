# COMPILE_FAIL: Tools/c-analyzer/c_analyzer/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py:28:11: warning: unused variable '_tag' [-Wunused-variable]
   28 |                           ):
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py:33:11: warning: unused variable '_tag' [-Wunused-variable]
   33 | def iter_decls(filenames, *,
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py:38:11: warning: unused variable '_tag' [-Wunused-variable]
   38 |     kinds = KIND.DECLS if kinds is None else (KIND.DECLS & set(kinds))
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py:53:11: warning: unused variable '_tag' [-Wunused-variable]
   53 |         known,
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py:62:13: warning: unused variable '_tag' [-Wunused-variable]
   62 |     types = {decl: None for decl in collated['type']}
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py: In function 'analyze_a64463':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py:145:8: error: variable or field 'results' declared void
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py:148:8: error: variable or field '_t10' declared void
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py:21:11: error: invalid use of void expression
   21 |     results = iter_analysis_results(filenames, **kwargs)
      |           ^
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py:147:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py: In function 'iter_analysis_results_dad6ee':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py:35:8: error: variable or field 'decls' declared void
   35 |                parse_files=_parse_files,
      |        ^    
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py:29:9: error: invalid use of void expression
   29 |     decls = iter_decls(filenames, **kwargs)
      |         ^
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py:36:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   36 |                **kwargs
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py:35:8: warning: variable 'decls' set but not used [-Wunused-but-set-variable]
   35 |                parse_files=_parse_files,
      |        ^    
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py: In function '_alloc_analyze_decls_analyze_decl_env':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py:52:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   52 |     knowntypes, knowntypespecs = _datafiles.get_known(
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py: In function 'analyze_decls_analyze_decl':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py:68:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   68 |             typespecs,
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py:66:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
... (88 more lines)
```

Exit code: 1
Elapsed: 14.14s
