# COMPILE_FAIL: CC ERROR: 'X' has no member named 'X'

**379 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py: In function '_alloc_BPOIssue':
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py:52:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   52 |             prb = self.inliner.problematic(self.rawtext, self.rawtext, msg)
      | ^   
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py: In function '_alloc_GitHubIssue':
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py:66:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   66 |         "version": "1.0",
      | ^   
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py:80:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py:85:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py:90:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py:105:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py:114:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py: In function 'BPOIssue_run':
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py:20:13: error: 'BPOIssue' has no member named 'text'
   20 |         issue = self.text
      |             ^~
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py:24:14: error: 'BPOIssue' has no member named 'inliner'
   24 |             msg = self.inliner.reporter.error(
      |              ^~
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py:24:14: error: 'BPOIssue' has no member named 'reporter'
   24 |             msg = self.inliner.reporter.error(
      |              ^~
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py:29:14: error: 'BPOIssue' has no member named 'inliner'
   29 |             prb = self.inliner.problematic(self.rawtext, self.rawtext, msg)
      |              ^~
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py:29:14: error: 'BPOIssue' has no member named 'rawtext'
   29 |             prb = self.inliner.problematic(self.rawtext, self.rawtext, msg)
      |              ^~
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py:29:14: error: 'BPOIssue' has no member named 'rawtext'
   29 |             prb = self.inliner.problematic(self.rawtext, self.rawtext, msg)
      |              ^~
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py:33:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   33 |         refnode = nodes.reference(issue, f"bpo-{issue}", refuri=issue_url)
      | ^   
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py:30:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   30 |             return [prb], [msg]
      | ^   
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py:260:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py:258:11: warning: variable '_t58' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/issue_role.py:257:10: warning: variable '_t57' set but not used [-Wunused-but-set-variable]
/Users/mrs/n
```

## Affected files

- `Doc/tools/extensions/audit_events.py`
- `Doc/tools/extensions/availability.py`
- `Doc/tools/extensions/c_annotations.py`
- `Doc/tools/extensions/changes.py`
- `Doc/tools/extensions/grammar_snippet.py`
- `Doc/tools/extensions/issue_role.py`
- `Doc/tools/extensions/misc_news.py`
- `Lib/collections/__init__.py`
- `Lib/compression/_common/_streams.py`
- `Lib/concurrent/futures/process.py`
- `Lib/concurrent/interpreters/_queues.py`
- `Lib/ctypes/wintypes.py`
- `Lib/email/_header_value_parser.py`
- `Lib/email/_policybase.py`
- `Lib/encodings/ascii.py`
- `Lib/encodings/base64_codec.py`
- `Lib/encodings/charmap.py`
- `Lib/encodings/cp037.py`
- `Lib/encodings/cp1006.py`
- `Lib/encodings/cp1026.py`
- `Lib/encodings/cp1125.py`
- `Lib/encodings/cp1140.py`
- `Lib/encodings/cp1250.py`
- `Lib/encodings/cp1251.py`
- `Lib/encodings/cp1252.py`
- `Lib/encodings/cp1253.py`
- `Lib/encodings/cp1254.py`
- `Lib/encodings/cp1255.py`
- `Lib/encodings/cp1256.py`
- `Lib/encodings/cp1257.py`
- `Lib/encodings/cp1258.py`
- `Lib/encodings/cp273.py`
- `Lib/encodings/cp424.py`
- `Lib/encodings/cp437.py`
- `Lib/encodings/cp500.py`
- `Lib/encodings/cp720.py`
- `Lib/encodings/cp737.py`
- `Lib/encodings/cp775.py`
- `Lib/encodings/cp850.py`
- `Lib/encodings/cp852.py`
- `Lib/encodings/cp855.py`
- `Lib/encodings/cp856.py`
- `Lib/encodings/cp857.py`
- `Lib/encodings/cp858.py`
- `Lib/encodings/cp860.py`
- `Lib/encodings/cp861.py`
- `Lib/encodings/cp862.py`
- `Lib/encodings/cp863.py`
- `Lib/encodings/cp864.py`
- `Lib/encodings/cp865.py`
- `Lib/encodings/cp866.py`
- `Lib/encodings/cp869.py`
- `Lib/encodings/cp874.py`
- `Lib/encodings/cp875.py`
- `Lib/encodings/hex_codec.py`
- `Lib/encodings/hp_roman8.py`
- `Lib/encodings/iso8859_1.py`
- `Lib/encodings/iso8859_10.py`
- `Lib/encodings/iso8859_11.py`
- `Lib/encodings/iso8859_13.py`
- `Lib/encodings/iso8859_14.py`
- `Lib/encodings/iso8859_15.py`
- `Lib/encodings/iso8859_16.py`
- `Lib/encodings/iso8859_2.py`
- `Lib/encodings/iso8859_3.py`
- `Lib/encodings/iso8859_4.py`
- `Lib/encodings/iso8859_5.py`
- `Lib/encodings/iso8859_6.py`
- `Lib/encodings/iso8859_7.py`
- `Lib/encodings/iso8859_8.py`
- `Lib/encodings/iso8859_9.py`
- `Lib/encodings/koi8_r.py`
- `Lib/encodings/koi8_t.py`
- `Lib/encodings/koi8_u.py`
- `Lib/encodings/kz1048.py`
- `Lib/encodings/latin_1.py`
- `Lib/encodings/mac_arabic.py`
- `Lib/encodings/mac_croatian.py`
- `Lib/encodings/mac_cyrillic.py`
- `Lib/encodings/mac_farsi.py`
- `Lib/encodings/mac_greek.py`
- `Lib/encodings/mac_iceland.py`
- `Lib/encodings/mac_latin2.py`
- `Lib/encodings/mac_roman.py`
- `Lib/encodings/mac_romanian.py`
- `Lib/encodings/mac_turkish.py`
- `Lib/encodings/mbcs.py`
- `Lib/encodings/oem.py`
- `Lib/encodings/palmos.py`
- `Lib/encodings/ptcp154.py`
- `Lib/encodings/quopri_codec.py`
- `Lib/encodings/raw_unicode_escape.py`
- `Lib/encodings/tis_620.py`
- `Lib/encodings/unicode_escape.py`
- `Lib/encodings/utf_16.py`
- `Lib/encodings/utf_16_be.py`
- `Lib/encodings/utf_16_le.py`
- `Lib/encodings/utf_32.py`
- `Lib/encodings/utf_32_be.py`
- `Lib/encodings/utf_32_le.py`
- `Lib/encodings/utf_7.py`
- `Lib/encodings/utf_8.py`
- `Lib/encodings/utf_8_sig.py`
- `Lib/http/__init__.py`
- `Lib/http/server.py`
- `Lib/idlelib/autocomplete.py`
- `Lib/idlelib/browser.py`
- `Lib/idlelib/calltip_w.py`
- `Lib/idlelib/codecontext.py`
- `Lib/idlelib/config_key.py`
- `Lib/idlelib/debugger.py`
- `Lib/idlelib/format.py`
- `Lib/idlelib/grep.py`
- `Lib/idlelib/help_about.py`
- `Lib/idlelib/history.py`
- `Lib/idlelib/idle_test/mock_tk.py`
- `Lib/idlelib/idle_test/test_autocomplete.py`
- `Lib/idlelib/idle_test/test_autocomplete_w.py`
- `Lib/idlelib/idle_test/test_autoexpand.py`
- `Lib/idlelib/idle_test/test_browser.py`
- `Lib/idlelib/idle_test/test_calltip.py`
- `Lib/idlelib/idle_test/test_calltip_w.py`
- `Lib/idlelib/idle_test/test_colorizer.py`
- `Lib/idlelib/idle_test/test_config.py`
- `Lib/idlelib/idle_test/test_config_key.py`
- `Lib/idlelib/idle_test/test_debugger.py`
- `Lib/idlelib/idle_test/test_editor.py`
- `Lib/idlelib/idle_test/test_filelist.py`
- `Lib/idlelib/idle_test/test_grep.py`
- `Lib/idlelib/idle_test/test_history.py`
- `Lib/idlelib/idle_test/test_hyperparser.py`
- `Lib/idlelib/idle_test/test_iomenu.py`
- `Lib/idlelib/idle_test/test_macosx.py`
- `Lib/idlelib/idle_test/test_multicall.py`
- `Lib/idlelib/idle_test/test_parenmatch.py`
- `Lib/idlelib/idle_test/test_pathbrowser.py`
- `Lib/idlelib/idle_test/test_percolator.py`
- `Lib/idlelib/idle_test/test_pyshell.py`
- `Lib/idlelib/idle_test/test_query.py`
- `Lib/idlelib/idle_test/test_redirector.py`
- `Lib/idlelib/idle_test/test_replace.py`
- `Lib/idlelib/idle_test/test_scrolledlist.py`
- `Lib/idlelib/idle_test/test_search.py`
- `Lib/idlelib/idle_test/test_searchengine.py`
- `Lib/idlelib/idle_test/test_stackviewer.py`
- `Lib/idlelib/idle_test/test_statusbar.py`
- `Lib/idlelib/idle_test/test_text.py`
- `Lib/idlelib/idle_test/test_textview.py`
- `Lib/idlelib/idle_test/test_tooltip.py`
- `Lib/idlelib/idle_test/test_tree.py`
- `Lib/idlelib/idle_test/test_undo.py`
- `Lib/idlelib/idle_test/test_window.py`
- `Lib/idlelib/idle_test/test_zoomheight.py`
- `Lib/idlelib/iomenu.py`
- `Lib/idlelib/outwin.py`
- `Lib/idlelib/parenmatch.py`
- `Lib/idlelib/pathbrowser.py`
- `Lib/idlelib/percolator.py`
- `Lib/idlelib/query.py`
- `Lib/idlelib/redirector.py`
- `Lib/idlelib/replace.py`
- `Lib/idlelib/scrolledlist.py`
- `Lib/idlelib/search.py`
- `Lib/idlelib/squeezer.py`
- `Lib/idlelib/textview.py`
- `Lib/idlelib/tree.py`
- `Lib/idlelib/undo.py`
- `Lib/importlib/__init__.py`
- `Lib/importlib/_bootstrap.py`
- `Lib/importlib/_bootstrap_external.py`
- `Lib/importlib/abc.py`
- `Lib/importlib/metadata/__init__.py`
- `Lib/importlib/metadata/_adapters.py`
- `Lib/importlib/resources/_adapters.py`
- `Lib/multiprocessing/dummy/__init__.py`
- `Lib/multiprocessing/dummy/connection.py`
- `Lib/multiprocessing/popen_spawn_posix.py`
- `Lib/multiprocessing/queues.py`
- `Lib/pathlib/__init__.py`
- `Lib/pathlib/types.py`
- `Lib/reprlib.py`
- `Lib/test/archiver_tests.py`
- `Lib/test/audiotests.py`
- `Lib/test/crashers/mutation_inside_cyclegc.py`
- `Lib/test/libregrtest/cmdline.py`
- `Lib/test/libregrtest/testresult.py`
- `Lib/test/lock_tests.py`
- `Lib/test/multibytecodec_support.py`
- `Lib/test/picklecommon.py`
- `Lib/test/ssl_servers.py`
- `Lib/test/support/_hypothesis_stubs/_helpers.py`
- `Lib/test/support/asynchat.py`
- `Lib/test/support/logging_helper.py`
- `Lib/test/support/script_helper.py`
- `Lib/test/support/venv.py`
- `Lib/test/test__interpchannels.py`
- `Lib/test/test_asyncio/test_buffered_proto.py`
- `Lib/test/test_asyncio/test_free_threading.py`
- `Lib/test/test_asyncio/test_runners.py`
- `Lib/test/test_asyncio/test_selector_events.py`
- `Lib/test/test_asyncio/test_server.py`
- `Lib/test/test_asyncio/test_subprocess.py`
- `Lib/test/test_asyncio/utils.py`
- `Lib/test/test_bigmem.py`
- `Lib/test/test_bisect.py`
- `Lib/test/test_build_details.py`
- `Lib/test/test_bz2.py`
- `Lib/test/test_capi/test_watchers.py`
- `Lib/test/test_codeccallbacks.py`
- `Lib/test/test_concurrent_futures/executor.py`
- `Lib/test/test_concurrent_futures/test_as_completed.py`
- `Lib/test/test_concurrent_futures/test_init.py`
- `Lib/test/test_concurrent_futures/test_interpreter_pool.py`
- `Lib/test/test_concurrent_futures/test_shutdown.py`
- `Lib/test/test_concurrent_futures/test_thread_pool.py`
- `Lib/test/test_concurrent_futures/test_wait.py`
- `Lib/test/test_ctypes/test_array_in_pointer.py`
- `Lib/test/test_ctypes/test_dlerror.py`
- `Lib/test/test_ctypes/test_init.py`
- `Lib/test/test_ctypes/test_pickling.py`
- `Lib/test/test_ctypes/test_simplesubclasses.py`
- `Lib/test/test_ctypes/test_structunion.py`
- `Lib/test/test_dbm.py`
- `Lib/test/test_email/__init__.py`
- `Lib/test/test_email/test__header_value_parser.py`
- `Lib/test/test_email/test_asian_codecs.py`
- `Lib/test/test_email/test_email.py`
- `Lib/test/test_email/test_generator.py`
- `Lib/test/test_email/test_headerregistry.py`
- `Lib/test/test_email/test_parser.py`
- `Lib/test/test_email/torture_test.py`
- `Lib/test/test_ensurepip.py`
- `Lib/test/test_exception_group.py`
- `Lib/test/test_exception_hierarchy.py`
- `Lib/test/test_file_eintr.py`
- `Lib/test/test_fileio.py`
- `Lib/test/test_free_threading/test_bisect.py`
- `Lib/test/test_free_threading/test_monitoring.py`
- `Lib/test/test_functools.py`
- `Lib/test/test_future_stmt/test_future.py`
- `Lib/test/test_genericpath.py`
- `Lib/test/test_glob.py`
- `Lib/test/test_heapq.py`
- `Lib/test/test_hmac.py`
- `Lib/test/test_httpservers.py`
- `Lib/test/test_importlib/builtin/test_finder.py`
- `Lib/test/test_importlib/builtin/test_loader.py`
- `Lib/test/test_importlib/extension/_test_nonmodule_cases.py`
- `Lib/test/test_importlib/extension/test_case_sensitivity.py`
- `Lib/test/test_importlib/extension/test_finder.py`
- `Lib/test/test_importlib/extension/test_loader.py`
- `Lib/test/test_importlib/frozen/test_finder.py`
- `Lib/test/test_importlib/frozen/test_loader.py`
- `Lib/test/test_importlib/import_/test_meta_path.py`
- `Lib/test/test_importlib/import_/test_path.py`
- `Lib/test/test_importlib/metadata/fixtures.py`
- `Lib/test/test_importlib/metadata/test_api.py`
- `Lib/test/test_importlib/resources/test_compatibilty_files.py`
- `Lib/test/test_importlib/resources/test_contents.py`
- `Lib/test/test_importlib/resources/test_files.py`
- `Lib/test/test_importlib/resources/test_functional.py`
- `Lib/test/test_importlib/resources/test_open.py`
- `Lib/test/test_importlib/resources/test_read.py`
- `Lib/test/test_importlib/resources/test_resource.py`
- `Lib/test/test_importlib/resources/util.py`
- `Lib/test/test_importlib/source/test_case_sensitivity.py`
- `Lib/test/test_importlib/source/test_file_loader.py`
- `Lib/test/test_importlib/source/test_finder.py`
- `Lib/test/test_importlib/source/test_path_hook.py`
- `Lib/test/test_importlib/source/test_source_encoding.py`
- `Lib/test/test_importlib/test_api.py`
- `Lib/test/test_importlib/test_lazy.py`
- `Lib/test/test_importlib/test_namespace_pkgs.py`
- `Lib/test/test_importlib/test_spec.py`
- `Lib/test/test_importlib/test_windows.py`
- `Lib/test/test_index.py`
- `Lib/test/test_inspect/inspect_fodder.py`
- `Lib/test/test_interpreters/test_lifecycle.py`
- `Lib/test/test_json/__init__.py`
- `Lib/test/test_json/test_decode.py`
- `Lib/test/test_json/test_dump.py`
- `Lib/test/test_json/test_encode_basestring_ascii.py`
- `Lib/test/test_json/test_fail.py`
- `Lib/test/test_json/test_float.py`
- `Lib/test/test_json/test_indent.py`
- `Lib/test/test_json/test_scanstring.py`
- `Lib/test/test_json/test_separators.py`
- `Lib/test/test_json/test_speedups.py`
- `Lib/test/test_linecache.py`
- `Lib/test/test_locale.py`
- `Lib/test/test_mimetypes.py`
- `Lib/test/test_netrc.py`
- `Lib/test/test_operator.py`
- `Lib/test/test_pathlib/test_join.py`
- `Lib/test/test_pathlib/test_join_posix.py`
- `Lib/test/test_pathlib/test_join_windows.py`
- `Lib/test/test_pathlib/test_pathlib.py`
- `Lib/test/test_pathlib/test_read.py`
- `Lib/test/test_pathlib/test_write.py`
- `Lib/test/test_picklebuffer.py`
- `Lib/test/test_pow.py`
- `Lib/test/test_pty.py`
- `Lib/test/test_pulldom.py`
- `Lib/test/test_pydoc/pydocfodder.py`
- `Lib/test/test_pyexpat.py`
- `Lib/test/test_pyrepl/test_windows_console.py`
- `Lib/test/test_re.py`
- `Lib/test/test_selectors.py`
- `Lib/test/test_set.py`
- `Lib/test/test_sqlite3/test_backup.py`
- `Lib/test/test_sqlite3/test_dump.py`
- `Lib/test/test_sqlite3/test_hooks.py`
- `Lib/test/test_statistics.py`
- `Lib/test/test_string/test_string.py`
- `Lib/test/test_support.py`
- `Lib/test/test_sys_setprofile.py`
- `Lib/test/test_termios.py`
- `Lib/test/test_thread.py`
- `Lib/test/test_threadedtempfile.py`
- `Lib/test/test_threadsignals.py`
- `Lib/test/test_timeit.py`
- `Lib/test/test_tkinter/support.py`
- `Lib/test/test_tkinter/test_colorchooser.py`
- `Lib/test/test_tkinter/test_font.py`
- `Lib/test/test_tkinter/test_geometry_managers.py`
- `Lib/test/test_tkinter/test_images.py`
- `Lib/test/test_tkinter/test_text.py`
- `Lib/test/test_tkinter/test_widgets.py`
- `Lib/test/test_tkinter/widget_tests.py`
- `Lib/test/test_ttk/test_style.py`
- `Lib/test/test_type_cache.py`
- `Lib/test/test_unittest/support.py`
- `Lib/test/test_unittest/test_assertions.py`
- `Lib/test/test_unittest/test_program.py`
- `Lib/test/test_unittest/test_result.py`
- `Lib/test/test_unittest/testmock/testhelpers.py`
- `Lib/test/test_unittest/testmock/testthreadingmock.py`
- `Lib/test/test_univnewlines.py`
- `Lib/test/test_urllib2_localnet.py`
- `Lib/test/test_warnings/__init__.py`
- `Lib/test/test_webbrowser.py`
- `Lib/test/test_wsgiref.py`
- `Lib/test/test_zoneinfo/_support.py`
- `Lib/test/test_zoneinfo/test_zoneinfo_property.py`
- `Lib/test/testcodec.py`
- `Lib/test/typinganndata/ann_module2.py`
- `Lib/tkinter/colorchooser.py`
- `Lib/tkinter/dialog.py`
- `Lib/tkinter/dnd.py`
- `Lib/tkinter/filedialog.py`
- `Lib/tkinter/scrolledtext.py`
- `Lib/tkinter/simpledialog.py`
- `Lib/turtledemo/colormixer.py`
- `Lib/unittest/_log.py`
- `Lib/unittest/async_case.py`
- `Lib/unittest/runner.py`
- `Lib/unittest/suite.py`
- `Lib/urllib/parse.py`
- `Lib/urllib/response.py`
- `Lib/wsgiref/simple_server.py`
- `Lib/xml/dom/__init__.py`
- `Lib/xml/dom/minidom.py`
- `Lib/xml/dom/pulldom.py`
- `Lib/xml/dom/xmlbuilder.py`
- `Lib/xml/etree/ElementInclude.py`
- `Tools/c-analyzer/c_common/tables.py`
- `Tools/c-analyzer/cpython/_capi.py`
- `Tools/c-analyzer/distutils/bcppcompiler.py`
- `Tools/c-analyzer/distutils/ccompiler.py`
- `Tools/c-analyzer/distutils/cygwinccompiler.py`
- `Tools/c-analyzer/distutils/unixccompiler.py`
- `Tools/clinic/libclinic/app.py`
- `Tools/clinic/libclinic/block_parser.py`
- `Tools/clinic/libclinic/converter.py`
- `Tools/clinic/libclinic/language.py`
- `Tools/clinic/libclinic/return_converters.py`
- `Tools/peg_generator/pegen/python_generator.py`
- `Tools/scripts/sortperf.py`
- `Tools/ssl/multissltests.py`
