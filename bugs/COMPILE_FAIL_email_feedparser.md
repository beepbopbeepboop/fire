# COMPILE_FAIL: Lib/email/feedparser.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py: In function '_alloc_BufferedSubFile':
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:125:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  125 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py: In function 'BufferedSubFile___init__':
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:355:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  355 |                         linesep = mo.group('linesep')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:353:9: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  353 |                     if mo.group('end'):
      |         ^  
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:352:14: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  352 |                     # epilogue with the empty string (see below).
      |              ^  
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:351:14: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  351 |                     # the closing boundary, then we need to initialize the
      |              ^  
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:350:7: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  350 |                     # this multipart.  If there was a newline at the end of
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:349:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  349 |                     # If we're looking at the end boundary, we're done with
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:348:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  348 |                 if mo:
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:347:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  347 |                 mo = boundarymatch(line)
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py: In function 'BufferedSubFile_push_eof_matcher':
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:71:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   71 |     def close(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:69:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   69 |         return self._eofstack.pop()
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:68:14: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   68 |     def pop_eof_matcher(self):
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py: In function 'BufferedSubFile_pop_eof_matcher':
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:76:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   76 |         self._partial.truncate()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:74:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   74 |         self.pushlines(self._partial.readlines())
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:73:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   73 |         self._partial.seek(0)
      |           ^~~
... (4733 more lines)
```

Exit code: 1
Elapsed: 14.77s
