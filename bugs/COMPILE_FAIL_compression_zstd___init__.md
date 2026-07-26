# COMPILE_FAIL: Lib/compression/zstd/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py: In function '_alloc_FrameInfo':
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:90:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   90 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:104:11: warning: unused variable '_tag' [-Wunused-variable]
  104 |     finalize *zstd_dict* by adding headers and statistics according to the
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:109:11: warning: unused variable '_tag' [-Wunused-variable]
  109 |     basis dictionary may be a "raw content" dictionary.  See *is_raw* in
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:114:11: warning: unused variable '_tag' [-Wunused-variable]
  114 |     *dict_size* is the dictionary's maximum size, in bytes.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:129:11: warning: unused variable '_tag' [-Wunused-variable]
  129 |     chunk_sizes = tuple(_nbytes(sample) for sample in samples)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:138:13: warning: unused variable '_tag' [-Wunused-variable]
  138 | def compress(data, level=None, options=None, zstd_dict=None):
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py: In function 'FrameInfo___init__':
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:274:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:272:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:271:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:270:10: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:269:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:268:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:267:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:266:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:265:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:264:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:263:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:262:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:261:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py: In function 'FrameInfo___repr__':
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:54:13: error: 'FrameInfo' has no member named 'decompressed_size'
   54 |         return (f'FrameInfo(decompressed_size={self.decompressed_size}, '
      |             ^~
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:54:13: error: 'FrameInfo' has no member named 'dictionary_id'
   54 |         return (f'FrameInfo(decompressed_size={self.decompressed_size}, '
      |             ^~
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:70:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   70 |     decompressed, or None when the decompressed size is unknown.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py: In function 'FrameInfo___setattr__':
... (143 more lines)
```

Exit code: 1
Elapsed: 9.57s
