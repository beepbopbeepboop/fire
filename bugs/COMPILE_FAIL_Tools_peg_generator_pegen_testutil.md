# COMPILE_FAIL: Tools/peg_generator/pegen/testutil.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py:55:11: warning: unused variable '_tag' [-Wunused-variable]
   55 |     return run_parser(file, parser_class, verbose=verbose)  # type: ignore[arg-type] # typeshed issue #3515
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py:60:11: warning: unused variable '_tag' [-Wunused-variable]
   60 |     grammar = parse_string(source, GrammarParser)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py:65:11: warning: unused variable '_tag' [-Wunused-variable]
   65 |     """Import a python module from a path"""
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py:80:11: warning: unused variable '_tag' [-Wunused-variable]
   80 |     genr = CParserGenerator(grammar, ALL_TOKENS, EXACT_TOKENS, NON_EXACT_TOKENS, out)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py:89:13: warning: unused variable '_tag' [-Wunused-variable]
   89 |     library_dir: str | None = None,
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py: In function 'generate_parser_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py:203:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py:200:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py: In function 'run_parser_c638e7':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py:42:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   42 |     result = parser.start()
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py: In function 'parse_string_477674':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py:61:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   61 |     return generate_parser(grammar)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py:54:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   54 |     file = io.StringIO(source)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py: In function 'import_file_abb124':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py:95:11: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
   95 |     """
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py:94:11: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
   94 |     TODO: express that using a Protocol.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py:84:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
   84 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py:71:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   71 |     # We assume this is not None and has an exec_module() method.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/testutil.py:66:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   66 | 
... (100 more lines)
```

Exit code: 1
Elapsed: 14.01s
