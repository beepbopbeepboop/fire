# COMPILE_FAIL: Tools/c-analyzer/c_analyzer/info.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (re-verified 2026-08-23)

Re-ran against current master tip (`626f3f0`): still fails, still in the
generated `info_gen.cpp`, with the SAME error shapes the 2026-08-09
root-cause below identified (unannotated generator-body params
`item`/`fmt` falling back to naive types):

```
info_gen.cpp:138:27: error: request for member 'render' in
    'self->Analyzed::item', which is of non-class type 'int64_t'
info_gen.cpp:134:14 / 158:19 / 161:19: error: ISO C++ forbids comparison
    between pointer and integer   (fmt == "raw" / "summary" / "full")
info_gen.cpp:159:48: error: invalid conversion from 'int64_t' to 'char*'
info_gen.cpp:146:35: error: void value not ignored as it ought to be
```

Byte-for-byte the same mechanism (coroutine-path type inference lacks
the ordinary path's param/field inference; same tracked generator/async
codegen project, tasks #95-135). Structural; unchanged; no code change —
doc re-verified only.

## Status (updated 2026-08-09)

Re-verified against current master (fast-forwarded to `bf1ead2`, after
several sibling `Tools/c-analyzer/` bugs got fixed this session): still
fails, same shape and (for the errors quoted in the 2026-08-06 note)
byte-identical text — errors are all in the generated C++ file
(`info_gen.cpp`), confirming this module still routes through the
separate C++20-coroutine generator lowering path (`info.py`'s `render`
method does `yield repr(self)` / `yield from rendered`, etc.).

Root-caused precisely this time (the 2026-08-06 note hadn't traced past
the gcc error text): `Analyzed.__init__`'s `item`/`typedecl` parameters
and the `render(self, fmt='line', ...)` method's `fmt` parameter are
both unannotated. The ORDINARY (non-coroutine) function-lowering path
infers such parameters' real C types from call-site/body usage; the
C++20-coroutine generator-body lowering (`_gen_cpp_generator_unit` and
its statement-emission helpers) is a separate, independently-maintained
type-inference pass that does not do this — it falls back to the naive
`int64_t` default for both `self.item` (a struct-typed field, assigned
from the `item` constructor param) and `fmt` (a string, compared against
string literals `'raw'`/`'summary'`/`'full'` in `render`'s body). This
produces exactly the observed errors:
- `self->item.render(fmt)` — `.render` looked up on `int64_t` because
  `item`'s field type was never resolved to the real `Analyzed`/
  `TypeDeclaration`-shaped struct pointer.
- `(fmt == "raw")` / `(fmt == "summary")` / `(fmt == "full")` — `fmt`
  compared against a C string literal while typed `int64_t`: "ISO C++
  forbids comparison between pointer and integer".
- `throw _MojoCppExc{ (int64_t)108472663, fmt, (void *)fmt }` — the
  exception-message slot expects `char*` but receives `fmt` typed as
  `int64_t`.
- `Analyzed__render_extra(self, fmt)` used in a value context while its
  inferred return type is `void` — likely the same self/param
  mistyping cascading into `_render_extra`'s own inferred signature.

This is the same "untyped/misresolved generator-body member-access"
category the 2026-08-06 note already pointed at, now traced to its
actual mechanism: the coroutine-body lowering pass needs its own
parameter/field type-inference pass brought up to parity with the
ordinary function-lowering path's (a real, nontrivial feature — not a
missing single case), and touches the same separately-maintained
generator/async codegen subsystem the tracked project (tasks #95-135)
already covers. Structural; not attempted here, per CLAUDE.md's
guidance against forcing narrow fixes onto shared/incomplete inference
machinery. No code change — doc corrected with the precise mechanism.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:67:11: warning: unused variable '_tag' [-Wunused-variable]
   67 |             return resolved, None
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:72:11: warning: unused variable '_tag' [-Wunused-variable]
   72 |         if extra:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:77:11: warning: unused variable '_tag' [-Wunused-variable]
   77 |         elif typedeps in (None, UNKNOWN):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:92:11: warning: unused variable '_tag' [-Wunused-variable]
   92 |         elif item.kind is KIND.STRUCT or item.kind is KIND.UNION:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:101:13: warning: unused variable '_tag' [-Wunused-variable]
  101 |         elif typedecl and not isinstance(typedecl, TypeDeclaration):
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function 'SystemType___init__':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:227:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  227 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:225:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  225 |         self.item.fix_filename(relroot, **kwargs)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py: In function 'Analyzed_is_target':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:38:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   38 |     def from_raw(cls, raw, **extra):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:36:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   36 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:47:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   47 |             return cls(raw, **extra)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:38:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   38 |     def from_raw(cls, raw, **extra):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:36:9: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   36 | 
      |         ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:35:9: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   35 |             return False
      |         ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py:34:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   34 |         else:
      |           ^~~
... (2301 more lines)
```

Exit code: 1
Elapsed: 13.82s
