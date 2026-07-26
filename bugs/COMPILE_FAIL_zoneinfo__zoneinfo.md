# COMPILE_FAIL: Lib/zoneinfo/_zoneinfo.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py: In function '_alloc__CalendarOffset':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py:106:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  106 |     def key(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py: In function '_alloc__DayOffset':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py:120:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  120 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py: In function '_alloc__TZStr':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py:134:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  134 |         ) and not isinstance(self._tz_after, _ttinfo):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py: In function '_alloc__ttinfo':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py:148:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  148 |                 tti = self._tz_after
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py: In function 'ZoneInfo___init_subclass__':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py:45:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   45 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py:43:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   43 |             instance = cls._weak_cache.setdefault(key, cls._new_instance(key))
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py:42:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   42 |         if instance is None:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py:41:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   41 |         instance = cls._weak_cache.get(key, None)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py:40:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   40 |     def __new__(cls, key):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py:39:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   39 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py:38:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   38 |         cls._weak_cache = weakref.WeakValueDictionary()
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py:37:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   37 |         cls._strong_cache = collections.OrderedDict()
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py:36:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   36 |     def __init_subclass__(cls):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py:35:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   35 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_zoneinfo.py:34:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   34 |     __module__ = "zoneinfo"
... (2884 more lines)
```

Exit code: 1
Elapsed: 13.35s
