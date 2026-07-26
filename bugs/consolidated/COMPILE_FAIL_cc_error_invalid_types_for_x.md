# COMPILE_FAIL: CC ERROR: invalid types for 'X'

**73 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py: In function '_alloc__Database':
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:52:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   52 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py: In function '_Database___init__':
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:277:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  277 |             self._commit()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:275:7: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
  275 |     def close(self):
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:274:7: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
  274 | 
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:273:11: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
  273 |             raise error('DBM object has already been closed') from None
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:272:11: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
  272 |         except TypeError:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:271:10: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
  271 |             return len(self._index)
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:270:7: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
  270 |         try:
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:269:10: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
  269 |     def __len__(self):
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:268:10: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
  268 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:267:11: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
  267 |     __iter__ = iterkeys
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:266:10: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
  266 |             raise error('DBM object has already been closed') from None
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:265:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
  265 |         except TypeError:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:264:10: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
  264 |             return iter(self._index)
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:263:7: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
  263 |         try:
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:262:10: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
  262 |     def iterkeys(self):
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:261:10: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
  261 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:260:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
  260 |                 raise
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:259:10: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
  259 |             else:
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:258:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
  258 |                 raise error('DBM object has already been closed') from None
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/dbm/dumb.py:257:10: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
  257 |             if self._index is None:
      |          ^  ~
/Users/mrs/net/Pyt
```

## Affected files

- `Lib/dbm/dumb.py`
- `Lib/email/generator.py`
- `Lib/email/mime/base.py`
- `Lib/html/parser.py`
- `Lib/idlelib/searchengine.py`
- `Lib/idlelib/stackviewer.py`
- `Lib/idlelib/tooltip.py`
- `Lib/json/decoder.py`
- `Lib/re/_constants.py`
- `Lib/test/support/bytecode_helper.py`
- `Lib/test/test_baseexception.py`
- `Lib/test/test_c_locale_coercion.py`
- `Lib/test/test_class.py`
- `Lib/test/test_concurrent_futures/util.py`
- `Lib/test/test_ctypes/test_python_api.py`
- `Lib/test/test_decorators.py`
- `Lib/test/test_dictviews.py`
- `Lib/test/test_difflib.py`
- `Lib/test/test_doctest/test_doctest2.py`
- `Lib/test/test_docxmlrpc.py`
- `Lib/test/test_errno.py`
- `Lib/test/test_file.py`
- `Lib/test/test_fnmatch.py`
- `Lib/test/test_free_threading/test_mmap.py`
- `Lib/test/test_funcattrs.py`
- `Lib/test/test_future_stmt/test_future_flags.py`
- `Lib/test/test_gdb/util.py`
- `Lib/test/test_hash.py`
- `Lib/test/test_htmlparser.py`
- `Lib/test/test_http_cookiejar.py`
- `Lib/test/test_ipaddress.py`
- `Lib/test/test_mailbox.py`
- `Lib/test/test_minidom.py`
- `Lib/test/test_module/__init__.py`
- `Lib/test/test_multibytecodec.py`
- `Lib/test/test_nturl2path.py`
- `Lib/test/test_osx_env.py`
- `Lib/test/test_peg_generator/test_c_parser.py`
- `Lib/test/test_pkg.py`
- `Lib/test/test_popen.py`
- `Lib/test/test_poplib.py`
- `Lib/test/test_pyclbr.py`
- `Lib/test/test_queue.py`
- `Lib/test/test_secrets.py`
- `Lib/test/test_site.py`
- `Lib/test/test_smtplib.py`
- `Lib/test/test_socketserver.py`
- `Lib/test/test_sqlite3/test_dbapi.py`
- `Lib/test/test_stat.py`
- `Lib/test/test_strptime.py`
- `Lib/test/test_tcl.py`
- `Lib/test/test_textwrap.py`
- `Lib/test/test_tools/test_i18n.py`
- `Lib/test/test_ttk_textonly.py`
- `Lib/test/test_ucn.py`
- `Lib/test/test_unicode_file_functions.py`
- `Lib/test/test_unittest/test_discovery.py`
- `Lib/test/test_unittest/test_loader.py`
- `Lib/test/test_unittest/testmock/testcallable.py`
- `Lib/test/test_unittest/testmock/testmagicmethods.py`
- `Lib/test/test_unittest/testmock/testwith.py`
- `Lib/test/test_utf8_mode.py`
- `Lib/test/test_xmlrpc.py`
- `Lib/test/test_zlib.py`
- `Tools/build/generate_sre_constants.py`
- `Tools/c-analyzer/distutils/log.py`
- `Tools/c-analyzer/distutils/msvc9compiler.py`
- `Tools/c-analyzer/distutils/msvccompiler.py`
- `Tools/unicode/genmap_japanese.py`
- `Tools/unicode/genmap_korean.py`
- `Tools/unicode/genmap_schinese.py`
- `Tools/unicode/genmap_support.py`
- `Tools/unittestgui/unittestgui.py`
