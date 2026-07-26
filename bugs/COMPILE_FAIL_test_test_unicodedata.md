# COMPILE_FAIL: Lib/test/test_unicodedata.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py:172:11: warning: unused variable '_tag' [-Wunused-variable]
  172 |             if looked_name is not None:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py:177:11: warning: unused variable '_tag' [-Wunused-variable]
  177 |                 *range(0xf0000, 0xfffff),
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py:182:11: warning: unused variable '_tag' [-Wunused-variable]
  182 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py:197:11: warning: unused variable '_tag' [-Wunused-variable]
  197 |             "CJK UNIFIED IDEOGRAPH-17000",
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py:206:13: warning: unused variable '_tag' [-Wunused-variable]
  206 |     def test_digit(self):
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py: In function 'iterallchars':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py:31:20: error: passing argument 1 of 'mojo_map' makes pointer from integer without a cast [-Wint-conversion]
   31 |     return map(chr, range(maxunicode + 1))
      |                    ^~~
      |                    |
      |                    int64_t {aka long long int}
In file included from test_unicodedata.ci:14:
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:333:22: note: expected 'void *' but argument is of type 'int64_t' {aka 'long long int'}
  333 | void *mojo_map(void *func, void *iterable);
      |                ~~~~~~^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py:31:8: error: assignment to 'int64_t' {aka 'long long int'} from 'void *' makes integer from pointer without a cast [-Wint-conversion]
   31 |     return map(chr, range(maxunicode + 1))
      |        ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py: In function 'UnicodeMethodsTest_test_method_checksum':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py:47:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   47 |                 # Predicates (single char)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py:45:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   45 |             s3 = char + '123'
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py:44:7: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   44 |             s2 = char + 'ABC'
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py:43:11: warning: variable 'result' set but not used [-Wunused-but-set-variable]
   43 |             s1 = char + 'abc'
      |           ^ ~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unicodedata.py:42:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   42 |         for char in iterallchars():
      |           ^~~
... (19817 more lines)
```

Exit code: 1
Elapsed: 15.84s
