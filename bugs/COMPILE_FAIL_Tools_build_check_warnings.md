# COMPILE_FAIL: Tools/build/check_warnings.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py: In function '_alloc_IgnoreRule':
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py:55:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   55 |                         sys.exit(1)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py: In function 'parse_warning_ignore_file_584a43':
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py:386:7: warning: variable '_t105' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py:372:11: warning: variable '_t91' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py:371:11: warning: variable '_t90' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py:341:10: warning: variable '_t61' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py:300:10: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
  300 |         ignore_rules = parse_warning_ignore_file(args.warning_ignore_file_path)
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py:273:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  273 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py: In function 'extract_warnings_from_compiler_output_854698':
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py:186:11: warning: variable '_t111' set but not used [-Wunused-but-set-variable]
  186 |             )
      |           ^ ~  
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py:185:11: warning: variable '_t110' set but not used [-Wunused-but-set-variable]
  185 |                 f" found {len(unexpected_warnings[file][0])}"
      |           ^    
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py:169:7: warning: variable '_t94' set but not used [-Wunused-but-set-variable]
  169 | 
      |       ^   
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py:165:10: warning: variable '_t90' set but not used [-Wunused-but-set-variable]
  165 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py:164:10: warning: variable '_t89' set but not used [-Wunused-but-set-variable]
  164 |         rule = is_file_ignored(file, ignore_rules)
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py:162:10: warning: variable '_t87' set but not used [-Wunused-but-set-variable]
  162 |     unexpected_warnings = {}
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py:161:10: warning: variable '_t86' set but not used [-Wunused-but-set-variable]
  161 |     """
      |          ^   
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py:155:11: warning: variable '_t80' set but not used [-Wunused-but-set-variable]
  155 |     files_with_warnings: dict[str, list[CompileWarning]],
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py:148:11: warning: variable '_t73' set but not used [-Wunused-but-set-variable]
  148 |         elif file_path == rule.file_path:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py:141:11: warning: variable '_t66' set but not used [-Wunused-but-set-variable]
  141 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/check_warnings.py:134:11: warning: variable '_t59' set but not used [-Wunused-but-set-variable]
  134 |     return warnings_by_file
      |           ^~~~
... (163 more lines)
```

Exit code: 1
Elapsed: 13.73s
