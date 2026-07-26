# COMPILE_FAIL: Lib/urllib/robotparser.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py: In function '_alloc_Entry':
/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py:74:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   74 |             self.parse(raw.decode("utf-8", "surrogateescape").splitlines())
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py: In function 'RobotFileParser___init__':
/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py:333:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  333 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py:331:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  331 |         path += '?' + query
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py:330:7: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  330 |         query = re.sub(r'[^=&]+', lambda m: normalize(m[0]), query)
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py:329:9: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  329 |     if sep:
      |         ^~~
/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py:328:9: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  328 |     path = normalize(path)
      |         ^~~
/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py:327:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  327 |     path, sep, query = path.partition('?')
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py:326:14: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  326 | def normalize_uri(path):
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py:325:14: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  325 | 
      |              ^  
/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py:324:14: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  324 |     return urllib.parse.quote(unquoted, errors='surrogateescape')
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py:323:14: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  323 |     unquoted = urllib.parse.unquote(path, errors='surrogateescape')
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py:322:14: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  322 | def normalize(path):
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py:321:14: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  321 | 
      |              ^  
/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py: In function 'RobotFileParser_mtime':
/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py:46:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   46 |         """
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py:44:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   44 |         check for new robots.txt files periodically.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/urllib/robotparser.py:43:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
... (1776 more lines)
```

Exit code: 1
Elapsed: 14.16s
