# COMPILE_FAIL: Lib/test/test_tools/test_i18n.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py:112:11: warning: unused variable '_tag' [-Wunused-variable]
  112 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py:117:11: warning: unused variable '_tag' [-Wunused-variable]
  117 |     def get_stderr(self, module_content):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py:122:11: warning: unused variable '_tag' [-Wunused-variable]
  122 |            http://www.gnu.org/software/gettext/manual/gettext.html#Header-Entry
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py:137:11: warning: unused variable '_tag' [-Wunused-variable]
  137 |             self.assertIn("Content-Transfer-Encoding", header)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py:146:13: warning: unused variable '_tag' [-Wunused-variable]
  146 |     @unittest.skipIf(sys.platform.startswith('aix'),
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py: In function 'normalize_POT_file_replace':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py:489:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  489 |         _("foo")
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py: In function 'normalize_POT_file_584a43':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py:75:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
   75 |                 else:
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py:64:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   64 |         return headers
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py:53:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   53 |     script = Path(toolsdir, 'i18n', 'pygettext.py')
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py:50:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   50 | class Test_pygettext(unittest.TestCase):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py: In function 'Test_pygettext_get_header':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py:66:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   66 |     def get_msgids(self, data):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py:117:1: warning: label 'bb_11' defined but not used [-Wunused-label]
  117 |     def get_stderr(self, module_content):
      | ^   ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py:113:1: warning: label 'bb_10' defined but not used [-Wunused-label]
  113 |     def extract_docstrings_from_str(self, module_content):
      | ^   ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_i18n.py:108:1: warning: label 'bb_9' defined but not used [-Wunused-label]
  108 |             data = self.get_msgids(data)
... (4268 more lines)
```

Exit code: 1
Elapsed: 16.28s
