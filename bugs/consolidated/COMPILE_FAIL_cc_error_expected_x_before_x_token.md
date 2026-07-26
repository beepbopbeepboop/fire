# COMPILE_FAIL: CC ERROR: expected 'X' before 'X' token

**43 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:41:15: error: expected '{' before ';' token
   41 | """The default compression level for Zstandard, currently '3'."""
      |               ^
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:41:11: error: two or more data types in declaration specifiers
   41 | """The default compression level for Zstandard, currently '3'."""
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:49:4: error: expected identifier before 'enum'
   49 |     def __init__(self, decompressed_size, dictionary_id):
      |    ^~~~
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:49:4: warning: excess elements in struct initializer
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:49:4: note: (near initialization for '_root_globals')
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:50:3: error: expected '}' before '.' token
   50 |         super().__setattr__('decompressed_size', decompressed_size)
      |   ^
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/__init__.py:45:37: note: to match this '{'
   45 |     """Information about a Zstandard frame."""
      |                                     ^
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
/Users/mrs/net/Python-3.14.6/Lib/compress
```

## Affected files

- `Lib/compression/zstd/__init__.py`
- `Lib/dbm/__init__.py`
- `Lib/idlelib/idle_test/test_run.py`
- `Lib/logging/config.py`
- `Lib/logging/handlers.py`
- `Lib/multiprocessing/forkserver.py`
- `Lib/test/libregrtest/win_utils.py`
- `Lib/test/test_array.py`
- `Lib/test/test_capi/test_object.py`
- `Lib/test/test_compileall.py`
- `Lib/test/test_ctypes/test_aligned_structures.py`
- `Lib/test/test_ctypes/test_byteswap.py`
- `Lib/test/test_ctypes/test_prototypes.py`
- `Lib/test/test_ctypes/test_structures.py`
- `Lib/test/test_deque.py`
- `Lib/test/test_fcntl.py`
- `Lib/test/test_gzip.py`
- `Lib/test/test_importlib/util.py`
- `Lib/test/test_inspect/inspect_fodder2.py`
- `Lib/test/test_ioctl.py`
- `Lib/test/test_memoryview.py`
- `Lib/test/test_ordered_dict.py`
- `Lib/test/test_platform.py`
- `Lib/test/test_plistlib.py`
- `Lib/test/test_str.py`
- `Lib/test/test_sys.py`
- `Lib/test/test_time.py`
- `Lib/test/test_tools/test_msgfmt.py`
- `Lib/test/test_wave.py`
- `Lib/test/test_xml_etree_c.py`
- `Lib/test/test_xpickle.py`
- `Lib/test/test_zipimport.py`
- `Lib/test/test_zoneinfo/test_zoneinfo.py`
- `Lib/test/xpickle_worker.py`
- `Lib/wave.py`
- `PC/layout/support/constants.py`
- `Parser/asdl.py`
- `Tools/clinic/libclinic/dsl_parser.py`
- `Tools/clinic/libclinic/function.py`
- `Tools/i18n/msgfmt.py`
- `Tools/scripts/summarize_stats.py`
- `Tools/tz/zdump.py`
- `Tools/wasm/wasm_build.py`
