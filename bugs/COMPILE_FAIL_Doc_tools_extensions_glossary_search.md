# COMPILE_FAIL: Doc/tools/extensions/glossary_search.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:25:11: warning: unused variable '_tag' [-Wunused-variable]
   25 |     if app.builder.format != 'html' or app.builder.embedded:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:30:11: warning: unused variable '_tag' [-Wunused-variable]
   30 |     else:
      |           ^   
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:35:11: warning: unused variable '_tag' [-Wunused-variable]
   35 |             term = glossary_item[0].astext()
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:50:11: warning: unused variable '_tag' [-Wunused-variable]
   50 |     dest = Path(app.outdir, '_static', 'glossary.json')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:59:13: warning: unused variable '_tag' [-Wunused-variable]
   59 |     return {
      |             ^   
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py: In function 'process_glossary_nodes_61846e':
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:31:7: error: request for member 'glossary_terms' in something not a structure or union
   31 |         terms = app.env.glossary_terms = {}
      |       ^
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:197:11: warning: variable '_t45' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:196:11: warning: variable '_t44' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:193:11: warning: variable '_t41' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:188:11: warning: variable 'terms' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py: In function 'write_glossary_json_1ce6ce':
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:77:11: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:76:11: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:74:11: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:67:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:61:10: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
   61 |         'parallel_read_safe': True,
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:60:10: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
   60 |         'version': '1.0',
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:56:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
   56 |     app.connect('doctree-resolved', process_glossary_nodes)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:53:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   53 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py: In function 'setup_0c85c9':
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:70:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:69:10: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:66:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
... (49 more lines)
```

Exit code: 1
Elapsed: 8.78s
