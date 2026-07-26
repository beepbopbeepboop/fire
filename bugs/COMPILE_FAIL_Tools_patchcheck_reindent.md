# COMPILE_FAIL: Tools/patchcheck/reindent.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py: In function '_alloc_Reindenter':
/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py:55:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   55 | # A specified newline to be used in the output (set by --newline option)
      | ^~~~
/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py: In function 'errprint':
/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py:94:11: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
   94 |             return
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py:88:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
   88 |             if not a.upper() in ('CRLF', 'LF'):
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py:73:11: warning: variable 'arg' set but not used [-Wunused-but-set-variable]
   73 |         opts, args = getopt.getopt(sys.argv[1:], "drnvh",
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py:72:14: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   72 |     try:
      |              ^  
/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py: In function '_gimple_main':
/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py:124:7: warning: variable '_t49' set but not used [-Wunused-but-set-variable]
  124 |             errprint("%s: SyntaxError: %s" % (file, str(se)))
      |       ^   
/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py:119:9: warning: variable '_t44' set but not used [-Wunused-but-set-variable]
  119 |         print("checking", file, "...", end=' ')
      |         ^~~~
/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py:98:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
   98 |         r.write(sys.stdout)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py:97:11: warning: variable 'opts' set but not used [-Wunused-but-set-variable]
   97 |         r.run()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py:94:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
   94 |             return
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py:85:10: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   85 |         elif o in ('-v', '--verbose'):
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py:82:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   82 |             recurse = True
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py:78:10: warning: unused variable '_t6' [-Wunused-variable]
   78 |     for o, a in opts:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py: In function 'check_584a43':
/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py:289:7: warning: variable '_t164' set but not used [-Wunused-but-set-variable]
  289 |                    COMMENT=tokenize.COMMENT,
      |       ^    
/Users/mrs/net/Python-3.14.6/Tools/patchcheck/reindent.py:274:11: warning: variable '_t149' set but not used [-Wunused-but-set-variable]
  274 | 
      |           ^    
... (1037 more lines)
```

Exit code: 1
Elapsed: 13.87s
