# COMPILE_FAIL: Modules/_decimal/tests/randdec.py

Source file: `/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randdec.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-06)

Re-ran; current errors, two separate files:

```
error: assignment to 'char *' from 'int64_t' makes pointer from integer without a cast [-Wint-conversion]   (randfloat.py:222)
error: too many arguments to function 'mojo_nan'; expected 0, have 1    (randdec.py:112)
```

The second is a genuinely new, distinct, well-scoped finding: this
codebase defines its own top-level `def nan():` (no args, a random-
decimal-string generator, unrelated to the C math library). This
codegen unconditionally maps the bare name `nan` to the C99 math
library `nan(const char *tagp)` function (`gimple_codegen.py`'s
builtin-passthrough table, `'nan': ('double', ['char *'])`) whenever it
sees a call to a name called `nan` — it does NOT check whether the
current module/program has its OWN user-defined function of that exact
name that should take priority. Real Python has no such ambiguity (the
math C function is never bound to the bare name `nan` at the Python
level at all — only `math.nan`, a constant, exists) — this is purely a
codegen-side name-collision between a hardcoded "known C builtin" table
and ordinary user code that happens to reuse a name from that table.
`randfloat.py`'s own error was not investigated further (a
"placeholder"-style global getting the wrong initial type is a
plausible but unconfirmed guess, given the pattern seen in several
other files this session).

Not fixed here. The `nan` collision looks narrow and safe-ish to fix in
isolation (check `struct_field_types`/top-level function names for a
user-defined override before consulting the builtin-passthrough table)
but wasn't attempted given this session's general caution after the
Phase 1.7 attempt turned out broken — a fix here should be scoped
FIRST to just adding "does a user-defined function/name shadow this
builtin" checks ahead of the builtin table lookup, verified against the
full quality gate, since the builtin-passthrough table is used broadly.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py: In function 'test_short_halfway_cases':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:211:11: warning: variable '_t121' set but not used [-Wunused-but-set-variable]
  211 |     '00000000000000000000000000000000000000000000000000' #...
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:209:11: warning: variable '_t119' set but not used [-Wunused-but-set-variable]
  209 |     '00000000000000000000000000000000000000000000000000' #...
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:207:11: warning: variable '_t117' set but not used [-Wunused-but-set-variable]
  207 |     # tough cases for ln etc.
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:205:11: warning: variable '_t115' set but not used [-Wunused-but-set-variable]
  205 |     '1',
      |           ^    
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:199:11: warning: variable '_t109' set but not used [-Wunused-but-set-variable]
  199 |     '0000000000000000001',
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:192:11: warning: variable '_t102' set but not used [-Wunused-but-set-variable]
  192 |     '00000000000000000000000001',
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:181:11: warning: variable '_t91' set but not used [-Wunused-but-set-variable]
  181 |     '000000000100000000000000000000000000000000000000000' #...
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:179:11: warning: variable '_t89' set but not used [-Wunused-but-set-variable]
  179 |     '000000000000000000000000000000000000000000000000005',
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:177:11: warning: variable '_t87' set but not used [-Wunused-but-set-variable]
  177 |     '000000000000000000000000000000000000000000000000000' #...
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:175:11: warning: variable '_t85' set but not used [-Wunused-but-set-variable]
  175 |     '000000000000000000000000000000000000000000000000001',
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:169:11: warning: variable '_t79' set but not used [-Wunused-but-set-variable]
  169 |     '000000000000000000000000000000000000000000000000000' #...
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:162:11: warning: variable '_t72' set but not used [-Wunused-but-set-variable]
  162 |     '0.9999999999999999999999999999999999999999999999999' #...
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:161:10: warning: variable 's' set but not used [-Wunused-but-set-variable]
  161 |     '0.99999999900000000025',
      |          ^
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:131:11: warning: variable '_t46' set but not used [-Wunused-but-set-variable]
  131 |             s = random.choice(signs)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:105:11: warning: variable 'upper' set but not used [-Wunused-but-set-variable]
  105 |     # with n
      |           ^~   
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py: In function 'test_halfway_cases':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/randfloat.py:141:11: warning: variable '_t57' set but not used [-Wunused-but-set-variable]
  141 |             if random.choice([True, False]):
... (438 more lines)
```

Exit code: 1
Elapsed: 14.09s
