# COMPILE_FAIL: PC/layout/main.py

Source file: `/Users/mrs/net/Python-3.14.6/PC/layout/main.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/PC/layout/main.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/PC/layout/main.py:169:11: warning: unused variable '_tag' [-Wunused-variable]
  169 |         alias.extend([
      |           ^~~~
/Users/mrs/net/Python-3.14.6/PC/layout/main.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/PC/layout/main.py:174:11: warning: unused variable '_tag' [-Wunused-variable]
  174 |             "pythonw{}t".format(VER_DOT),
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/PC/layout/main.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/PC/layout/main.py:179:11: warning: unused variable '_tag' [-Wunused-variable]
  179 |         yield from in_build(source, new_name=a)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/PC/layout/main.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/PC/layout/main.py:194:11: warning: unused variable '_tag' [-Wunused-variable]
  194 |     if ns.include_stable:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/PC/layout/main.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/PC/layout/main.py:203:13: warning: unused variable '_tag' [-Wunused-variable]
  203 |         yield dest, src
      |             ^~~~
/Users/mrs/net/Python-3.14.6/PC/layout/main.py: In function 'copy_if_modified_1ce6ce':
/Users/mrs/net/Python-3.14.6/PC/layout/main.py:558:11: warning: variable '_t42' set but not used [-Wunused-but-set-variable]
  558 |         help="Specify the target architecture",
      |           ^~~~
/Users/mrs/net/Python-3.14.6/PC/layout/main.py:557:11: warning: variable '_t41' set but not used [-Wunused-but-set-variable]
  557 |         metavar="architecture",
      |           ^~~~
/Users/mrs/net/Python-3.14.6/PC/layout/main.py:555:10: warning: unused variable '_t39' [-Wunused-variable]
  555 |     parser.add_argument(
      |          ^~~~
/Users/mrs/net/Python-3.14.6/PC/layout/main.py:532:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
  532 |             log_info("Generating {}", ns.catalog)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/PC/layout/main.py:521:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  521 |                     if not c:
      |           ^  
/Users/mrs/net/Python-3.14.6/PC/layout/main.py:519:10: warning: unused variable '_t6' [-Wunused-variable]
  519 |                 ]
      |          ^  
/Users/mrs/net/Python-3.14.6/PC/layout/main.py: In function '_alloc_get_lib_layout__c_env':
/Users/mrs/net/Python-3.14.6/PC/layout/main.py:114:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  114 |         try:
      | ^   
/Users/mrs/net/Python-3.14.6/PC/layout/main.py: In function 'get_lib_layout__c':
/Users/mrs/net/Python-3.14.6/PC/layout/main.py:104:1: warning: label 'bb_17' defined but not used [-Wunused-label]
  104 |     for dest, src in rglob(ns.source / "Lib", "**/*", _c):
      | ^   ~
/Users/mrs/net/Python-3.14.6/PC/layout/main.py:111:1: warning: label 'bb_16' defined but not used [-Wunused-label]
  111 | 
... (1346 more lines)
```

Exit code: 1
Elapsed: 13.57s
