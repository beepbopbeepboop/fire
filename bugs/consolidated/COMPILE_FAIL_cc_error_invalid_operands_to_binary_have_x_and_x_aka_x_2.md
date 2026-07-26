# COMPILE_FAIL: CC ERROR: invalid operands to binary / (have 'X' and 'X' {aka 'X'})

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:52:11: warning: unused variable '_tag' [-Wunused-variable]
   52 |         self.assertEqual(res.stderr, '')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:57:11: warning: unused variable '_tag' [-Wunused-variable]
   57 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:62:11: warning: unused variable '_tag' [-Wunused-variable]
   62 |     snapshot_path = _get_snapshot_path(module.__name__)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:77:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:86:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py: In function '_extract_msgids_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:33:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   33 |             msgids.append(msgid_string)
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:32:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   32 |         if msgid_string:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py: In function '_get_snapshot_path_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:38:13: error: invalid operands to binary / (have 'char *' and 'int64_t' {aka 'long long int'})
   38 |     return Path(TEST_HOME_DIR) / 'translationdata' / module_name / 'msgids.txt'
      |             ^
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py: In function 'TestTranslationsBase_assertMsgidsEqual':
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:80:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:78:11: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:77:11: warning: variable 'snapshot' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:76:7: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:75:7: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:74:10: warning: variable 'snapshot_path' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:73:10: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:72:11: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:71:10: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:70:10: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:69:11: warning: variable 'msgids' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/support/i18n_helper.py:68:10: warning: variable '_t25' set but not used [-Wunu
```

## Affected files

- `Lib/test/support/i18n_helper.py`
