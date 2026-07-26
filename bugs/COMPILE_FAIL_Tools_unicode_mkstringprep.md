# COMPILE_FAIL: Tools/unicode/mkstringprep.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py:63:11: warning: unused variable '_tag' [-Wunused-variable]
   63 |     m = re.match("----- (Start|End) Table ([A-Z](.[0-9])+) -----", l)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py:68:11: warning: unused variable '_tag' [-Wunused-variable]
   68 |             curname = m.group(2)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py:73:11: warning: unused variable '_tag' [-Wunused-variable]
   73 |             if not curname:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py:88:11: warning: unused variable '_tag' [-Wunused-variable]
   88 |         if len(fields) > 1:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py:97:13: warning: unused variable '_tag' [-Wunused-variable]
   97 |         end = int(end, 16)
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py: In function 'gen_category_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py:238:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  238 | # C.1.1 is a table with a single character
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py:235:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  235 |         return al
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py: In function 'gen_bidirectional_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py:32:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   32 |         else:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py:29:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   29 |                     single.append(i)
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py: In function 'compact_set_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py:63:14: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
   63 |     m = re.match("----- (Start|End) Table ([A-Z](.[0-9])+) -----", l)
      |              ^~~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py:60:8: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
   60 |     if l.startswith(("Hoffman & Blanchet", "RFC 3454")):
      |        ^~~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py:48:7: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
   48 | ############## Read the tables in the RFC #######################
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py:47:7: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
   47 | 
      |       ^   
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py: In function 'map_table_b2_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/unicode/mkstringprep.py:223:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
... (244 more lines)
```

Exit code: 1
Elapsed: 11.75s
