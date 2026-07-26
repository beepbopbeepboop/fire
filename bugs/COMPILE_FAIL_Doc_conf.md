# COMPILE_FAIL: Doc/conf.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/conf.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Doc/conf.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Doc/conf.py:173:11: warning: unused variable '_tag' [-Wunused-variable]
  173 |     ('c:type', 'va_list'),
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/conf.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Doc/conf.py:178:11: warning: unused variable '_tag' [-Wunused-variable]
  178 |     ('c:type', '_Float16'),
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/conf.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Doc/conf.py:183:11: warning: unused variable '_tag' [-Wunused-variable]
  183 |     ('c:struct', 'statvfs'),
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/conf.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Doc/conf.py:198:11: warning: unused variable '_tag' [-Wunused-variable]
  198 |     ('envvar', 'HOME'),
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/conf.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Doc/conf.py:207:13: warning: unused variable '_tag' [-Wunused-variable]
  207 |     ('envvar', 'LC_MESSAGES'),
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Doc/conf.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/Doc/conf.py:230:3: error: 'nitpick_ignore' undeclared (first use in this function)
  230 | nitpick_ignore += [
      |   ^~~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Doc/conf.py:230:3: note: each undeclared identifier is reported only once for each function it appears in
/Users/mrs/net/Python-3.14.6/Doc/conf.py:463:3: error: 'rst_epilog' undeclared (first use in this function)
  463 |     rst_epilog += f"""\
      |   ^ ~~~~~~~~
/Users/mrs/net/Python-3.14.6/Doc/conf.py:605:3: error: 'ogp_custom_meta_tags' undeclared (first use in this function)
  605 |     ogp_custom_meta_tags += (
      |   ^ ~~~~~~~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Doc/conf.py:1841:10: warning: variable 'ogp_image' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/conf.py:1835:11: warning: variable '_t1238' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/conf.py:1834:10: warning: variable '_t1237' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/conf.py:1814:10: warning: variable 'notfound_urls_prefix' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/conf.py:1795:10: warning: variable '_t1199' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/conf.py:1793:10: warning: variable '_t1197' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/conf.py:1780:11: warning: variable '_t1184' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/conf.py:1624:10: warning: variable '_t1028' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/conf.py:1622:10: warning: variable '_t1026' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/conf.py:1616:7: warning: variable '_t1020' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/conf.py:1600:10: warning: variable '_t1004' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/conf.py:1594:10: warning: variable '_t998' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/conf.py:1571:7: warning: variable '_t975' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/conf.py:1570:11: warning: variable '_t974' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/conf.py:1567:11: warning: variable '_t971' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/conf.py:1460:10: warning: variable '_t864' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/conf.py:1458:10: warning: variable '_t862' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/conf.py:1412:11: warning: variable '_t816' set but not used [-Wunused-but-set-variable]
... (58 more lines)
```

Exit code: 1
Elapsed: 5.35s
