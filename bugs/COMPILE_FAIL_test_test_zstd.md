# COMPILE_FAIL: Lib/test/test_zstd.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py:409:11: warning: unused variable '_tag' [-Wunused-variable]
  409 |                                     r'should be a positive int less than \d+'):
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py:414:11: warning: unused variable '_tag' [-Wunused-variable]
  414 |             c.set_pledged_input_size(2**64)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py:419:11: warning: unused variable '_tag' [-Wunused-variable]
  419 |         # ZSTD_CONTENTSIZE_UNKNOWN should use None
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py:434:11: warning: unused variable '_tag' [-Wunused-variable]
  434 |         self.assertEqual(ret.decompressed_size, 0)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py:443:13: warning: unused variable '_tag' [-Wunused-variable]
  443 |             c.set_pledged_input_size(300)
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py:811:41: warning: hex escape sequence out of range
  811 |         self.assertGreaterEqual(len(DAT), 4)
      |                                         ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py: In function 'setUpModule':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py:956:7: warning: variable '_t122' set but not used [-Wunused-but-set-variable]
  956 | 
      |       ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py:945:11: warning: variable '_t112' set but not used [-Wunused-but-set-variable]
  945 |                          self.DECOMPRESSED_60)
      |           ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py:936:11: warning: variable '_t103' set but not used [-Wunused-but-set-variable]
  936 | 
      |           ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py:899:11: warning: variable '_t70' set but not used [-Wunused-but-set-variable]
  899 |             decompress(DAT_130K_C[:-4])
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py:882:10: warning: variable '_t54' set but not used [-Wunused-but-set-variable]
  882 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py:879:11: warning: variable '_t51' set but not used [-Wunused-but-set-variable]
  879 |         self.assertEqual(decompress(self.FRAME_42_60), self.DECOMPRESSED_42_60)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py:834:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  834 | class DecompressorFlagsTestCase(unittest.TestCase):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py: In function 'FunctionsTestCase_test_version':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zstd.py:148:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  148 |     def test_roundtrip_default(self):
... (24401 more lines)
```

Exit code: 1
Elapsed: 14.38s
