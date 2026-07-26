# COMPILE_FAIL: Doc/includes/ndiff.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py:25:11: warning: unused variable '_tag' [-Wunused-variable]
   25 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py:30:11: warning: unused variable '_tag' [-Wunused-variable]
   30 | "+ " lines; use ndiff with -r2; or, on Unix, the second file can be
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py:35:11: warning: unused variable '_tag' [-Wunused-variable]
   35 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py:50:11: warning: unused variable '_tag' [-Wunused-variable]
   50 |         return open(fname)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py:59:13: warning: unused variable '_tag' [-Wunused-variable]
   59 |         return 0
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py: In function 'fail_0c85c9':
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py:161:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py:160:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py:156:11: warning: variable 'out' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py: In function 'mojo_fopen_584a43':
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py:57:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   57 |     f2 = fopen(f2name)
      | ^   
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py:54:10: warning: unused variable '_t6' [-Wunused-variable]
   54 | # open two files & spray the diff to stdout; return false iff a problem
      |          ^~~
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py: In function 'fcompare_abb124':
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py:87:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
   87 |         return fail("can't specify both -q and -r")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py:83:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
   83 |         elif opt == "-r":
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py:81:7: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
   81 |             qseen = 1
      |       ^   
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py:79:14: warning: variable 'b' set but not used [-Wunused-but-set-variable]
   79 |     for opt, val in opts:
      |              ^
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py:76:7: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   76 |         return fail(str(detail))
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py: In function '_gimple_main':
/Users/mrs/net/Python-3.14.6/Doc/includes/ndiff.py:153:11: warning: variable '_t77' set but not used [-Wunused-but-set-variable]
... (73 more lines)
```

Exit code: 1
Elapsed: 5.22s
