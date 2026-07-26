# COMPILE_FAIL: Lib/importlib/resources/abc.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py: In function 'abc_ResourceReader_open_resource':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py:82:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   82 |         with self.open('rb') as strm:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py:80:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   80 |         Read contents of self as bytes
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py: In function 'abc_ResourceReader_resource_path':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py:30:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   30 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py:28:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   28 |         # it'll still do the right thing.
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py: In function 'abc_ResourceReader_is_resource':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py:42:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   42 |         raise FileNotFoundError
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py:40:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   40 |         # NotImplementedError so that if this method is accidentally called,
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py: In function 'abc_ResourceReader_contents':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py:55:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   55 |         raise FileNotFoundError
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py:53:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   53 |     def contents(self) -> Iterable[str]:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py: In function 'abc_Traversable_iterdir':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py:63:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   63 | class Traversable(Protocol):
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py:61:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   61 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py: In function 'abc_Traversable_read_bytes':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py:88:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   88 |         """
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py:86:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   86 |         """
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py:85:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   85 |     def read_text(self, encoding: Optional[str] = None) -> str:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py:84:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   84 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/abc.py:83:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
... (499 more lines)
```

Exit code: 1
Elapsed: 10.43s
