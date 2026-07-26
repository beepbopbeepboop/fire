# COMPILE_FAIL: Lib/test/test_zlib.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py: In function '_alloc_CustomInt':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py:228:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  228 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py:242:11: warning: unused variable '_tag' [-Wunused-variable]
  242 |         x = zlib.compress(HAMLET_SCENE)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py:247:11: warning: unused variable '_tag' [-Wunused-variable]
  247 |     # Memory use of the following functions takes into account overallocation
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py:252:11: warning: unused variable '_tag' [-Wunused-variable]
  252 |         self.check_big_compress_buffer(size, compress)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py:267:11: warning: unused variable '_tag' [-Wunused-variable]
  267 |         compressed = zlib.compress(data, 1)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py:276:13: warning: unused variable '_tag' [-Wunused-variable]
  276 |             self.assertEqual(zlib.decompress(comp), data)
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py: In function '_zlib_runtime_version_tuple_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py:532:10: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
  532 |         data = random.randbytes(17 * 1024)
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py:526:7: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
  526 |         # Create compressor and decompressor objects
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py:511:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  511 |                     b = obj.flush( sync )
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py:506:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  506 |         for sync in sync_opt:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py: In function 'VersionTestCase_test_library_version':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py:53:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   53 | # and func2() produce the same compressed data made of a single (final)
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py:51:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
   51 | # "final" compressed block whereas func2() produces 3 compressed blocks (the
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py:50:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
   50 | # On s390x if zlib uses a hardware accelerator, func1() creates a single
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zlib.py:49:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
   49 | #
... (10177 more lines)
```

Exit code: 1
Elapsed: 13.81s
