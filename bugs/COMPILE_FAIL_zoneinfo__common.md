# COMPILE_FAIL: Lib/zoneinfo/_common.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:40:11: warning: unused variable '_tag' [-Wunused-variable]
   40 |         time_size = 8
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:45:11: warning: unused variable '_tag' [-Wunused-variable]
   45 |         skip_bytes = (
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:50:11: warning: unused variable '_tag' [-Wunused-variable]
   50 |             + header.isstdcnt  # Standard/wall indicators
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:65:11: warning: unused variable '_tag' [-Wunused-variable]
   65 |     if timecnt:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:74:13: warning: unused variable '_tag' [-Wunused-variable]
   74 |     else:
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py: In function 'load_tzdata_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:222:11: warning: variable '_t50' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:212:7: warning: variable '_t41' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:210:10: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:209:10: warning: unused variable '_t38' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:194:10: warning: variable 'package_name' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:189:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:188:7: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:182:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:181:7: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:172:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  172 |     """Exception raised when a ZoneInfo key is not found."""
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py: In function '_alloc_load_data_get_abbr_env':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:59:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   59 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py: In function 'load_data_get_abbr':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:111:1: warning: label 'bb_4' defined but not used [-Wunused-label]
  111 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:105:1: warning: label 'bb_3' defined but not used [-Wunused-label]
  105 |         # {0: "LMT", 4: "AHST", 5: "HST", 9: "HDT"}
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:96:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   96 |         # Gets a string starting at idx and running until the next \x00
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_common.py:94:11: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
   94 | 
... (270 more lines)
```

Exit code: 1
Elapsed: 13.19s
