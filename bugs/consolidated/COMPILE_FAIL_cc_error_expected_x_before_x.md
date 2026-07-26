# COMPILE_FAIL: CC ERROR: expected 'X' before 'X'

**85 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/cProfile.py:1998:16: error: expected '{' before 'auto'
/Users/mrs/net/Python-3.14.6/Lib/cProfile.py:1998:16: error: multiple storage classes in declaration specifiers
/Users/mrs/net/Python-3.14.6/Lib/cProfile.py:2001:3: error: 'auto' in empty declaration
In file included from /opt/local/lib/gcc15/gcc/aarch64-apple-darwin25/15.2.0/include-fixed/_stdio.h:173,
                 from /opt/local/lib/gcc15/gcc/aarch64-apple-darwin25/15.2.0/include-fixed/stdio.h:75,
                 from cProfile.ci:8:
/Users/mrs/net/Python-3.14.6/Lib/cProfile.py:2488:7: error: expected identifier or '(' before numeric constant
/Users/mrs/net/Python-3.14.6/Lib/cProfile.py:2489:7: error: expected identifier or '(' before numeric constant
/Users/mrs/net/Python-3.14.6/Lib/cProfile.py:2490:7: error: expected identifier or '(' before numeric constant
/Users/mrs/net/Python-3.14.6/Lib/cProfile.py:2880:15: error: expected '{' before ';' token
/Users/mrs/net/Python-3.14.6/Lib/cProfile.py:2880:11: error: two or more data types in declaration specifiers
/Users/mrs/net/Python-3.14.6/Lib/cProfile.py:3264:4: error: expected identifier before numeric constant
/Users/mrs/net/Python-3.14.6/Lib/cProfile.py:3265:3: error: expected '}' before '.' token
/Users/mrs/net/Python-3.14.6/Lib/cProfile.py:2984:37: note: to match this '{'
/Users/mrs/net/Python-3.14.6/Lib/cProfile.py:3901:9: error: 'Error' redeclared as different kind of symbol
/Users/mrs/net/Python-3.14.6/Lib/cProfile.py:406:3: note: previous declaration of 'Error' with type 'Error'
/Users/mrs/net/Python-3.14.6/Lib/io.py:5:7: error: expected identifier or '(' before numeric constant
    5 | defines the basic interface to a stream. Note, however, that there is no
      |       ^~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/io.py:6:7: error: expected identifier or '(' before numeric constant
    6 | separation between reading and writing to streams; implementations are
      |       ^~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/io.py:7:7: error: expected identifier or '(' before numeric constant
    7 | allowed to raise an OSError if they do not support a given operation.
      |       ^~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/io.py:43:4: error: expected identifier before numeric constant
   43 | 
      |    ^       
/Users/mrs/net/Python-3.14.6/Lib/io.py:44:3: error: expected '}' before '.' token
   44 | __all__ = ["BlockingIOError", "open", "open_code", "IOBase", "RawIOBase",
      |   ^
/Users/mrs/net/Python-3.14.6/Lib/io.py:39:33: note: to match this '{'
   39 |               "Mark Russell <mark.russell@zen.co.uk>, "
      |                                 ^
/Users/mrs/net/Python-3.14.6/Lib/abc.py: In function 'abstractmethod_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/abc.py:71:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   71 |     Deprecated, use 'property' with 'abstractmethod' instead:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/abc.py: In function 'abc_abstractclassmethod___init__':
/Users/mrs/net/Python-3.14.6/Lib/abc.py:38:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   38 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/abc.py:36:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   36 |             def my_abstract_classmethod(cls, ...):
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/abc.py:35:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   35 |             @abstractmethod
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/abc.py:34:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   34 |             @classmethod
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/abc.py:33:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   33 |         class C(ABC):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/abc.py:32:11: warnin
```

## Affected files

- `Lib/bz2.py`
- `Lib/cProfile.py`
- `Lib/calendar.py`
- `Lib/code.py`
- `Lib/codecs.py`
- `Lib/codeop.py`
- `Lib/compileall.py`
- `Lib/contextlib.py`
- `Lib/copy.py`
- `Lib/copyreg.py`
- `Lib/csv.py`
- `Lib/dis.py`
- `Lib/doctest.py`
- `Lib/enum.py`
- `Lib/filecmp.py`
- `Lib/fileinput.py`
- `Lib/fnmatch.py`
- `Lib/fractions.py`
- `Lib/ftplib.py`
- `Lib/functools.py`
- `Lib/genericpath.py`
- `Lib/getpass.py`
- `Lib/gettext.py`
- `Lib/glob.py`
- `Lib/gzip.py`
- `Lib/imaplib.py`
- `Lib/inspect.py`
- `Lib/ipaddress.py`
- `Lib/locale.py`
- `Lib/lzma.py`
- `Lib/mailbox.py`
- `Lib/mimetypes.py`
- `Lib/modulefinder.py`
- `Lib/netrc.py`
- `Lib/ntpath.py`
- `Lib/nturl2path.py`
- `Lib/optparse.py`
- `Lib/os.py`
- `Lib/pickle.py`
- `Lib/pickletools.py`
- `Lib/pkgutil.py`
- `Lib/plistlib.py`
- `Lib/poplib.py`
- `Lib/posixpath.py`
- `Lib/pprint.py`
- `Lib/profile.py`
- `Lib/pstats.py`
- `Lib/pty.py`
- `Lib/py_compile.py`
- `Lib/pyclbr.py`
- `Lib/queue.py`
- `Lib/quopri.py`
- `Lib/random.py`
- `Lib/rlcompleter.py`
- `Lib/runpy.py`
- `Lib/sched.py`
- `Lib/shelve.py`
- `Lib/shutil.py`
- `Lib/signal.py`
- `Lib/smtplib.py`
- `Lib/socket.py`
- `Lib/socketserver.py`
- `Lib/sre_compile.py`
- `Lib/sre_constants.py`
- `Lib/sre_parse.py`
- `Lib/ssl.py`
- `Lib/subprocess.py`
- `Lib/symtable.py`
- `Lib/tabnanny.py`
- `Lib/tarfile.py`
- `Lib/tempfile.py`
- `Lib/test/test__colorize.py`
- `Lib/test/test_external_inspection.py`
- `Lib/test/test_global.py`
- `Lib/test/test_pyrepl/test_interact.py`
- `Lib/test/test_sqlite3/test_cli.py`
- `Lib/threading.py`
- `Lib/timeit.py`
- `Lib/trace.py`
- `Lib/tracemalloc.py`
- `Lib/turtle.py`
- `Lib/types.py`
- `Lib/typing.py`
- `Lib/uuid.py`
- `Lib/webbrowser.py`
