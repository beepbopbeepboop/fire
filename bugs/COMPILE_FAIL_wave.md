# COMPILE_FAIL: Lib/wave.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/wave.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/wave.py:259:9: error: 'Error' redeclared as different kind of symbol
  259 |             self._data_seek_needed = 1
      |         ^   ~
/Users/mrs/net/Python-3.14.6/Lib/wave.py:5:3: note: previous declaration of 'Error' with type 'Error'
    5 | Reading WAVE files:
      |   ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/struct.py: In function '_alloc_Wave_read':
/Users/mrs/net/Python-3.14.6/Lib/struct.py:13:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   13 | from _struct import *
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/struct.py: In function '_alloc_Wave_write':
/Users/mrs/net/Python-3.14.6/Lib/struct.py:27:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/struct.py: In function '_alloc__Chunk':
/Users/mrs/net/Python-3.14.6/Lib/struct.py:41:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/wave.py: In function '_Chunk___init__':
/Users/mrs/net/Python-3.14.6/Lib/wave.py:133:1: warning: label 'bb_19' defined but not used [-Wunused-label]
  133 |         """Return the name (ID) of the current chunk."""
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/wave.py:131:1: warning: label 'bb_22' defined but not used [-Wunused-label]
  131 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/wave.py:143:1: warning: label 'bb_21' defined but not used [-Wunused-label]
  143 |     def seek(self, pos, whence=0):
      | ^   ~
/Users/mrs/net/Python-3.14.6/Lib/wave.py:134:1: warning: label 'bb_18' defined but not used [-Wunused-label]
  134 |         return self.chunkname
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/wave.py:133:1: warning: label 'bb_16' defined but not used [-Wunused-label]
  133 |         """Return the name (ID) of the current chunk."""
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/wave.py:130:1: warning: label 'bb_17' defined but not used [-Wunused-label]
  130 |             self.seekable = True
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/wave.py:126:1: warning: label 'bb_15' defined but not used [-Wunused-label]
  126 |             self.offset = self.file.tell()
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/wave.py:146:1: warning: label 'bb_14' defined but not used [-Wunused-label]
  146 |         If the file is not seekable, this will result in an error.
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/wave.py:138:1: warning: label 'bb_13' defined but not used [-Wunused-label]
  138 |             try:
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/wave.py:133:1: warning: label 'bb_12' defined but not used [-Wunused-label]
  133 |         """Return the name (ID) of the current chunk."""
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/wave.py:141:1: warning: label 'bb_10' defined but not used [-Wunused-label]
  141 |                 self.closed = True
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/wave.py:138:1: warning: label 'bb_8' defined but not used [-Wunused-label]
... (3456 more lines)
```

Exit code: 1
Elapsed: 14.65s
