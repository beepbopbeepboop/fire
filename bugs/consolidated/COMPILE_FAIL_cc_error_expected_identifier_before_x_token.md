# COMPILE_FAIL: CC ERROR: expected identifier before 'X' token

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py: In function '_alloc_IntLike':
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py:408:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  408 |                 self.ioclass.__init__(me, initvalue)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py: In function 'IntLike___init__':
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py:917:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  917 |         # to be immutable.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py:915:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  915 |         # BytesIO should accept only Bytes for copy-on-write sharing, since
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py: In function 'IntLike___index__':
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py:25:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   25 |     def testInit(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py:23:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   23 | class MemorySeekTestMixin:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py: In function 'MemorySeekTestMixin_testInit':
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py:31:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   31 |         bytesIo = self.ioclass(buf)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py:29:11: warning: variable 'bytesIo' set but not used [-Wunused-but-set-variable]
   29 |     def testRead(self):
      |           ^~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py:28:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   28 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py:27:11: warning: variable 'buf' set but not used [-Wunused-but-set-variable]
   27 |         bytesIo = self.ioclass(buf)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py:26:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   26 |         buf = self.buftype("1234567890")
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py:25:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   25 |     def testInit(self):
      |          ^~~
In file included from /opt/local/lib/gcc15/gcc/aarch64-apple-darwin25/15.2.0/include-fixed/stdio.h:75,
                 from test_memoryio.ci:8:
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py: In function 'MemorySeekTestMixin_testRead':
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py:36:16: error: expected identifier before '(' token
   36 |         self.assertEqual(self.EOF, bytesIo.read())
      |                ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py:65:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   65 |         bytesIo = self.ioclass(buf)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py:63:11: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
   63 |     def testTell(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py:62:10: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
   62 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py:61:25: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
   61 |         self.assertEqual(self.EOF, bytesIo.read(4))
      |                         ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_memoryio.py:60:11: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
   60 |         self.assertEqual(sys.maxsize - 2, bytesIo.seek(sys.maxsize - 2))
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/tes
```

## Affected files

- `Lib/test/test_memoryio.py`
