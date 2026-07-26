# COMPILE_FAIL: CC ERROR: 'X' undeclared (first use in this function); did you mean 'X'?

**5 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:41:11: warning: unused variable '_tag' [-Wunused-variable]
   41 |     return re.sub(_color_pattern, _replace_match_callback, json_str)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:46:11: warning: unused variable '_tag' [-Wunused-variable]
   46 |                    'to validate and pretty-print JSON objects.')
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:51:11: warning: unused variable '_tag' [-Wunused-variable]
   51 |     parser.add_argument('outfile', nargs='?',
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:66:11: warning: unused variable '_tag' [-Wunused-variable]
   66 |                        const='\t', help='separate items with newlines and use '
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:75:13: warning: unused variable '_tag' [-Wunused-variable]
   75 |     dump_args = {
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py: In function '_colorize_json__replace_match_callback':
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:213:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:186:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py: In function '_colorize_json_0335d0':
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:41:9: error: '_mojo_cb__colorize_json__replace_match_callback' undeclared (first use in this function); did you mean '_colorize_json__replace_match_callback'?
   41 |     return re.sub(_color_pattern, _replace_match_callback, json_str)
      |         ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
      |         _colorize_json__replace_match_callback
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:41:9: note: each undeclared identifier is reported only once for each function it appears in
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py: In function '_gimple_main':
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:99:1: warning: label 'bb_15' defined but not used [-Wunused-label]
   99 |         if options.outfile is None:
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:255:11: warning: variable '_t197' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:253:11: warning: variable '_t195' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:252:11: warning: variable '_t194' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:243:11: warning: variable '_t185' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:241:11: warning: variable '_t183' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:235:11: warning: variable '_t178' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:219:11: warning: variable '_t164' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:199:7: warning: variable '_t145' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:192:11: warning: variable '_t138' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:182:11: warning: variable 'line' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/json/tool.py:171:10: warning: unused 
```

## Affected files

- `Lib/json/tool.py`
- `Lib/test/test_dbm_dumb.py`
- `Lib/test/test_getpass.py`
- `Lib/test/test_sort.py`
- `Tools/scripts/var_access_benchmark.py`
