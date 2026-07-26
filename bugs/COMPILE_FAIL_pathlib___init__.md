# COMPILE_FAIL: Lib/pathlib/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py: In function '_alloc__PathParents':
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:381:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  381 |     @property
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py: In function '_PathParents___init__':
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1116:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1116 |             target = self.with_segments(target_dir, name)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1114:7: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
 1114 |             target = target_dir / name
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1113:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
 1113 |         elif hasattr(target_dir, 'with_segments'):
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1112:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
 1112 |             raise ValueError(f"{self!r} has an empty name")
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1111:10: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
 1111 |         if not name:
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1110:7: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
 1110 |         name = self.name
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1109:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
 1109 |         """
      |          ^~ 
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1108:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
 1108 |         Copy this file or directory tree into the given existing directory.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1107:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
 1107 |         """
      |          ^~ 
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1106:7: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
 1106 |     def copy_into(self, target_dir, **kwargs):
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1105:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
 1105 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1104:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
 1104 |         return target.joinpath()  # Empty join to ensure fresh metadata.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1103:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
 1103 |         target._copy_from(self, **kwargs)
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1102:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
 1102 |         ensure_distinct_paths(self, target)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py: In function '_PathParents___len__':
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:68:1: warning: label 'bb_2' defined but not used [-Wunused-label]
... (34916 more lines)
```

Exit code: 1
Elapsed: 10.23s
