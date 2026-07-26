# COMPILE_FAIL: Tools/freeze/freeze.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/freeze/freeze.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
# ERROR: compiling imported module 'makefreeze' from /Users/mrs/net/Python-3.14.6/Tools/freeze/makefreeze.py: 23:0: Unexpected INDENT('')
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py: In function '_alloc_open_close_env':
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:38:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py: In function 'open_close':
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:27:1: warning: label 'bb_4' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:32:1: warning: label 'bb_3' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:68:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:66:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:65:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:64:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:63:10: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:62:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:61:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:60:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:59:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:58:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:57:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:56:11: warning: variable 'os' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:55:9: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:54:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:53:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:52:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:51:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:50:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:49:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:48:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:47:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:46:11: warning: variable 'filecmp' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py: In function 'mojo_open_132aaf':
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:70:11: warning: variable '_t37' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:69:11: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:67:10: warning: unused variable '_t34' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:55:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:51:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:49:10: warning: unused variable '_t16' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/bkfile.py:32:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/parsesetup.py: In function 'getmakevars_584a43':
/Users/mrs/net/Python-3.14.6/Tools/freeze/parsesetup.py:14:9: error: too many arguments to function 'mojo_open_file'; expected 1, have 3
   14 |     fp = open(filename)
      |         ^~~~~~~~~~~~~~             
/Users/mrs/net/Python-3.14.6/Tools/freeze/checkextensions.py:472:9: note: declared here
/Users/mrs/net/Python-3.14.6/Tools/freeze/parsesetup.py:40:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   40 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/freeze/parsesetup.py:128:7: warning: variable '_t61' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/parsesetup.py:116:10: warning: variable '_t50' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/freeze/parsesetup.py:111:11: warning: variable '_t46' set but not used [-Wunused-but-set-variable]
  111 |     test()
      |           ^   
... (454 more lines)
```

Exit code: 1
Elapsed: 15.27s
