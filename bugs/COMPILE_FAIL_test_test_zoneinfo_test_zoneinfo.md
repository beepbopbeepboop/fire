# COMPILE_FAIL: Lib/test/test_zoneinfo/test_zoneinfo.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py: In function '_alloc_ZoneInfoData':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py:1296:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1296 |                 (datetime(2019, 10, 26), BST, NORMAL),
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py: In function '_alloc_ZoneOffset':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py:1310:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1310 |             tzstr = "AEST-10AEDT,M10.1.0/2,M4.1.0/3"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py: In function '_alloc_ZoneTransition':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py:1324:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1324 |                 (datetime(2019, 4, 7, 3, 0, fold=1), AEST, NORMAL),
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py: In function 'setUpModule':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py:2279:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
 2279 |             PPT = ZoneOffset("PPT", timedelta(hours=-7), ONE_H)
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py: In function 'tearDownModule':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py:62:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   62 | class CustomError(Exception):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py:61:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   61 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py: In function 'TzPathUserMixin_tzpath':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py:66:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   66 | class TzPathUserMixin:
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py:64:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   64 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py: In function 'TzPathUserMixin_block_tzdata':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py:85:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   85 |         with contextlib.ExitStack() as stack:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py:83:9: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   83 | 
      |         ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py: In function 'TzPathUserMixin_setUp':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py:103:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  103 |     class DatetimeSubclass(datetime):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py:101:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
  101 |     """
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py:100:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  100 |     Replaces all ZoneTransition transition dates with a datetime subclass.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo.py:99:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   99 |     """
... (36956 more lines)
```

Exit code: 1
Elapsed: 14.71s
