# COMPILE_FAIL: CC ERROR: missing terminating " character

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py:98:11: warning: unused variable '_tag' [-Wunused-variable]
   98 |         self.assertEqual(process.stdout, self.expect)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py:103:11: warning: unused variable '_tag' [-Wunused-variable]
  103 |         with open(infile, "w", encoding="utf-8") as fp:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py:108:11: warning: unused variable '_tag' [-Wunused-variable]
  108 |     def test_infile_stdout(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py:123:11: warning: unused variable '_tag' [-Wunused-variable]
  123 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py:132:13: warning: unused variable '_tag' [-Wunused-variable]
  132 |     def test_infile_outfile(self):
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py: In function 'TestMain_test_stdin_stdout':
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py:331:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  331 | @support.requires_subprocess()
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py:329:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
  329 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py:328:10: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
  328 |                 self.assertEqual(stdout, expected)
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py:327:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
  327 |                 stdout = stdout.strip()
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py:326:26: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
  326 |                 stdout = stdout.replace('\r\n', '\n')  # normalize line endings
      |                          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py:325:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
  325 |                 stdout = stdout_b.decode()
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py:324:10: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
  324 |                 )
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py:323:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
  323 |                     '-m', self.module, infile, FORCE_COLOR='1', __isolated='1'
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py:322:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
  322 |                 _, stdout_b, _ = assert_python_ok(
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py:321:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
  321 |                     fp.write(input_)
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_json/test_tool.py:320:26: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
  320 |                 with open(infile, "w", encoding="utf-8") as fp:
      |                         
```

## Affected files

- `Lib/test/test_json/test_tool.py`
