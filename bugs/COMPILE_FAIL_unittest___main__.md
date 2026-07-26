# COMPILE_FAIL: Lib/unittest/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py:31:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py:36:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py:41:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py:56:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py:65:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py:146:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py:133:11: warning: variable 'os' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py:127:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py:123:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py:21:5: error: conflicting types for '_gimple_main'; have 'int(void)'
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py:11:9: note: previous declaration of '_gimple_main' with type 'int64_t()' {aka 'long long int()'}
   11 |     sys.argv[0] = executable + " -m unittest"
      |         ^~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py:37:13: warning: '_mojo_classattr_init' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py:83:15: warning: '_mojo_repr_dict' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py:54:15: warning: '_mojo_dispatch_repr' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py:45:12: warning: '_mojo_dispatch_is_dataclass' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py:40:19: warning: '_mojo_dispatch_fields' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/unittest/__main__.py:35:13: warning: '_mojo_dispatch_setattr' defined but not used [-Wunused-function]
__main__.ci:458:16: warning: 'id' defined but not used [-Wunused-function]
  458 | static int64_t id (int64_t x) { return x; }
      |                ^~
__main__.ci:457:19: warning: '_Bool_items' defined but not used [-Wunused-function]
  457 | static MojoList * _Bool_items (int64_t a) { return mojo_list_new(); }
      |                   ^~~~~~~~~~~
__main__.ci:456:15: warning: '_ReflectTable_in_dll' defined but not used [-Wunused-function]
  456 | static char * _ReflectTable_in_dll (int64_t a, int64_t b, char * c) { return (char *)dlsym((void *)b, c); }
      |               ^~~~~~~~~~~~~~~~~~~~
In file included from __main__.ci:14:
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:396:12: warning: '_mojo_vprintf' defined but not used [-Wunused-function]
  396 | static int _mojo_vprintf(char *fmt, void *ap) {
      |            ^~~~~~~~~~~~~
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:392:16: warning: '_mojo_getline' defined but not used [-Wunused-function]
  392 | static ssize_t _mojo_getline(void *lp, void *n, void *f) {
      |                ^~~~~~~~~~~~~
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:389:16: warning: '_mojo_getdelim' defined but not used [-Wunused-function]
  389 | static ssize_t _mojo_getdelim(void *lp, void *n, int d, void *f) {
      |                ^~~~~~~~~~~~~~

```

Exit code: 1
Elapsed: 14.17s
