# COMPILE_FAIL: CC ERROR: conflicting types for 'X'; have 'X' {aka 'X'}

**15 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py:47:11: warning: unused variable '_tag' [-Wunused-variable]
   47 | def get_diff_files(ref_a: str, ref_b: str, filter_mode: str = "") -> set[Path]:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py:52:11: warning: unused variable '_tag' [-Wunused-variable]
   52 |             "diff",
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py:57:11: warning: unused variable '_tag' [-Wunused-variable]
   57 |         ],
      |           ^   
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py:72:11: warning: unused variable '_tag' [-Wunused-variable]
   72 |             "git",
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py:81:13: warning: unused variable '_tag' [-Wunused-variable]
   81 |         text=True,
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py: In function 'get_diff_files_854698':
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py:66:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   66 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py:246:10: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
  246 |         print("\nCongratulations! You improved:\n")
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py:225:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  225 |     if problem_files:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py: In function 'get_diff_lines_08338c':
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py:158:11: warning: variable 'line_ranges' set but not used [-Wunused-but-set-variable]
  158 | def process_touched_warnings(
      |           ^~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py:97:11: warning: variable 'line_matches' set but not used [-Wunused-but-set-variable]
   97 |     ]
      |           ^           
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py:93:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
   93 |         for match_value in line_match_values
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py:70:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   70 |     diff_output = subprocess.run(
      |          ^~~
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py: In function 'get_para_line_numbers_0c85c9':
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py:148:7: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
  148 |         warning for warning in warnings if str(file) in warning["file"]
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py:147:7: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
  147 |     warnings_infile = [
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py:105:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  105 |     paragraphs = []
      |          ^~~
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py: In function 'filter_and_parse_warnings_06b3cc':
/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py:131:1: warning: label 'bb_21' defined but not used [-Wunused-label]
  131 |     return non_null_matches
      | ^   ~
/Users/mrs/net/Python
```

## Affected files

- `Doc/tools/check-warnings.py`
- `Lib/idlelib/pyshell.py`
- `Lib/multiprocessing/connection.py`
- `Lib/multiprocessing/pool.py`
- `Lib/multiprocessing/popen_forkserver.py`
- `Lib/multiprocessing/process.py`
- `Lib/test/_test_monitoring_shutdown.py`
- `Lib/test/_test_multiprocessing.py`
- `Lib/test/test_importlib/metadata/test_main.py`
- `Lib/test/test_subprocess.py`
- `Lib/test/test_unittest/testmock/testpatch.py`
- `Lib/turtledemo/fractalcurves.py`
- `Platforms/emscripten/prepare_external_wasm.py`
- `Tools/build/check_warnings.py`
- `Tools/msi/generate_md5.py`
