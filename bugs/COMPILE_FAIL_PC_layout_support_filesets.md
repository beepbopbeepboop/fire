# COMPILE_FAIL: PC/layout/support/filesets.py

Source file: `/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:48:11: warning: unused variable '_tag' [-Wunused-variable]
   48 |                 self._names.add(p[1:])
      |           ^   
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:53:11: warning: unused variable '_tag' [-Wunused-variable]
   53 |             elif p.startswith("."):
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:58:11: warning: unused variable '_tag' [-Wunused-variable]
   58 |     def _make_name(self, f):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:73:11: warning: unused variable '_tag' [-Wunused-variable]
   73 |     if recurse:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:82:13: warning: unused variable '_tag' [-Wunused-variable]
   82 |                 )
      |             ^   
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py: In function 'FileStemSet___init__':
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:182:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:180:10: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:179:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:178:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:177:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:176:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:175:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:174:7: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:173:14: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:172:14: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:171:14: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:170:14: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:169:13: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:168:13: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:24:1: error: invalid conversion in gimple call
   24 |     def _make_name(self, f):
      | ^
int64_t

void *

_t12 = mojo_map (_t10, patterns);
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py: In function 'FileStemSet__make_name':
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:36:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   36 | class FileNameSet(FileStemSet):
      | ^~~~
/Users/mrs/net/Python-3.14.6/PC/layout/support/filesets.py:34:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   34 | 
... (556 more lines)
```

Exit code: 1
Elapsed: 13.75s
