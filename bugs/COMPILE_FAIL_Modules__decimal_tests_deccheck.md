# COMPILE_FAIL: Modules/_decimal/tests/deccheck.py

Source file: `/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/deccheck.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py: In function 'get_preferred_encoding':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py:267:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  267 | def all_format_sep():
      |           ^~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py: In function 'printit_7a6366':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py:304:11: warning: variable '_t103' set but not used [-Wunused-but-set-variable]
  304 |             s += str(random.randrange(1, 100))
      |           ^ ~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py:285:11: warning: variable '_t84' set but not used [-Wunused-but-set-variable]
  285 |             if align == '': fill = ''
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py:259:11: warning: variable '_t58' set but not used [-Wunused-but-set-variable]
  259 |             if 4 in active: c = typespec.replace('n', '')
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py:231:10: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
  231 |     while 1:
      |          ^~~ 
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py:211:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  211 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py:209:10: warning: unused variable '_t9' [-Wunused-variable]
  209 |         sys.stderr.write("%s  %s  %s\n" % (err, s, fmt))
      |          ^~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py: In function 'check_fillchar_0c85c9':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py:222:1: warning: label 'bb_5' defined but not used [-Wunused-label]
  222 | # Generate all unicode characters that are accepted as
      | ^~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py:230:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  230 | def rand_fillchar():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py:228:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  228 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py:226:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  226 |         c = check_fillchar(i)
      |          ^~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py:225:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  225 |     for i in range(0, 0x110002):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py:222:10: warning: unused variable '_t6' [-Wunused-variable]
  222 | # Generate all unicode characters that are accepted as
      |          ^~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py: In function 'all_fillchars':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py:235:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  235 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py: In function 'rand_fillchar':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/formathelper.py:247:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  247 |         elif elem == 1: # sign
... (4063 more lines)
```

Exit code: 1
Elapsed: 14.02s
