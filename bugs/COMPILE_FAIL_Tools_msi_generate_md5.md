# COMPILE_FAIL: Tools/msi/generate_md5.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:31:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:36:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:41:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:56:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:65:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py: At top level:
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:125:9: error: conflicting types for '_gimple_main'; have 'int64_t(void)' {aka 'long long int(void)'}
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:11:9: note: previous declaration of '_gimple_main' with type 'int64_t()' {aka 'long long int()'}
   11 | 
      |         ^           
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py: In function '_gimple_main':
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:193:10: warning: variable '_t60' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:187:10: warning: variable '_t54' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:186:10: warning: variable '_t53' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:185:10: warning: variable '_t52' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:184:10: warning: variable '_t51' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:183:10: warning: variable '_t50' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:182:10: warning: variable '_t49' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:178:7: warning: variable '_t45' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:173:7: warning: variable '_t40' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:170:7: warning: variable '_t37' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:163:7: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:142:7: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:59:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:56:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py: In function '_gimple_main':
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:28:1: warning: control reaches end of non-void function [-Wreturn-type]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py: At top level:
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:83:15: warning: '_mojo_repr_dict' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:54:15: warning: '_mojo_dispatch_repr' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:45:12: warning: '_mojo_dispatch_is_dataclass' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:40:19: warning: '_mojo_dispatch_fields' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:35:13: warning: '_mojo_dispatch_setattr' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Tools/msi/generate_md5.py:30:16: warning: '_mojo_dispatch_getattr' defined but not used [-Wunused-function]
generate_md5.ci:458:16: warning: 'id' defined but not used [-Wunused-function]
  458 | static int64_t id (int64_t x) { return x; }
      |                ^~
generate_md5.ci:457:19: warning: '_Bool_items' defined but not used [-Wunused-function]
  457 | static MojoList * _Bool_items (int64_t a) { return mojo_list_new(); }
      |                   ^~~~~~~~~~~
generate_md5.ci:456:15: warning: '_ReflectTable_in_dll' defined but not used [-Wunused-function]
  456 | static char * _ReflectTable_in_dll (int64_t a, int64_t b, char * c) { return (char *)dlsym((void *)b, c); }
      |               ^~~~~~~~~~~~~~~~~~~~
... (11 more lines)
```

Exit code: 1
Elapsed: 13.84s
