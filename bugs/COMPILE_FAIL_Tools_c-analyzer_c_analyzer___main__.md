# COMPILE_FAIL: Tools/c-analyzer/c_analyzer/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-09)

Re-verified against current master (fast-forwarded to `bf1ead2`, after
several sibling `Tools/c-analyzer/` bugs and the related
`_write_atomic.__code__` bug (see
`bugs/COMPILE_FAIL_importlib__bootstrap_external.md`) got fixed this
session). `python3 mojo.py build` on this file still fails with the
EXACT SAME four errors as the 2026-08-07 note below, character for
character (`'fmt_brief_0c85c9' undeclared here (not in a function)`,
etc.) — none of the intervening fixes touched this "generator function
referenced as a bare value" gap. That `importlib/_bootstrap_external.py`
doc's own 2026-08-09 update independently confirms the same conclusion:
its superficially-similar `_write_atomic.__code__` case had an
unrelated root cause (a `_lower_MemberExpr` heuristic misfiring on a
dunder attribute) and has now been fixed there, while explicitly
reaffirming this file's case is the separate, still out-of-scope
generator-as-value gap. Confirmed still structural (part of the
already-tracked compiled-generator/async-codegen project, tasks
#95-135); not attempted. No code change — doc re-verified only.

## Original status (updated 2026-08-07)

Investigated further: `fmt_raw`/`fmt_brief`/`fmt_summary`/`fmt_full`
(referenced below as VALUES in the `FORMATS` dict) are all GENERATOR
functions (`yield`/`yield from` in their bodies) — this is almost
certainly an instance of the already-tracked, explicitly out-of-scope
compiled-generator/async-codegen project (tasks #95-135)'s "a generator
function used as a bare value" gap, NOT the same root cause as the
`_write_atomic`-shaped case it was originally paired with in
`bugs/COMPILE_FAIL_importlib__bootstrap_external.md` (confirmed via a
direct repro: an ordinary, non-generator top-level function used as a
module-level dict value compiles clean through this codegen's existing
`_lower_IdentExpr` "function name used as a value" mechanism — no bug
there). See that doc's 2026-08-07 follow-up for the full correction.
Not fixed here; out of scope per this session's generator/async-codegen
boundary.

## Original status (2026-08-06)

Re-ran; current error:

```
error: 'fmt_brief_0c85c9' undeclared here (not in a function); did you mean '_funcptr_fmt_brief_0c85c9'?
error: 'fmt_full_0c85c9' undeclared here (not in a function)
error: 'fmt_raw_79c856' undeclared here (not in a function)
error: 'fmt_summary_0c85c9' undeclared here (not in a function); did you mean 'fmt_summary_section'?
```

Root-caused: `def fmt_raw/fmt_brief/fmt_summary/fmt_full(analysis):`
are ordinary top-level functions, then referenced as VALUES (not
called) in a module-level dispatch dict: `FORMATS = {'raw': fmt_raw,
'brief': fmt_brief, 'summary': fmt_summary, 'full': fmt_full}`. This is
a confirmed SECOND, independent real-world instance of the already-
documented "`_write_atomic.__code__` at module scope" gap in
`bugs/COMPILE_FAIL_importlib__bootstrap_external.md` (added there) —
GCC's own suggested fix (`did you mean '_funcptr_fmt_brief_0c85c9'`)
names the exact already-generated-but-unreferenced static function
pointer this call site should use instead of the bare unmangled name.
Not fixed here — see that doc.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:117:11: warning: unused variable '_tag' [-Wunused-variable]
  117 |     return items, render
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:122:11: warning: unused variable '_tag' [-Wunused-variable]
  122 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:127:11: warning: unused variable '_tag' [-Wunused-variable]
  127 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:142:11: warning: unused variable '_tag' [-Wunused-variable]
  142 |                                 action='append_const', const=check)
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:151:13: warning: unused variable '_tag' [-Wunused-variable]
  151 |         pass
      |             ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_render_table_132aaf':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:392:10: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  392 |     if track_progress:
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:388:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  388 |         raise ValueError(f'unsupported fmt {fmt!r}')
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:387:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  387 |     except KeyError:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:384:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  384 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:383:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  383 |     verbosity = verbosity if verbosity is not None else 3
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:382:10: warning: variable 'div' set but not used [-Wunused-but-set-variable]
  382 |                 ):
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:380:10: warning: variable 'header' set but not used [-Wunused-but-set-variable]
  380 |                 formats=FORMATS,
      |          ^     
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function '_alloc_build_section_render_env':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:106:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  106 |         info = TABLE_SECTIONS[info]
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py: In function 'build_section_render':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py:129:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  129 |     default = False
... (841 more lines)
```

Exit code: 1
Elapsed: 14.16s
