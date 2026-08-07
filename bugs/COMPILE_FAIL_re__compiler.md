# COMPILE_FAIL: Lib/re/_compiler.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (root-caused 2026-08-07, Track B continuation session — still NOT fixed, see below)

Root cause fully confirmed via a minimal standalone repro and direct
tracing through `gimple_codegen.py` (superseding the 2026-08-06 note's
partial guess, which was on the wrong track — this is unrelated to
`CODEGEN_multi_assign_local_var_type_not_inferred.md`):

```
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:187:17: error: invalid operands to binary - (have 'int64_t' {aka 'long long int'} and 'MojoList *')
```

at `code[tail] = _len(code) - tail`, inside:
```python
for tail in tail:
    code[tail] = _len(code) - tail
```
— a genuine, if unusual, Python idiom: the loop TARGET variable
(`tail`) has the SAME NAME as the list being iterated (also `tail`, an
outer local — Python's own well-known "don't shadow your iterable"
footgun, but perfectly legal syntax that really does rebind `tail` to
each element in turn, discarding the original list reference by the
time the loop ends).

**Root cause**: `_gen_for_list` (gimple_codegen.py, ~line 20060) calls
`self._declare_var(var, elem)` to bind the loop variable's C-level type.
`_declare_var` (~line 6592) has a `if name not in self.var_types:` guard
— it ONLY registers a NEW type/declaration the FIRST time a given
Python name is seen; every later call for the SAME name is a deliberate
no-op (this is intentional, load-bearing behavior for the common,
different case of the SAME loop-variable name reused across two
SEPARATE sibling `for` loops with different element types — see that
function's own neighboring comments about "first-decl-wins... the
per-type assignment... boxes/coerces"). Here, though, `tail` was
ALREADY registered as `MojoList *` (the outer list) BEFORE this same
`for` statement even started iterating it — so `_declare_var` silently
skips updating `self.var_types['tail']` to the real per-iteration
element type (`int64_t`), even though the loop body's C statements DO
correctly assign the current int64_t element value into `tail`'s (still
`MojoList *`-declared) C variable. `self.var_types['tail']` stays stale
at `'MojoList *'` for the rest of the function, so `_type_of('tail')`
(consulted by `_lower_IdentExpr`'s plain-local-read case, ~line 8195)
reports the WRONG type for every later read of `tail`, including the
`- tail` in `_len(code) - tail` — producing this GIMPLE type error
instead of the int64_t subtraction the code actually needs.

**Minimal repro** (confirmed against `gimple_codegen.compile_to_gimple`
directly, not just this real-world file):
```python
fn main():
    var tail = [1, 2, 3]
    var code = [10, 20, 30, 40]
    for tail in tail:
        code[tail] = code[tail] - tail
```
Reproduces the identical `invalid operands to binary -` error.

## Not fixed

A real fix needs to distinguish THIS shape (the loop target's name
collides with its OWN iterable, within the SAME `for` statement) from
the deliberate "same loop-var name reused across sibling loops" shape
`_declare_var`'s current no-op guard exists to support — those need
opposite behavior (rebind the type vs. keep-and-coerce to the first
type). Doing this correctly and generally means either (a) teaching
`_gen_for_iter`/`_declare_var` to detect the self-shadowing case
specifically and mint a genuinely fresh, non-colliding C variable name
for the loop's redeclaration (the iterable's OWN already-lowered C
value must be captured into a stable temp FIRST, since `_lower_
IdentExpr`'s plain-read case returns the bare C variable name itself,
not a copy — reusing the literal identifier `tail` for a second,
differently-typed C declaration in the same function is not otherwise
possible), done consistently across ALL of `_gen_for_iter`'s ~7
per-iterable-kind branches (`_gen_for_list`/`_gen_for_dict`/`_gen_for_
set`/`_gen_for_str`/`_gen_for_cstr`/`_gen_for_struct_iter`/`_gen_for_
generator_iter`, each computing its own element type differently), or
(b) a narrower single-branch fix (this file only hits the `_gen_for_
list` case) that still needs the same "capture the iterable's value
before evicting the stale registration, then re-declare under a fresh
C name" shape. Assessed as more than the "genuinely tractable" bar for
this pass given the number of branches and the need to avoid regressing
the deliberate, existing "reused loop-var name across sibling loops"
convention `_declare_var`'s current behavior protects — not attempted.
Worth a focused, independently-verified follow-up (only one confirmed
real-world occurrence so far, so not promoted to `bugs/hard/` yet).

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:70:11: warning: unused variable '_tag' [-Wunused-variable]
   70 |                 lo = tolower(av)
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:75:11: warning: unused variable '_tag' [-Wunused-variable]
   75 |                     emit(OP_UNICODE_IGNORE[op])
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:80:11: warning: unused variable '_tag' [-Wunused-variable]
   80 |                     if op is NOT_LITERAL:
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:95:11: warning: unused variable '_tag' [-Wunused-variable]
   95 |                     emit(IN_LOC_IGNORE)
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:104:13: warning: unused variable '_tag' [-Wunused-variable]
  104 |                 code[skip] = _len(code) - skip
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py: In function '_compile_06e87d':
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:59:11: warning: variable 'fixes' set but not used [-Wunused-but-set-variable]
   59 |         if op in LITERAL_CODES:
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:58:11: warning: variable '_var_tolower' set but not used [-Wunused-but-set-variable]
   58 |     for op, av in pattern:
      |           ^~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:57:11: warning: variable 'iscased' set but not used [-Wunused-but-set-variable]
   57 |             tolower = _sre.ascii_tolower
      |           ^ ~~~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:56:11: warning: variable 'ASSERT_CODES' set but not used [-Wunused-but-set-variable]
   56 |             iscased = _sre.ascii_iscased
      |           ^ ~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:54:11: warning: variable 'SUCCESS_CODES' set but not used [-Wunused-but-set-variable]
   54 |             fixes = _EXTRA_CASES
      |           ^ ~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:52:11: warning: variable 'REPEATING_CODES' set but not used [-Wunused-but-set-variable]
   52 |             iscased = _sre.unicode_iscased
      |           ^ ~~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:50:11: warning: variable 'LITERAL_CODES' set but not used [-Wunused-but-set-variable]
   50 |     if flags & SRE_FLAG_IGNORECASE and not flags & SRE_FLAG_LOCALE:
      |           ^~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:47:11: warning: variable '_len' set but not used [-Wunused-but-set-variable]
   47 |     iscased = None
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py:45:11: warning: variable 'emit' set but not used [-Wunused-but-set-variable]
   45 |     SUCCESS_CODES = _SUCCESS_CODES
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/re/_compiler.py: In function '_compile_charset_132aaf':
... (1377 more lines)
```

Exit code: 1
Elapsed: 11.63s
