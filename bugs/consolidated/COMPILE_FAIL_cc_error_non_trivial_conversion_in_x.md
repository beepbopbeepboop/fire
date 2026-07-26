# COMPILE_FAIL: CC ERROR: non-trivial conversion in 'X'

**52 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py: In function '_alloc_BufferedSubFile':
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:113:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  113 |         self._partial.truncate()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py: In function 'BufferedSubFile___init__':
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:337:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  337 |             preamble = []
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:335:9: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  335 |                 return boundaryendRE.match(line, len(separator))
      |         ^  
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:334:14: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  334 |                     return None
      |              ^  
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:333:14: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  333 |                 if not line.startswith(separator):
      |              ^  
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:332:7: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  332 |             def boundarymatch(line):
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:331:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  331 |             separator = '--' + boundary
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:330:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  330 |             # preamble.
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:329:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  329 |             # this onto the input stream until we've scanned past the
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py: In function 'BufferedSubFile_push_eof_matcher':
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:71:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   71 |     def close(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:69:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   69 |         return self._eofstack.pop()
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:68:14: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   68 |     def pop_eof_matcher(self):
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py: In function 'BufferedSubFile_pop_eof_matcher':
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:76:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   76 |         self._partial.truncate()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:74:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   74 |         self.pushlines(self._partial.readlines())
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:73:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   73 |         self._partial.seek(0)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:72:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   72 |         # Don't forget any trailing partial line.
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:71:14: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   71 |     def close(self):
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py: In function 'BufferedSubFile_mojo_close':
/Users/mrs/net/Python-3.14.6/Lib/email/feedparser.py:86:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   86 |         line = self._
```

## Affected files

- `Lib/email/feedparser.py`
- `Lib/idlelib/help.py`
- `Lib/importlib/resources/readers.py`
- `Lib/multiprocessing/popen_spawn_win32.py`
- `Lib/multiprocessing/synchronize.py`
- `Lib/test/_test_atexit.py`
- `Lib/test/list_tests.py`
- `Lib/test/test_asyncio/test_base_events.py`
- `Lib/test/test_asyncio/test_events.py`
- `Lib/test/test_asyncio/test_locks.py`
- `Lib/test/test_asyncio/test_queues.py`
- `Lib/test/test_bufio.py`
- `Lib/test/test_capi/test_config.py`
- `Lib/test/test_capi/test_opt.py`
- `Lib/test/test_ctypes/test_arrays.py`
- `Lib/test/test_ctypes/test_cast.py`
- `Lib/test/test_ctypes/test_cfuncs.py`
- `Lib/test/test_ctypes/test_win32.py`
- `Lib/test/test_dictcomps.py`
- `Lib/test/test_dynamic.py`
- `Lib/test/test_fileinput.py`
- `Lib/test/test_free_threading/test_code.py`
- `Lib/test/test_free_threading/test_collections.py`
- `Lib/test/test_free_threading/test_csv.py`
- `Lib/test/test_free_threading/test_dict_watcher.py`
- `Lib/test/test_free_threading/test_func_annotations.py`
- `Lib/test/test_free_threading/test_gc.py`
- `Lib/test/test_free_threading/test_heapq.py`
- `Lib/test/test_free_threading/test_list.py`
- `Lib/test/test_free_threading/test_pickle.py`
- `Lib/test/test_genericalias.py`
- `Lib/test/test_importlib/test_locks.py`
- `Lib/test/test_int_literal.py`
- `Lib/test/test_interpreters/test_channels.py`
- `Lib/test/test_interpreters/test_queues.py`
- `Lib/test/test_interpreters/test_stress.py`
- `Lib/test/test_keywordonlyarg.py`
- `Lib/test/test_list.py`
- `Lib/test/test_pickletools.py`
- `Lib/test/test_readline.py`
- `Lib/test/test_robotparser.py`
- `Lib/test/test_scope.py`
- `Lib/test/test_sqlite3/test_regression.py`
- `Lib/test/test_sqlite3/test_userfunctions.py`
- `Lib/test/test_syslog.py`
- `Lib/test/test_tuple.py`
- `Lib/test/test_weakset.py`
- `Lib/test/test_winapi.py`
- `Lib/test/test_zipfile64.py`
- `Tools/gdb/libpython.py`
- `Tools/i18n/pygettext.py`
- `Tools/peg_generator/pegen/validator.py`
