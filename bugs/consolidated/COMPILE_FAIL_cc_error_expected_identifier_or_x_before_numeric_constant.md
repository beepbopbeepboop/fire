# COMPILE_FAIL: CC ERROR: expected identifier or 'X' before numeric constant

**7 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
In file included from /opt/local/lib/gcc15/gcc/aarch64-apple-darwin25/15.2.0/include-fixed/_stdio.h:173,
                 from /opt/local/lib/gcc15/gcc/aarch64-apple-darwin25/15.2.0/include-fixed/stdio.h:75,
                 from io.ci:8:
/Users/mrs/net/Python-3.14.6/Lib/io.py:203:7: error: expected identifier or '(' before numeric constant
/Users/mrs/net/Python-3.14.6/Lib/io.py:204:7: error: expected identifier or '(' before numeric constant
/Users/mrs/net/Python-3.14.6/Lib/io.py:205:7: error: expected identifier or '(' before numeric constant
/Users/mrs/net/Python-3.14.6/Lib/io.py:241:4: error: expected identifier before numeric constant
/Users/mrs/net/Python-3.14.6/Lib/io.py:242:3: error: expected '}' before '.' token
/Users/mrs/net/Python-3.14.6/Lib/io.py:237:37: note: to match this '{'
/Users/mrs/net/Python-3.14.6/Lib/abc.py: In function 'abstractmethod_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/abc.py:71:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   71 |     Deprecated, use 'property' with 'abstractmethod' instead:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/abc.py: In function 'abc_abstractclassmethod___init__':
/Users/mrs/net/Python-3.14.6/Lib/abc.py:38:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   38 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/abc.py:36:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   36 |             def my_abstract_classmethod(cls, ...):
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/abc.py:35:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   35 |             @abstractmethod
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/abc.py:34:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   34 |             @classmethod
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/abc.py:33:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   33 |         class C(ABC):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/abc.py:32:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   32 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/abc.py:31:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   31 |     Deprecated, use 'classmethod' with 'abstractmethod' instead:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/abc.py:30:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   30 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/abc.py: In function 'abc_abstractstaticmethod___init__':
/Users/mrs/net/Python-3.14.6/Lib/abc.py:58:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   58 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/abc.py:56:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   56 |             def my_abstract_staticmethod(...):
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/abc.py:55:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   55 |             @abstractmethod
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/abc.py:54:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   54 |             @staticmethod
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/abc.py:53:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   53 |         class C(ABC):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/abc.py:52:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   52 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/abc.py:51:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   51 |     Deprecated, use 'staticmethod' with 'abstractmethod' instead:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/abc.py:50:10: warning: variable '_t1' set but not used [-Wunused-but-set-va
```

## Affected files

- `Lib/io.py`
- `Lib/multiprocessing/util.py`
- `Lib/shlex.py`
- `Lib/test/test_call.py`
- `Lib/test/test_capi/test_float.py`
- `Lib/test/test_json/test_enum.py`
- `Lib/test/test_source_encoding.py`
