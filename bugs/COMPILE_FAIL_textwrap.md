# COMPILE_FAIL: Lib/textwrap.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/textwrap.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/textwrap.py: In function '_alloc_TextWrapper':
/Users/mrs/net/Python-3.14.6/Lib/textwrap.py:58:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   58 |       drop_whitespace (default: true)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/textwrap.py: In function 'TextWrapper___init__':
/Users/mrs/net/Python-3.14.6/Lib/textwrap.py:306:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  306 |             if self.drop_whitespace and cur_line and cur_line[-1].strip() == '':
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/textwrap.py:304:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
  304 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/textwrap.py:303:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  303 |                 cur_len = sum(map(len, cur_line))
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/textwrap.py:302:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  302 |                 self._handle_long_word(chunks, cur_line, cur_len, width)
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/textwrap.py:301:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  301 |             if chunks and len(chunks[-1]) > width:
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/textwrap.py:300:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  300 |             # fit on *any* line (not just this one).
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/textwrap.py:299:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  299 |             # The current line is full, and the next chunk is too big to
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/textwrap.py:298:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  298 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/textwrap.py:297:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  297 |                     break
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/textwrap.py:296:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  296 |                 else:
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/textwrap.py:295:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  295 |                 # Nope, this line is full.
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/textwrap.py:294:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  294 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/textwrap.py:293:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  293 |                     cur_len += l
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/textwrap.py: In function 'TextWrapper__munge_whitespace':
/Users/mrs/net/Python-3.14.6/Lib/textwrap.py:156:1: warning: label 'bb_6' defined but not used [-Wunused-label]
  156 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/textwrap.py:160:1: warning: label 'bb_5' defined but not used [-Wunused-label]
... (1785 more lines)
```

Exit code: 1
Elapsed: 13.37s
