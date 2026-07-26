# COMPILE_FAIL: Lib/urllib/parse.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py: In function '_alloc_DefragResult':
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py:237:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  237 |         netloc = self.netloc
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py: In function '_alloc_ParseResult':
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py:251:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  251 | _SplitResultBase = namedtuple(
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py: In function '_alloc_SplitResult':
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py:265:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  265 | _DefragResultBase.fragment.__doc__ = """
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py: In function '_alloc__Quoter':
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py:279:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  279 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py: In function 'clear_cache':
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py:921:7: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  921 | 
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py:920:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  920 |     but not necessarily in all of them.
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py:919:7: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  919 |     Each of the reserved characters is reserved in some component of a URL,
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py:918:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  918 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py:917:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  917 |                   / "*" / "+" / "," / ";" / "="
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py: In function '_ResultMixinStr_encode':
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py:141:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  141 |         return self._encoded_counterpart(*(x.encode(encoding, errors) for x in self))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py:139:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  139 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py:138:14: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  138 |     __slots__ = ()
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py: In function '_ResultMixinBytes_decode':
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py:149:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  149 |         return self._decoded_counterpart(*(x.decode(encoding, errors) for x in self))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/urllib/parse.py:147:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  147 | 
      |           ^  
... (3110 more lines)
```

Exit code: 1
Elapsed: 14.63s
