# COMPILE_FAIL: CC ERROR: request for member 'X' in something not a structure or union

**59 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

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
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/glossary_search.py:53:11: warning: variable '_t12' set but not u
```

## Affected files

- `Doc/tools/extensions/glossary_search.py`
- `Lib/idlelib/idle_test/test_editmenu.py`
- `Lib/idlelib/idle_test/test_help.py`
- `Lib/idlelib/idle_test/test_outwin.py`
- `Lib/idlelib/idle_test/test_zzdummy.py`
- `Lib/idlelib/multicall.py`
- `Lib/idlelib/runscript.py`
- `Lib/multiprocessing/popen_fork.py`
- `Lib/numbers.py`
- `Lib/pathlib/_os.py`
- `Lib/selectors.py`
- `Lib/sysconfig/__main__.py`
- `Lib/test/_test_embed_structseq.py`
- `Lib/test/libregrtest/single.py`
- `Lib/test/support/smtpd.py`
- `Lib/test/test___all__.py`
- `Lib/test/test_asyncio/test_eager_task_factory.py`
- `Lib/test/test_asyncio/test_futures2.py`
- `Lib/test/test_asyncio/test_graph.py`
- `Lib/test/test_asyncio/test_sendfile.py`
- `Lib/test/test_asyncio/test_taskgroups.py`
- `Lib/test/test_asyncio/test_tools.py`
- `Lib/test/test_asyncio/test_unix_events.py`
- `Lib/test/test_asyncio/test_windows_utils.py`
- `Lib/test/test_code_module.py`
- `Lib/test/test_ctypes/test_find.py`
- `Lib/test/test_defaultdict.py`
- `Lib/test/test_epoll.py`
- `Lib/test/test_frame.py`
- `Lib/test/test_generator_stop.py`
- `Lib/test/test_graphlib.py`
- `Lib/test/test_json/test_recursion.py`
- `Lib/test/test_kqueue.py`
- `Lib/test/test_modulefinder.py`
- `Lib/test/test_pydoc/module_none.py`
- `Lib/test/test_pyrepl/support.py`
- `Lib/test/test_quopri.py`
- `Lib/test/test_raise.py`
- `Lib/test/test_runpy.py`
- `Lib/test/test_script_helper.py`
- `Lib/test/test_select.py`
- `Lib/test/test_smtpnet.py`
- `Lib/test/test_string/test_templatelib.py`
- `Lib/test/test_symtable.py`
- `Lib/test/test_timeout.py`
- `Lib/test/test_winreg.py`
- `Lib/test/test_wmi.py`
- `Lib/test/test_zipfile/_path/test_complexity.py`
- `Lib/test/test_zipfile/_path/test_path.py`
- `Lib/turtledemo/__main__.py`
- `PC/layout/support/appxmanifest.py`
- `Tools/c-analyzer/c_analyzer/__main__.py`
- `Tools/c-analyzer/c_common/clsutil.py`
- `Tools/c-analyzer/c_common/fsutil.py`
- `Tools/c-analyzer/cpython/__main__.py`
- `Tools/c-analyzer/distutils/_msvccompiler.py`
- `Tools/freeze/test/freeze.py`
- `Tools/importbench/importbench.py`
- `Tools/peg_generator/pegen/__main__.py`
