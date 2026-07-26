# COMPILE_FAIL: CC ERROR: invalid operands to binary % (have 'X' and 'X' {aka 'X'})

**20 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:25:11: warning: unused variable '_tag' [-Wunused-variable]
   25 |     yield self
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:30:11: warning: unused variable '_tag' [-Wunused-variable]
   30 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:35:11: warning: unused variable '_tag' [-Wunused-variable]
   35 |     Optional decode (default False) is passed through to .get_payload().
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:50:11: warning: unused variable '_tag' [-Wunused-variable]
   50 |     for subpart in msg.walk():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:59:13: warning: unused variable '_tag' [-Wunused-variable]
   59 |         fp = sys.stdout
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function 'walk_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:149:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:143:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:142:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function 'body_line_iterator_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:40:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   40 |             yield from StringIO(payload)
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:38:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   38 |         payload = subpart.get_payload(decode=decode)
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function 'typed_subpart_iterator_132aaf':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:47:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   47 |     "text".  Optional 'subtype' is the MIME subtype to match against; if
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:45:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   45 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function '_structure_7a6366':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:63:15: error: invalid operands to binary % (have 'char *' and 'int64_t' {aka 'long long int'})
   63 |         print(' [%s]' % msg.get_default_type(), file=fp)
      |               ^
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:89:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:58:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   58 |     if fp is None:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:78:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:26:13: warning: '_mojo_classattr_init' defined but not used [-Wunused-function]
   26 |     if self.is_multipart():
      |             ^~~~~~~~~~~~~~~     
/Users/mrs/net/Python-3.14.6/Lib/e
```

## Affected files

- `Lib/email/iterators.py`
- `Lib/idlelib/autoexpand.py`
- `Lib/idlelib/colorizer.py`
- `Lib/multiprocessing/spawn.py`
- `Lib/test/support/asyncore.py`
- `Lib/test/test_curses.py`
- `Lib/test/test_faulthandler.py`
- `Lib/test/test_importlib/threaded_import_hangers.py`
- `Lib/test/tf_inherit_check.py`
- `Lib/unittest/main.py`
- `Lib/urllib/error.py`
- `Modules/_decimal/tests/bench.py`
- `Objects/typeslots.py`
- `PCbuild/field3.py`
- `Programs/freeze_test_frozenmain.py`
- `Tools/build/generate_re_casefix.py`
- `Tools/clinic/libclinic/clanguage.py`
- `Tools/freeze/checkextensions_win32.py`
- `Tools/freeze/parsesetup.py`
- `Tools/freeze/winmakemakefile.py`
