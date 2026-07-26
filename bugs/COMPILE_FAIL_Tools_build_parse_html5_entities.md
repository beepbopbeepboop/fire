# COMPILE_FAIL: Tools/build/parse_html5_entities.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py:41:11: warning: unused variable '_tag' [-Wunused-variable]
   41 |     added = new.keys() - old.keys()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py:46:11: warning: unused variable '_tag' [-Wunused-variable]
   46 |     removed = old.keys() - new.keys()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py:51:11: warning: unused variable '_tag' [-Wunused-variable]
   51 |     changed = set()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py:66:11: warning: unused variable '_tag' [-Wunused-variable]
   66 |     # To do this we first sort in a case-sensitive way (so all the
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py:75:13: warning: unused variable '_tag' [-Wunused-variable]
   75 |           f'# {PAGE_URL}.\n'
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py: In function 'get_json_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py:189:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py:185:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py:184:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py:180:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py: In function 'create_dict_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py:65:10: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
   65 |     # looks like: ['Aacute', 'aacute', 'Aacute;', 'aacute;', ...]
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py:64:10: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
   64 |     # the uppercase version should come first so that the result
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py:35:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   35 |     for name, value in entities.items():
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py: In function 'compare_dicts_1ce6ce':
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py:41:8: error: assignment to 'MojoList *' from 'long int' makes pointer from integer without a cast [-Wint-conversion]
   41 |     added = new.keys() - old.keys()
      |        ^
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py:46:8: error: assignment to 'MojoList *' from 'long int' makes pointer from integer without a cast [-Wint-conversion]
   46 |     removed = old.keys() - new.keys()
      |        ^
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py:60:15: error: invalid operands to binary & (have 'MojoList *' and 'MojoList *')
   60 | def write_items(entities, file=sys.stdout):
      |               ^
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py:186:11: warning: variable 'item' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py:173:7: warning: variable '_t128' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/parse_html5_entities.py:42:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   42 |     if added:
... (56 more lines)
```

Exit code: 1
Elapsed: 13.86s
