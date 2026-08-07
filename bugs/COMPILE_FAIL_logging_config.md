# COMPILE_FAIL: Lib/logging/config.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/logging/config.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-06)

Re-ran; current error:

```
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:1130:1: error: invalid conversion in gimple call
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py:901:1: error: non-trivial conversion in 'integer_cst'  (x2)
```

The first is shared with `bugs/COMPILE_FAIL_logging_handlers.md`
(`config.py` imports `handlers.py`) — see that doc. `config.py`'s own
line 901 is a blank line, not executable code — same line-number
misattribution pattern seen elsewhere this session. Neither
root-caused further; not fixed.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py: In function '_alloc_ConvertingDict':
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py:185:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  185 |     However, don't disable children of named loggers, as that's probably not
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py: In function '_alloc_ConvertingList':
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py:199:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  199 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py: In function '_alloc_ConvertingTuple':
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py:213:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  213 |         log.setLevel(level)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py: In function 'fileConfig_7a6366':
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py:700:11: warning: variable '_t72' set but not used [-Wunused-but-set-variable]
  700 |                 config['fmt'] = config.pop('format')
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py:677:11: warning: variable '_t50' set but not used [-Wunused-but-set-variable]
  677 |                                          disable_existing)
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py:676:11: warning: variable '_t49' set but not used [-Wunused-but-set-variable]
  676 |                 _handle_existing_loggers(existing, child_loggers,
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py:673:11: warning: variable '_t46' set but not used [-Wunused-but-set-variable]
  673 |                 #        logger.propagate = True
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py:671:11: warning: variable '_t44' set but not used [-Wunused-but-set-variable]
  671 |                 #        logger.level = logging.NOTSET
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py:670:11: warning: variable '_t43' set but not used [-Wunused-but-set-variable]
  670 |                 #    if log in child_loggers:
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py:661:11: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
  661 |                                          '%r' % name) from e
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py:659:10: warning: unused variable '_t32' [-Wunused-variable]
  659 |                     except Exception as e:
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py:641:7: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
  641 |                 #We'll keep the list of existing loggers
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py:626:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  626 |                 #we don't want to lose the existing loggers,
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py: In function '_resolve_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py:130:10: warning: unused variable '_t31' [-Wunused-variable]
  130 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/config.py:101:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  101 |         try:
... (6807 more lines)
```

Exit code: 1
Elapsed: 10.52s
