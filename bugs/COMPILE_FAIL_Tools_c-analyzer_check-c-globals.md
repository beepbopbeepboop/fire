# COMPILE_FAIL: Tools/c-analyzer/check-c-globals.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py`

Note (2026-08-05): the "conflicting types for '_gimple_main'" error shown
below is now FIXED (commit 12ff719, see `bugs/hard/
CODEGEN_aliased_external_import_no_backing_symbol.md`). Re-testing today,
this file still fails to compile, but now with a completely different,
unrelated set of errors rooted in a transitively-imported module
(`Tools/c-analyzer/c_common/logging.py` — a redefinition conflict plus
"expected identifier or '(' before 'default'"). Not investigated as part
of the aliased-import-as-main work; left here as a regular (not "hard")
report since the remaining failure is an unrelated bug class.

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py:35:11: warning: unused variable '_tag' [-Wunused-variable]
   35 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py:40:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py:45:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py:60:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py:69:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py: In function 'parse_args_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py:169:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py:165:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py:52:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py: At top level:
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py:43:5: error: conflicting types for '_gimple_main'; have 'int(void)'
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py:19:9: note: previous declaration of '_gimple_main' with type 'int64_t()' {aka 'long long int()'}
   19 |         _cli_check(parser),
      |         ^~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py:59:13: warning: '_mojo_classattr_init' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py:87:15: warning: '_mojo_repr_dict' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py:58:15: warning: '_mojo_dispatch_repr' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py:49:12: warning: '_mojo_dispatch_is_dataclass' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py:44:19: warning: '_mojo_dispatch_fields' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py:39:13: warning: '_mojo_dispatch_setattr' defined but not used [-Wunused-function]
   39 |     main(cmd, cmd_kwargs)
      |             ^~~~~~~~~~~~~         
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/check-c-globals.py:34:16: warning: '_mojo_dispatch_getattr' defined but not used [-Wunused-function]
   34 | 
      |                ^                     
check-c-globals.ci:458:16: warning: 'id' defined but not used [-Wunused-function]
  458 | static int64_t id (int64_t x) { return x; }
      |                ^~
check-c-globals.ci:457:19: warning: '_Bool_items' defined but not used [-Wunused-function]
  457 | static MojoList * _Bool_items (int64_t a) { return mojo_list_new(); }
      |                   ^~~~~~~~~~~
check-c-globals.ci:456:15: warning: '_ReflectTable_in_dll' defined but not used [-Wunused-function]
  456 | static char * _ReflectTable_in_dll (int64_t a, int64_t b, char * c) { return (char *)dlsym((void *)b, c); }
      |               ^~~~~~~~~~~~~~~~~~~~
In file included from check-c-globals.ci:14:
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:396:12: warning: '_mojo_vprintf' defined but not used [-Wunused-function]
  396 | static int _mojo_vprintf(char *fmt, void *ap) {
      |            ^~~~~~~~~~~~~
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:392:16: warning: '_mojo_getline' defined but not used [-Wunused-function]
  392 | static ssize_t _mojo_getline(void *lp, void *n, void *f) {
      |                ^~~~~~~~~~~~~
... (4 more lines)
```

Exit code: 1
Elapsed: 14.59s
