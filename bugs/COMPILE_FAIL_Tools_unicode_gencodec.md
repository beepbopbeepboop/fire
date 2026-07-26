# COMPILE_FAIL: Tools/unicode/gencodec.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py:33:11: warning: unused variable '_tag' [-Wunused-variable]
   33 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py:38:11: warning: unused variable '_tag' [-Wunused-variable]
   38 | MISSING_CODE = -1
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py:43:11: warning: unused variable '_tag' [-Wunused-variable]
   43 |                    r'\s*'
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py:58:11: warning: unused variable '_tag' [-Wunused-variable]
   58 |         return MISSING_CODE
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py:67:13: warning: unused variable '_tag' [-Wunused-variable]
   67 |     l = [x for x in l if x != MISSING_CODE]
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py: In function 'parsecodes_132aaf':
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py:68:1: warning: label 'bb_21' defined but not used [-Wunused-label]
   68 |     if len(l) == 1:
      | ^   ~
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py:246:10: warning: unused variable '_t34' [-Wunused-variable]
  246 |             append('    %a' % mapchar)
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py:218:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  218 |         if mapkey > maxkey:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py:211:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  211 |         if isinstance(mapkey, tuple):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py: In function 'readmap_584a43':
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py:183:7: warning: variable '_t94' set but not used [-Wunused-but-set-variable]
  183 |             else:
      |       ^   
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py:181:7: warning: variable '_t92' set but not used [-Wunused-but-set-variable]
  181 |             if splits == 0:
      |       ^   
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py:154:11: warning: variable '_t66' set but not used [-Wunused-but-set-variable]
  154 |     mappings = sorted(map.items())
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py:150:11: warning: variable '_t63' set but not used [-Wunused-but-set-variable]
  150 |         append("%s = {" % varname)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py:146:11: warning: variable '_t60' set but not used [-Wunused-but-set-variable]
  146 |         splits = 1
      |           ^~~~
... (249 more lines)
```

Exit code: 1
Elapsed: 14.01s
