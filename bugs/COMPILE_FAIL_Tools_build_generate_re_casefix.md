# COMPILE_FAIL: Tools/build/generate_re_casefix.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py: In function '_alloc_hexint':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py:40:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   40 |     return c if c.isalpha() else ascii(c)[1:-1]
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py:54:11: warning: unused variable '_tag' [-Wunused-variable]
   54 |                               if len(t) > 1]
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py:59:11: warning: unused variable '_tag' [-Wunused-variable]
   59 |             if i > 0xffff:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py:64:11: warning: unused variable '_tag' [-Wunused-variable]
   64 |                     pass
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py:79:11: warning: unused variable '_tag' [-Wunused-variable]
   79 |     for i, t in sorted(mapping.items()):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py:88:13: warning: unused variable '_tag' [-Wunused-variable]
   88 |             ''.join(map(alpha, t)),
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py: In function 'update_file_0335d0':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py:213:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py:187:10: warning: unused variable '_t6' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py: In function 'uname_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py:34:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   34 | class hexint(int):
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py:26:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   26 | _EXTRA_CASES = {{
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py: In function 'hexint___repr__':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py:44:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   44 |     # Find sets of characters which have the same uppercase.
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py: In function 'alpha_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py:49:7: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   49 | 
      |       ^  
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py: In function '_gimple_main':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_re_casefix.py:55:20: error: passing argument 1 of 'mojo_map' makes pointer from integer without a cast [-Wint-conversion]
   55 | 
      |                    ^  
      |                    |
      |                    int64_t {aka long long int}
In file included from generate_re_casefix.ci:14:
... (121 more lines)
```

Exit code: 1
Elapsed: 14.31s
