# COMPILE_FAIL: Tools/c-analyzer/c_analyzer/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:117:11: warning: unused variable '_tag' [-Wunused-variable]
  117 |     return items, render
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:122:11: warning: unused variable '_tag' [-Wunused-variable]
  122 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:127:11: warning: unused variable '_tag' [-Wunused-variable]
  127 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:142:11: warning: unused variable '_tag' [-Wunused-variable]
  142 |                                 action='append_const', const=check)
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:151:13: warning: unused variable '_tag' [-Wunused-variable]
  151 |         pass
      |             ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_render_table_132aaf':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:392:10: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  392 |     if track_progress:
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:388:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  388 |         raise ValueError(f'unsupported fmt {fmt!r}')
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:387:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  387 |     except KeyError:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:384:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  384 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:383:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  383 |     verbosity = verbosity if verbosity is not None else 3
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:382:10: warning: variable 'div' set but not used [-Wunused-but-set-variable]
  382 |                 ):
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:380:10: warning: variable 'header' set but not used [-Wunused-but-set-variable]
  380 |                 formats=FORMATS,
      |          ^     
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_alloc_build_section_render_env':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:106:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  106 |         info = TABLE_SECTIONS[info]
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function 'build_section_render':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:129:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  129 |     default = False
... (841 more lines)
```

Exit code: 1
Elapsed: 14.16s
