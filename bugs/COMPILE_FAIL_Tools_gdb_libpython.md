# COMPILE_FAIL: Tools/gdb/libpython.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (re-verified 2026-08-26, branch fix/rest-remainder15 — unchanged)

Fresh `MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/
Tools/gdb/libpython.py` against current tree (`a913ab8`): exit 1,
byte-for-byte the same error family as the 2026-08-25 entry below —
`expected primary-expression before '.'`, `begin`/`end` not declared
(×4), `PyObjectPtr` undeclared (×4, "did you mean 'PySetObjectPtr'"),
`invalid conversion from 'const char*' to 'int64_t'` (dict-subscript
misrouted to string-slice codegen), `PyDictObjectPtr* -> MojoDict*`
conversion, `operator""pointer` unresolved-receiver shape, pointer-vs-
integer comparison. None of this campaign's shared fixes (map/getattr
gaps checked for pkgutil, int()/float() builtin already landed prior)
touch struct-declaration coverage in standalone coroutine TUs,
unresolved-receiver method dispatch, or dict-subscript dispatch in the
coroutine expression emitter (`gimple_cpp_core.py`'s `_cpp_expr`
SubscriptExpr case has no dict-vs-slice disambiguation for a raw
struct-pointer receiver like `ep` here — confirmed by reading that
function directly). Genuinely deep compiled-generator/cpp-emission
project scope, not attempted. No code change. Doc stays open.

## Status (updated 2026-08-25, second session — the `-fgimple` ICE is ## ROOT-CAUSED and FIXED; the file advances to the .cpp coroutine stage ## and is blocked there by the SAME error family the 2026-08-23 entry ## documented — those were MASKED by earlier refusals, never resolved)

The ICE was not GCC being flaky — the emitted GIMPLE was genuinely
self-contradictory. Root cause chain:

1. `TruncatedStringIO.write(self, data)`'s ONLY body-level type signals
   are a slice (`data[0:n]`) and `len(data)` (excluded as sized-container
   evidence), so `_infer_param_types` (gimple_gen_infra.py) took its
   documented subscripted-without-str-signals branch and typed `data`
   `'MojoList *'` — the same str/list heuristic guess its own docstrings
   already record three prior misfires of.
