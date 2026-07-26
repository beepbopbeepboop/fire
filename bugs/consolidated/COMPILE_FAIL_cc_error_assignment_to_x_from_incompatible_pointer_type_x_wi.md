# COMPILE_FAIL: CC ERROR: assignment to 'X' from incompatible pointer type 'X' [-Wincompatible-pointer-types]

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py:145:11: warning: unused variable '_tag' [-Wunused-variable]
  145 |             return []
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py:150:11: warning: unused variable '_tag' [-Wunused-variable]
  150 |         self.assertEqual(set(), opcodes)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py:155:11: warning: unused variable '_tag' [-Wunused-variable]
  155 |     def test_line(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py:170:11: warning: unused variable '_tag' [-Wunused-variable]
  170 |     backend = SystemTapBackend()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py:179:13: warning: unused variable '_tag' [-Wunused-variable]
  179 |     @classmethod
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py: In function 'abspath_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py:351:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py: In function 'normalize_trace_output_584a43':
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py:39:7: error: assignment to 'char *' from incompatible pointer type 'MojoList *' [-Wincompatible-pointer-types]
   39 |         result = [row[1] for row in result]
      |       ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py:34:1: warning: label 'bb_11' defined but not used [-Wunused-label]
   34 |             row.split("\t")
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py:63:7: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
   63 |     def generate_trace_command(self, script_file, subcommand=None):
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py:50:10: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
   50 |     COMMAND_ARGS = []
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py:46:10: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
   46 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py:35:10: warning: unused variable '_t12' [-Wunused-variable]
   35 |             for row in output.splitlines()
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py:24:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   24 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py: In function 'TraceBackend_run_case':
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py:94:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   94 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_dtrace.py:64: confused by earlier errors, bailing out


```

## Affected files

- `Lib/test/test_dtrace.py`
