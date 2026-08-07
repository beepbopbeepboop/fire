# COMPILE_FAIL: Tools/c-analyzer/c_parser/datafiles.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-06)

Re-ran; 472 error lines, almost all inside a transitively-imported
sibling, `Tools/c-analyzer/c_parser/info.py` (this file itself imports
`from .info import ...` extensively). Representative errors:

```
error: 'c_parser_info__fmt_full_fe04a9' undeclared here (not in a function); did you mean '_funcptr_c_parser_info__fmt_full_fe04a9'?
error: 'MojoBoundMethod' has no member named 'id'
error: expected expression before ';' token
error: request for member 'filename' in 'fileinfo', which is of non-class type 'int64_t'
```

Not fully root-caused given the sheer volume, but several DISTINCT,
already-partially-understood mechanisms plausibly compound here:
1. The same "function-as-value at module scope" gap already documented
   in `bugs/COMPILE_FAIL_importlib__bootstrap_external.md` (the
   `_funcptr_*` GCC suggestion is the same tell).
2. `HighlevelParsedItem` (in `info.py`) subclasses namedtuple factories
   AND defines its own `__getattr__` override (dynamic attribute
   fallback: `def __getattr__(self, name): return self._extra[name]`)
   — plausibly related to `bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md`.
3. `__str__` does `self._str = next(self.render())` where `render()` is
   a generator method — same `next()`-on-a-generic-iterator shape
   already flagged (not yet a hard bug doc) in
   `bugs/COMPILE_FAIL_importlib_resources__common.md`.
4. `HighlevelParsedItem.id` property (`return self.parsed.id`) reads a
   field through a chain that ends up typed `MojoBoundMethod *` instead
   of the real class — plausibly the struct-field/return-type
   inference gap this session's other hard bugs already describe.

Given `info.py` itself isn't independently in this session's assigned
range and the error count here makes isolating any ONE of these four
candidates impractical within the time available, this file is left as
a compound/cascading case rather than root-caused to one specific fix.
Worth a dedicated follow-up session that starts from `info.py` directly
(not this file) with a much longer time budget, informed by the four
candidate mechanisms above.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py:35:11: warning: unused variable '_tag' [-Wunused-variable]
   35 |     for row in _tables.read_table(infile, columns, sep='\t', fix='-'):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py:40:11: warning: unused variable '_tag' [-Wunused-variable]
   40 |     # XXX Support other formats than TSV?
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py:45:11: warning: unused variable '_tag' [-Wunused-variable]
   45 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py:60:11: warning: unused variable '_tag' [-Wunused-variable]
   60 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py:69:13: warning: unused variable '_tag' [-Wunused-variable]
   69 |     _, ext = os.path.splitext(filename)
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py: In function 'read_parsed_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py:34:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   34 |     columns = _get_columns('parsed')
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py:33:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   33 |     # XXX Support other formats than TSV?
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py:31:14: warning: variable 'columns' set but not used [-Wunused-but-set-variable]
   31 | 
      |              ^      
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py: In function 'write_parsed_1ce6ce':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py:56:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   56 |         fmt = _get_format(infile)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py:55:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   55 |     if fmt is None:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py:51:11: warning: variable 'rows' set but not used [-Wunused-but-set-variable]
   51 |         yield decl
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py:49:14: warning: variable 'columns' set but not used [-Wunused-but-set-variable]
   49 |     read_all, _ = _get_format_handlers('decls', fmt)
      |              ^~~~~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py: In function 'read_decls_1ce6ce':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py:64:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
   64 | def _get_format(file, default='tsv'):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py:62:11: warning: variable '_' set but not used [-Wunused-but-set-variable]
   62 | # formats
... (33 more lines)
```

Exit code: 1
Elapsed: 13.71s
