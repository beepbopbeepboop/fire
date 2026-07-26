# COMPILE_FAIL: Lib/compression/zstd/_zstdfile.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py: In function '_alloc_ZstdFile':
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:89:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   89 |                 self._fp,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:274:38: error: 'ZstdFile_close' undeclared here (not in a function); did you mean 'ZstdFile_closed'?
  274 | 
      |                                      ^             
      |                                      ZstdFile_closed
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:281:50: error: 'ZstdFile_read' undeclared here (not in a function); did you mean 'ZstdFile_read1'?
  281 |         """Return whether the file supports seeking."""
      |                                                  ^~~~~~       
      |                                                  ZstdFile_read1
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:291:51: error: 'ZstdFile_write' undeclared here (not in a function); did you mean 'ZstdFile_writable'?
  291 |         self._check_not_closed()
      |                                                   ^             
      |                                                   ZstdFile_writable
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py: In function 'ZstdFile___init__':
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
/Users/mrs/net/Python-3.14.6/Lib/compression/zstd/_zstdfile.py:102:1: warning: label 'bb_29' defined but not used [-Wunused-label]
... (1287 more lines)
```

Exit code: 1
Elapsed: 9.51s
