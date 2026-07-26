# COMPILE_FAIL: Tools/unicode/genmap_japanese.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_japanese.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_support.py: In function 'genmap_support_BufferedFiller___init__':
/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_support.py:91:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   91 |                 m = self.decode_map
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_support.py:89:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   89 |         for i in range(256):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_support.py:88:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   88 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_support.py:87:14: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   87 |             self.fp.write(f"static const struct widedbcs_index {self.prefix}_decmap[256] = {{\n")
      |              ^~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_support.py:86:14: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   86 |         else:
      |              ^  
/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_support.py:85:14: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   85 |             self.fp.write(f"static const struct dbcs_index {self.prefix}_decmap[256] = {{\n")
      |              ^~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_support.py:84:14: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   84 |         if not wide:
      |              ^~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_support.py:83:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   83 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_support.py: In function 'genmap_support_BufferedFiller_mojo_write':
/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_support.py:28:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   28 |         if not self.cline:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_support.py:25:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   25 |             self.count += 1
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_support.py:55:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   55 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_support.py:45:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   45 |     filler_class = BufferedFiller
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_support.py:37:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   37 |             fp.write(f'{l}\n')
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_support.py:34:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   34 |     def printout(self, fp):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_support.py:27:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   27 |     def flush(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_support.py:23:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   23 |             self.clen += len(s)
... (1820 more lines)
```

Exit code: 1
Elapsed: 13.35s