2. `self._val`, meanwhile, stays `char *` (from `__init__`'s
   `self._val = ''` via gen_module's field-registration pass), so the
   body lowered `len(data)`→`mojo_list_len`, `data[0:n]`→
   `mojo_list_slice`, and then `self._val += data[...]` fell through
   BinOp '+' dispatch (which has branches for char*+char*,
   char*+char, MojoList*+MojoList* but nothing for the mixed shape)
   into generic arithmetic emission: raw `_t17 = _t10 + _t16;` —
   `char * + MojoList *`. gcc's `-fgimple` frontend cannot build a
   PLUS_EXPR tree between two pointer operands → "internal compiler
   error: in build2, at tree.cc:5208".

FIXED (commit `31f79c3`) at the INFERENCE level, with two narrow,
independent evidence sources that resolve such a param to `char *`
(fixing only BinOp's fall-through would have silenced the ICE but left
`mojo_list_len(char_ptr)` garbage at runtime):

- `_infer_param_types` gained an optional `owner_struct` param (threaded
  only from gen_module's struct-method loop) and `analyze_param_usage`
  records every `self.<member> += <param-derived value>` sink as a pure
  name signal; the decision step resolves all recorded sinks against
  `struct_field_types` (populated from `__init__`'s own
  `self._val = ''` by `_collect_self_assigns`) and picks `char *` when
  every sink is char*-typed — sound because `str += <list>` is a
  TypeError in real Python. THIS is the mechanism that fires for
  libpython.py: every `.write(...)` receiver there is an `out` parameter
  forwarded through write_repr chains, so no call-site observer can see
  the struct.
- Pass 1.3e's method cross-call scalar observation (`_apply_method_
  scalar_obs` in gimple_module_gen.py) may now override a
  usage-heuristic `'MojoList *'` when EVERY observable call site passes
  provably-str arguments ({'char *} unanimity — string literals/
  f-strings/provably-str joins are the only sources of such entries).
  Fires for shapes where receivers DO resolve (verified on an isolated
  repro where `t = TruncatedStringIO(None)` locals exist).

Verified end-to-end: libpython.ci now emits
`void __GIMPLE TruncatedStringIO_mojo_write (TruncatedStringIO * self, char * data)`
with `mojo_strlen(data)` / `mojo_cstr_slice(data, 0, n)` /
`mojo_str_cat(self->_val, ...)` throughout — the .c/-fgimple stage
compiles clean for the first time. Isolated TruncatedStringIO repros
also BUILD AND RUN correctly (truncation path: writes 'abcde', raises,
caller catches StringTruncated and getvalue returns the truncated
value; unbounded path appends normally).

The file still does not build end-to-end. With the ICE gone, the build
now reaches the Milestone-B companion `.cpp` compile
(`libpython_gen.cpp`, the C++20-coroutine units for items_from_keys_
and_values / iteritems / iter_locals / parse_location_table) and fails
there — and the error list IS the 2026-08-23 entry's list below, which
that entry's re-triage declared "GONE". They were never resolved; the
earlier up-front generator refusals merely made them unreachable.
Confirmed still present, verbatim:

- `(void)(PyDictObjectPtr._get_entries(keys));` — a class-qualified
  method call lowered as `.method(...)` ON THE CLASS NAME ("expected
  primary-expression before '.'");
- `for (auto i : safe_range_0c85c9(nentries))` — `begin`/`end` not
  declared ×4 each in these standalone coroutine TUs;
- `PyObjectPtr` undeclared ×4 (struct declaration coverage in
  coroutine units);
- 10× `invalid conversion from 'const char*' to 'int64_t'`, the
  clearest being a WRONG LOWERING, not just a type mismatch:
  `ep["me_key"]` (a str-KEY dict subscript) routed to string-slice
  codegen — `mojo_cstr_slice((char *)(ep), "me_key", ("me_key") + 1)` —
  the coroutine emitter (`gimple_cpp_core.py`'s `_cpp_expr`) has no
  dict-subscript dispatch and reuses slice lowering for any subscript;
- `obj_ptr_ptr = 0.pointer().pointer();` → operator""pointer (the
  unresolved-receiver shape, still present in iter_locals);
- plus int64_t→MojoList*, PyDictObjectPtr*→MojoDict*, char→char*, and
  pointer-vs-integer comparison conversions around the same sites.

These remain compiled-generator/cpp-emission project scope (struct
declaration coverage/ordering in standalone coroutine units,
unresolved-receiver method dispatch, missing dict-subscript dispatch in
the coroutine expression emitter) — several distinct gaps, each
needing its own focused session; deliberately not attempted here per
the standing warning about narrow-looking edits to shared
coroutine-emission machinery. Quality gate after `31f79c3`:
test_gimple.py 256/256, test_module_cache.py 76/76, make check-selfhost
clean, from-scratch stdlib dylib build exit 0 with ZERO skip lines.

## Status (updated 2026-08-25 — `iteritems`'s own remaining refusal FIXED;
## a genuinely different, deeper GCC ICE now blocks the file)

Re-ran fresh against `fix/rest-remainder9`. The 2026-08-23 entry below's
`.cpp`-stage error list (`PyObjectPtr` undeclared, `begin`/`end` clashes,
etc.) is GONE — this file no longer even reaches that stage. Instead, the
build now refuses earlier and more narrowly:

```
Error building: cannot compile module: function(s) iteritems (generator
function(s), contain a `yield`/`yield from`) ...
Unsupported shape(s): iteritems: a call to unresolved callee 'int(...)'
is not supported in a compiled generator/coroutine body (...).
```

`PyDictObjectPtr.iteritems` does `has_values = int(values)` (line 789) —
the coroutine-body expression emitter (`gimple_cpp_core.py`'s `_cpp_expr`
CallExpr case) had NO handling at all for the `int(x)`/`float(x)`
builtins, unlike the ordinary (non-coroutine) call path (`_lower_named_
call`'s own `int(x)`/`float(x)` direct-cast special cases). FIXED: added
matching `int(x)`/`float(x)` handling to the coroutine emitter, mirroring
the ordinary path's dispatch — a `char *`-declared argument is a real
string parsed via `mojo_make_int`/`mojo_make_float` (this codegen's
existing runtime helpers, already declared in `runtime/mojo_runtime.h`),
any other declared (or untracked — this emitter has no `_actual_types`
boxed-value-kind tracking) type gets a direct numeric cast
(`(int64_t)(...)`/`(double)(...)`), unlike list()/set()/comprehension
(which need real loop-as-expression codegen this emitter still lacks —
see the sibling `c_analyzer/__init__.py`/`__main__.py` docs), int()/
float() need no loop at all, so this was a safe, narrow, mechanical
addition.

Confirmed: `iteritems`'s own `int(...)`-unresolved-callee refusal is
gone; the generator now clears the eligibility gate entirely. The file
still does not build — it now reaches g++/`-fgimple` compilation of a
DIFFERENT, unrelated function, `TruncatedStringIO.mojo_write`, and hits a
genuine GCC internal compiler error (not a graceful diagnostic):

```
TruncatedStringIO_mojo_write: internal compiler error: in build2, at
tree.cc:5208
    self._val += data[0:self.maxlen - len(self._val)]
```

— the same general class of `-fgimple` frontend crash (as opposed to an
ordinary type-mismatch diagnostic) already seen and left un-investigated
in `cases_generator/cwriter.py`'s history (`internal compiler error: in
build2, at tree.cc:5204`, a different line/shape but the same GCC
internals entry point). Root-causing an ICE typically means bisecting the
exact emitted GIMPLE shape that GCC's frontend cannot build a tree for —
a materially different, deeper investigation than an honest-refusal gap,
and not attempted in the time remaining this session. Doc kept open;
`iteritems`'s blocker is genuinely resolved, but the file as a whole
still fails, on a new and different bug.

Quality gate after the `int()`/`float()` coroutine-emitter fix:
`test_gimple.py` 253/253, `test_module_cache.py` 76/76 (see the session's
top-level report for `make check-selfhost`/stdlib-dylib results, run once
for the whole day's change set).

## Status (2026-08-23): the up-front generator refusal is GONE entirely (all 4
## tuple-yield generators, `iteritems` included, now pass the gate); new
## blockers are .cpp-stage hard errors. Still open.

Re-ran against current code (branch `fix/tools-misc` @ `c16c05c`, which includes
master's absorbed lambda/tuple-yield coroutine work). No `cannot compile module`
refusal is emitted anymore — the build proceeds all the way to compiling the
generated `libpython_gen.cpp` and fails there with a fresh frontier of errors:

- `PyObjectPtr` (the file's own base wrapper class, source line 160) "was not
  declared in this scope" — the cpp emission never declares that struct;
- `begin`/`end` undeclared (colliding with `std::ranges` names in scope);
- 14× `invalid conversion from 'const char*' to 'int64_t'`;
- `_mojogen_PyFramePtr_iter_locals_impl`: `obj_ptr_ptr = 0.pointer().pointer();`
  — an unresolved receiver lowered to literal `0`, then `.pointer()` emitted as
  a raw member call on the int literal (GCC reads it as a user-defined-literal,
  `unable to find numeric literal operator 'operator""pointer'`) — same
  opaque-receiver-method-call class as wasi `__main__.py`'s surviving error;
- `too many arguments to function 'PyDictObjectPtr__get_entries(int64_t)'`.

All of these are instances of the compiled-generator/cpp-emission project scope
(struct declaration coverage/ordering in standalone coroutine units,
unresolved-receiver method dispatch), not narrow fixes; not attempted here.
Every previously documented blocker (including 2026-08-10's last refusal,
`iteritems`'s mixed-shape yields) is nonetheless verified gone.

## Status (updated 2026-08-10, historical — superseded by 2026-08-23 above)

Implemented real tuple-valued-`yield` support this session (see
`gimple_codegen.py`'s `_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes`). Re-verified via an isolated compile: `items_from_keys_and_
values`'s `yield (pyop_key, pyop_value)` and `parse_location_table`'s
tuple yield are NO LONGER refused (both now compile past the
eligibility gate); the overall refusal list dropped from 4 names down
to 1.

**`PyDictObjectPtr.iteritems` remains refused**, for a DIFFERENT,
deeper reason than plain tuple-yield, unaffected by this fix: its body
has TWO yield sites of genuinely different shapes —
```python
for item in items_from_keys_and_values(keys, values):
    yield item                       # a bare identifier
...
yield (pyop_key, pyop_value)         # a literal 2-tuple
```
`yield item` (a bare identifier, delegated from another function's
already-tuple-shaped result) contributes the generic int64_t default
(this fix only recognizes a LITERAL tuple expression at the yield site
itself — it has no way to know `item` is already conceptually
tuple-shaped), while `yield (pyop_key, pyop_value)` contributes
`MojoList *` — these disagree, so `_generator_yield_ctype`'s
unification correctly refuses the whole function, the same way it
would for any two genuinely-disagreeing scalar types. Recognizing that
a bare-identifier yield site is ALSO tuple-shaped (when it demonstrably
is) is a separate, more general inference improvement, out of this
fix's scope. Doc kept open (not deleted) — 3 of 4 generators fixed, but
the file still doesn't build (both because of `iteritems` and because
none of these files build clean end-to-end regardless, per this
session's broader findings — see the other docs in this batch).

## Status (updated 2026-08-09, re-verified — supersedes the 2026-08-06 note below)

Re-ran against current master (`d0e4874`). The isinstance-tuple /
subscript C-syntax errors described in the 2026-08-06 note below no
longer reproduce at all — that code is never reached anymore. The
build now fails much earlier, before any C text is emitted, with a
hard, honest `RuntimeError` refusal out of `GimpleGen.gen_module`:

```
cannot compile module: function(s) items_from_keys_and_values,
iter_locals, iteritems, parse_location_table (generator function(s),
contain a `yield`/`yield from`) — this codegen compiles every function
into a single straight-line C function and has no suspend/resume
state-machine transform for generators, nor an event loop /
suspend-resume codegen for async functions, yet, so these cannot be
represented as compiled C without emitting silently wrong or broken
code; falling back to interpreting this module from source instead
```

`MOJO_DEBUG=1` shows the specific cause for all four:

```
generator 'parse_location_table' not eligible for C++ coroutine path:
  every `yield` must carry a value, and all values must agree on one
  scalar type (int64_t/double/_Bool)
generator 'items_from_keys_and_values' not eligible: same reason
generator method PyDictObjectPtr.'iteritems' not eligible: same reason
generator method PyFramePtr.'iter_locals' not eligible: same reason
```

Confirmed by reading the source: every one of these four generators
`yield`s a tuple, not a scalar —
`items_from_keys_and_values`/`PyDictObjectPtr.iteritems`/
`PyFramePtr.iter_locals` all `yield (pyop_key, pyop_value)` (or
`yield (pyop_name, pyop_value)`), and `parse_location_table` does
`yield addr, end_addr, None` (a 3-tuple). This is the SAME well-known,
already-documented, deliberately-out-of-scope limitation as
`bugs/CODEGEN_generator_function_Lib_weakref.md` (`WeakValueDictionary
.items`/`WeakKeyDictionary.items` both `yield key, value`) and several
other `bugs/CODEGEN_generator_function_Lib_*.md` docs: the C++20
coroutine codegen this compiler uses for generator functions only
supports a scalar (int64_t/double/_Bool) yield-value type — a
`yield`ed tuple/object needs a whole new pointer-typed promise/value
representation in that coroutine machinery (`_gen_cpp_generator_unit`
and friends), which is a structural, feature-sized extension to shared
generator-codegen machinery, not a narrow one-spot fix. Per this
project's history of "narrow-looking" fixes to this exact class of
shared machinery causing broad silent regressions, this is
deliberately NOT attempted here — left as an accurate, honest
structural-limitation record instead. `relaxed_imports` (which would
turn this into a per-function stub-and-continue instead of a hard
raise) is never set `True` for a root module by `mojo.py`'s own build
entry points, so this is a hard, whole-module refusal for this file as
things stand today, independent of the two now-stale findings below.

## Status (updated 2026-08-06, historical — superseded, kept for context)

Re-ran; current errors include real C syntax errors (not just type
mismatches):

```
error: expected ')' before ',' token
error: expected expression before '(' token
error: 'pyop_key' undeclared (first use in this function); did you mean 'proxy_key'?
```

The first two point at:
```python
if isinstance(pyop_attrdict, (PyKeysValuesPair, PyDictObjectPtr)):
```
(a 2-type `isinstance(x, (A, B))` tuple form) and:
```python
ep = entries[i]
```
(subscripting a GDB-specific proxy value). Investigated
`_lower_builtin_isinstance` (`gimple_codegen.py`) directly — the
`TupleExpr` branch there DOES already handle the multi-type
`isinstance(x, (A, B, ...))` form correctly (OR-combining each
alternative), so the malformed C is NOT obviously from that function;
the generated `.ci` didn't retain a matching `#line 431` directive to
confirm exactly what WAS emitted at that point (possibly stale between
build attempts, or the enclosing function was dropped/restructured).
Not root-caused further within this session's time budget — the file
mixes several unusual, GDB-specific patterns (`gdb.Value` proxy
subscripting, multi-type `isinstance`, an `_undeclared` identifier
suggesting a totally separate name-typo-adjacent codegen issue for
`pyop_key`/`pyop_value` inside `items_from_keys_and_values`) that would
need a dedicated, focused session to untangle individually. Flagging
for follow-up rather than guessing at a fix.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py: In function '_alloc_BuiltInFunctionProxy':
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py:329:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  329 |           NotImplementedError: Symbol type not yet supported in Python scripts.
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py: In function '_alloc_BuiltInMethodProxy':
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py:343:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  343 |             # class
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py: In function '_alloc_Frame':
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py:357:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  357 |                     }
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py: In function '_alloc_InstanceProxy':
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py:371:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  371 |             return PyBytesObjectPtr
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py: In function '_alloc_ProxyAlreadyVisited':
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py:385:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  385 |     def from_pyobject_ptr(cls, gdbval):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py: In function '_alloc_ProxyException':
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py:399:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  399 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py: In function '_alloc_PyCodeArrayPtr':
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py:413:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  413 |     loops in the object graph.
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py: In function '_alloc_PyFramePtr':
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py:427:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  427 |     out.write('<')
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py: In function '_alloc_PyKeysValuesPair':
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py:441:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  441 |             pyop_val.write_repr(out, visited)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py: In function '_alloc_PyObjectPtr':
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py:455:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  455 |             kwargs = ', '.join(["%s=%r" % (arg, val)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py: In function '_alloc_PyObjectPtrPrinter':
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py:469:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  469 |                (_sizeof_void_p() - 1)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py: In function '_alloc_PyTypeObjectPtr':
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py:483:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  483 |             typeobj = self.type()
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py: In function '_alloc_TruncatedStringIO':
... (26095 more lines)
```

Exit code: 1
Elapsed: 14.25s
