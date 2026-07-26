# COMPILE_FAIL: Lib/tomllib/_parser.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py: In function '_alloc_Flags':
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py:106:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  106 |                 args = doc, *args
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py: In function '_alloc_NestedDict':
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py:120:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  120 |         else:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py: In function '_alloc_Output':
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py:134:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  134 |     b = fp.read()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py: In function 'TOMLDecodeError___init__':
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py:124:1: warning: label 'bb_24' defined but not used [-Wunused-label]
  124 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py:122:1: warning: label 'bb_25' defined but not used [-Wunused-label]
  122 |         errmsg = f"{msg} (at {coord_repr})"
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py:124:1: warning: label 'bb_23' defined but not used [-Wunused-label]
  124 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py:119:1: warning: label 'bb_21' defined but not used [-Wunused-label]
  119 |             coord_repr = "end of document"
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py:117:1: warning: label 'bb_22' defined but not used [-Wunused-label]
  117 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py:117:1: warning: label 'bb_20' defined but not used [-Wunused-label]
  117 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py:111:1: warning: label 'bb_19' defined but not used [-Wunused-label]
  111 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py:116:1: warning: label 'bb_18' defined but not used [-Wunused-label]
  116 |             colno = pos - doc.rindex("\n", 0, pos)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py:109:1: warning: label 'bb_17' defined but not used [-Wunused-label]
  109 |             ValueError.__init__(self, *args)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py:114:1: warning: label 'bb_16' defined but not used [-Wunused-label]
  114 |             colno = pos + 1
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py:107:1: warning: label 'bb_15' defined but not used [-Wunused-label]
  107 |             if msg is not DEPRECATED_DEFAULT:  # type: ignore[comparison-overlap]
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_parser.py:102:1: warning: label 'bb_14' defined but not used [-Wunused-label]
  102 |             )
      | ^    
... (1504 more lines)
```

Exit code: 1
Elapsed: 17.11s
