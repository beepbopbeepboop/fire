# COMPILE_FAIL: Lib/logging/handlers.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:431:11: warning: unused variable '_tag' [-Wunused-variable]
  431 |         """
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:436:11: warning: unused variable '_tag' [-Wunused-variable]
  436 |             timeTuple = time.gmtime(t)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:441:11: warning: unused variable '_tag' [-Wunused-variable]
  441 |             if dstNow != dstThen:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:456:11: warning: unused variable '_tag' [-Wunused-variable]
  456 |         self.rotate(self.baseFilename, dfn)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:465:13: warning: unused variable '_tag' [-Wunused-variable]
  465 |     """
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py: In function 'BaseRotatingHandler___init__':
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:782:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  782 |     LOG_KERN      = 0       #  kernel messages
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:780:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  780 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:779:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
  779 |     LOG_DEBUG     = 7       #  debug-level messages
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:778:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  778 |     LOG_INFO      = 6       #  informational
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:777:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  777 |     LOG_NOTICE    = 5       #  normal but significant condition
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:776:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  776 |     LOG_WARNING   = 4       #  warning conditions
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:775:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  775 |     LOG_ERR       = 3       #  error conditions
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:774:25: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  774 |     LOG_CRIT      = 2       #  critical conditions
      |                         ^~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:773:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  773 |     LOG_ALERT     = 1       #  action must be taken immediately
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:772:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
... (8687 more lines)
```

Exit code: 1
Elapsed: 10.37s
