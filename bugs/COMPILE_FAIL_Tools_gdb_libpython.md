# COMPILE_FAIL: Tools/gdb/libpython.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/gdb/libpython.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-06)

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
