# COMPILE_FAIL: Lib/re/_compiler.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:70:11: warning: unused variable '_tag' [-Wunused-variable]
   70 |                 lo = tolower(av)
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:75:11: warning: unused variable '_tag' [-Wunused-variable]
   75 |                     emit(OP_UNICODE_IGNORE[op])
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:80:11: warning: unused variable '_tag' [-Wunused-variable]
   80 |                     if op is NOT_LITERAL:
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:95:11: warning: unused variable '_tag' [-Wunused-variable]
   95 |                     emit(IN_LOC_IGNORE)
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:104:13: warning: unused variable '_tag' [-Wunused-variable]
  104 |                 code[skip] = _len(code) - skip
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py: In function '_compile_06e87d':
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:59:11: warning: variable 'fixes' set but not used [-Wunused-but-set-variable]
   59 |         if op in LITERAL_CODES:
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:58:11: warning: variable '_var_tolower' set but not used [-Wunused-but-set-variable]
   58 |     for op, av in pattern:
      |           ^~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:57:11: warning: variable 'iscased' set but not used [-Wunused-but-set-variable]
   57 |             tolower = _sre.ascii_tolower
      |           ^ ~~~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:56:11: warning: variable 'ASSERT_CODES' set but not used [-Wunused-but-set-variable]
   56 |             iscased = _sre.ascii_iscased
      |           ^ ~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:54:11: warning: variable 'SUCCESS_CODES' set but not used [-Wunused-but-set-variable]
   54 |             fixes = _EXTRA_CASES
      |           ^ ~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:52:11: warning: variable 'REPEATING_CODES' set but not used [-Wunused-but-set-variable]
   52 |             iscased = _sre.unicode_iscased
      |           ^ ~~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:50:11: warning: variable 'LITERAL_CODES' set but not used [-Wunused-but-set-variable]
   50 |     if flags & SRE_FLAG_IGNORECASE and not flags & SRE_FLAG_LOCALE:
      |           ^~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:47:11: warning: variable '_len' set but not used [-Wunused-but-set-variable]
   47 |     iscased = None
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:45:11: warning: variable 'emit' set but not used [-Wunused-but-set-variable]
   45 |     SUCCESS_CODES = _SUCCESS_CODES
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py: In function '_compile_charset_132aaf':
... (1377 more lines)
```

Exit code: 1
Elapsed: 11.63s
