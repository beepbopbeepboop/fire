# COMPILE_FAIL: PC/layout/support/logging.py

Source file: `/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py: In function '_alloc_BraceMessage':
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:27:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   27 | 
      | ^   
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py: In function 'public_0c85c9':
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:94:7: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py: In function 'configure_logger_0c85c9':
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:132:11: warning: variable '_t106' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:131:11: warning: variable '_t105' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:129:11: warning: variable '_t103' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:128:11: warning: variable '_t102' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:126:11: warning: variable '_t100' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:125:11: warning: variable '_t99' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:122:11: warning: variable '_t96' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:116:11: warning: variable '_t90' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:108:11: warning: variable '_t82' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:107:11: warning: variable '_t81' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:105:11: warning: variable '_t79' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:104:11: warning: variable '_t78' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:102:11: warning: variable '_t76' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:101:11: warning: variable '_t75' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:98:11: warning: variable '_t72' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:91:11: warning: variable '_t66' set but not used [-Wunused-but-set-variable]
   91 | @public
      |           ^   
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:29:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   29 |     LOG.level = logging.DEBUG
      |           ^~~
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py: In function 'logging_BraceMessage___init__':
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:67:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   67 | @public
      | ^~~~
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:65:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   65 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:64:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   64 |     return LOG.debug(BraceMessage(msg, *args, **kwargs))
      |          ^~~
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:63:14: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   63 | def log_debug(msg, *args, **kwargs):
      |              ^~~
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:62:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   62 | @public
      |           ^  
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:61:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   61 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/PC/layout/support/logging.py:60:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   60 | 
... (327 more lines)
```

Exit code: 1
Elapsed: 13.58s
