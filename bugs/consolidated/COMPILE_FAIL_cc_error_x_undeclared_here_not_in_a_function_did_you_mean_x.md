# COMPILE_FAIL: CC ERROR: 'X' undeclared here (not in a function); did you mean 'X'?

**4 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py: In function '_alloc_ZstdFile':
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:84:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   84 |             raise TypeError('file must be a file-like object '
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:242:38: error: 'ZstdFile_close' undeclared here (not in a function); did you mean 'ZstdFile_closed'?
  242 |         """
      |                                      ^             
      |                                      ZstdFile_closed
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:249:50: error: 'ZstdFile_read' undeclared here (not in a function); did you mean 'ZstdFile_read1'?
  249 |         if ret := self._buffer.readline():
      |                                                  ^            
      |                                                  ZstdFile_read1
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:259:51: error: 'ZstdFile_write' undeclared here (not in a function); did you mean 'ZstdFile_writable'?
  259 |             return self._pos
      |                                                   ^             
      |                                                   ZstdFile_writable
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py: In function 'ZstdFile___init__':
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:71:7: error: 'ZstdFile' has no member named '_compressor'
   71 |             self._compressor = ZstdCompressor(level=level, options=options,
      |       ^ 
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:73:7: error: 'ZstdFile' has no member named '_pos'
   73 |             self._pos = 0
      |       ^ 
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:97:1: warning: label 'bb_37' defined but not used [-Wunused-label]
   97 |         """Flush and close the file.
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:100:1: warning: label 'bb_36' defined but not used [-Wunused-label]
  100 |         any other operation on it will raise ValueError.
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:85:1: warning: label 'bb_25' defined but not used [-Wunused-label]
   85 |                             'or a str, bytes, or PathLike object')
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:138:1: warning: label 'bb_26' defined but not used [-Wunused-label]
  138 |     def flush(self, mode=FLUSH_BLOCK):
      | ^   ~
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:131:1: warning: label 'bb_35' defined but not used [-Wunused-label]
  131 |         length = _nbytes(data)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:120:1: warning: label 'bb_33' defined but not used [-Wunused-label]
  120 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:124:1: warning: label 'bb_34' defined but not used [-Wunused-label]
  124 |         Returns the number of uncompressed bytes written, which is
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:135:1: warning: label 'bb_32' defined but not used [-Wunused-label]
  135 |         self._pos += length
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:111:1: warning: label 'bb_31' defined but not used [-Wunused-label]
  111 |                 self._compressor = None
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:107:1: warning: label 'bb_30' defined but not used [-Wunused-label]
  107 |                     self._buffer.close()
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:102:1: warning: label 'bb_
```

## Affected files

- `Lib/compression/zstd/_zstdfile.py`
- `Lib/multiprocessing/managers.py`
- `Lib/multiprocessing/sharedctypes.py`
- `Lib/test/seq_tests.py`
