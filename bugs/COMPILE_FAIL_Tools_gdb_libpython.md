# COMPILE_FAIL: Tools/gdb/libpython.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

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
