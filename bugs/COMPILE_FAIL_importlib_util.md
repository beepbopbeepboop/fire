# COMPILE_FAIL: Lib/importlib/util.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (re-verified 2026-08-07): NOW PASSES

`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/importlib/util.py`
now builds cleanly (`Built: .../util`, exit 0, no `error:` lines) — a
side effect of the "option 3" defensive-net fix landed today in
`bugs/hard/CODEGEN_selfhost_getattr_dispatch_heuristic_misfires_on_ordinary_code.md`
(the root cause this doc's 2026-08-06 note pointed at). No further
action needed here; not re-fixed by this session, just re-verified and
closed out.

## Status (updated 2026-08-06, historical)

Re-ran; current error (line numbers now point at the generated `.ci`,
not the real `.py`, since the malformed code is emitted after the last
`#line` directive — cosmetic, not the bug):

```
error: expected declaration specifiers or '...' before '*' token
error: '_lazymodule__dispatch_t' has no member named 'LazyModule___delattr__'
error: expected '}' before '_LazyModule___delattr__'
```

Root-caused (this is the SAME underlying error the original stale doc
already showed, at a different — now-shifted — location, confirming
it's stable/reproducible): `_LazyModule(types.ModuleType)`'s
`__getattribute__` does an ordinary attribute-delegation `return
getattr(self, attr)`. This codegen's self-hosting-oriented
`getattr(self, x)`-as-dispatch-table heuristic
(`_analyze_getattr_pattern` in `gimple_codegen.py`, built for
`myinterpreter.py`'s own `Interpreter.execute` vtable-style dispatch)
mis-fires on this ordinary delegation call and, unable to parse a
`prefix + something` name shape, falls back to "assume all of
`_LazyModule`'s methods are dispatch targets" — including
`__delattr__`/`__getattribute__` themselves. Since `_LazyModule`
subclasses the opaque `types.ModuleType`, its `self` parameter's C type
can't be resolved, so the synthesized dispatch-table typedef gets a
function-pointer field with a missing type before `*self`
(`void (*LazyModule___delattr__)( *self, int attr);`), an invalid C
declaration GCC rejects — which then cascades into the "has no member"
errors seen above.

This is a genuinely NEW hard bug (not one of the previously documented
ones) — written up in full, including a 3-option fix plan, as
`bugs/hard/CODEGEN_selfhost_getattr_dispatch_heuristic_misfires_on_ordinary_code.md`.
Not fixed here: the triggering machinery exists specifically to keep
`make check-selfhost` working, so any fix needs verification against
that gate specifically before being considered safe — left for a
dedicated pass.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:63:35: error: expected declaration specifiers or '...' before '*' token
   63 |         else:
      |                                   ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:64:43: error: expected declaration specifiers or '...' before '*' token
   64 |             if spec is None:
      |                                           ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:65:1: warning: no semicolon at end of struct or union
   65 |                 raise ValueError(f'{name}.__spec__ is None')
      | ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:73:11: warning: unused variable '_tag' [-Wunused-variable]
   73 |     so, then sys.modules[name].__spec__ is returned. If that happens to be
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:78:11: warning: unused variable '_tag' [-Wunused-variable]
   78 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:83:11: warning: unused variable '_tag' [-Wunused-variable]
   83 |     In other words, relative module names (with leading dots) work.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:98:11: warning: unused variable '_tag' [-Wunused-variable]
   98 |             parent_path = None
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:107:13: warning: unused variable '_tag' [-Wunused-variable]
  107 |             raise ValueError(f'{name}.__spec__ is not set') from None
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:185:4: error: '_lazymodule__dispatch_t' has no member named 'LazyModule___delattr__'
  185 |                 if loader_state['is_loading']:
      |    ^            ~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:185:40: error: expected declaration specifiers or '...' before '*' token
  185 |                 if loader_state['is_loading']:
      |                                        ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:185:29: warning: excess elements in struct initializer
  185 |                 if loader_state['is_loading']:
      |                             ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:185:29: note: (near initialization for '_lazymodule__dispatch')
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:185:57: error: expected '}' before '_LazyModule___delattr__'
  185 |                 if loader_state['is_loading']:
      |                                                         ^                      
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:184:62: note: to match this '{'
  184 |                 # happen, but in any case we must return something to avoid deadlock.
      |                                                              ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: In function 'source_hash_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:241:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  241 |             raise TypeError('loader must define exec_module()')
... (793 more lines)
```

Exit code: 1
Elapsed: 10.31s
