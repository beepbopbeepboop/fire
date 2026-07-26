# COMPILE_FAIL: Doc/tools/check-warnings.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

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
... (189 more lines)
```

Exit code: 1
Elapsed: 8.90s
