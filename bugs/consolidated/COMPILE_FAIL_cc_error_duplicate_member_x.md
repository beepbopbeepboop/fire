# COMPILE_FAIL: CC ERROR: duplicate member 'X'

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/test_util.py:204:11: error: duplicate member 'importlib_util'
  204 |             sys.modules[name] = module
      |           ^ ~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/test_util.py: In function '_alloc_PatchAtomicWrites':
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/test_util.py:260:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  260 |             spec_again = self.util.find_spec(fullname)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/test_util.py: In function 'DecodeSourceBytesTests_test_ut8_default':
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/test_util.py:42:13: error: 'DecodeSourceBytesTests' has no member named 'util'
   42 |         self.assertEqual(self.util.decode_source(source_bytes), self.source)
      |             ^~
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/test_util.py:605:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  605 |         with util.temporary_pycache_prefix(pycache_prefix):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/test_util.py:603:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  603 |                             f'qux.{self.tag}.pyc')
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/test_util.py:602:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  602 |         path = os.path.join(pycache_prefix, 'foo', 'bar', 'baz',
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/test_util.py:601:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  601 |         pycache_prefix = os.path.join(os.path.sep, 'tmp', 'bytecode')
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/test_util.py:600:28: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  600 |         # the path within pycache_prefix.
      |                            ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/test_util.py:599:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  599 |         # we return an absolute path to the py file based on the remainder of
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/test_util.py:598:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  598 |         # If pycache_prefix is set and the cache path we get is inside it,
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/test_util.py:597:11: warning: variable 'source_bytes' set but not used [-Wunused-but-set-variable]
  597 |     def test_source_from_cache_inside_pycache_prefix(self):
      |           ^~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/test_util.py:596:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  596 |                      'requires sys.implementation.cache_tag to not be None')
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/test_util.py:595:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  595 |     @unittest.skipIf(sys.implementation.cache_tag is None,
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/test_util.py:594:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  594 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/test_util.py:593:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  593 |                 self.assertEqual(self.util.cache_from_source(path), expect)
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/test_util.py: In function 'DecodeSourceBytesTests_test_specified_encoding':
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/test_util.py:48:14: error: 'DecodeSourceBytesTests'
```

## Affected files

- `Lib/test/test_importlib/test_util.py`
