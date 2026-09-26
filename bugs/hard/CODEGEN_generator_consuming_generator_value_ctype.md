# HARD BUG: a generator that consumes a sibling generator mis-types the value — `int64_t` instead of the callee's real `value_ctype`, silently

**State: OPEN.** NEW 2026-09-26. Root-caused, not fixed. A generator consuming a sibling generator types
the yielded value as int64_t instead of the callee's real value_ctype -- silent, and it
compounds along a consumption chain. The fix is a fixpoint over value_ctype derivation;
the existing retry machinery cannot help because the consumer never raises.


## Status (2026-09-26 — root-caused to a phase-ordering gap in gimple_codegen's pipeline; NOT fixed, minimal repro + evidence chain recorded)

Found while auditing
`COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md`, where it was the real
cause behind that doc's `iter_files_by_suffix` "call to unresolved callee"
entry. It is **not** fsutil-specific and not a compile failure — it is a
silent miscompile affecting any module where one generator consumes
another.

### Minimal repro

```python
def inner():
    yield "a.txt"

def outer(g):
    for f in inner():
        if f.endswith(".txt"):
            yield f

def main():
    for v in outer("x"):
        print(v)
```

Prints a raw pointer (`4308653504`). Correct output is `a.txt`.

### The value is correct; only the TYPE is wrong

This is the whole reason it is easy to misdiagnose as a dangling pointer.
Established by reading the emitted GIMPLE, in this order:

1. `__mgco_inner_body` yields `_slit_10000`, and that slot **is** properly
   defined and statically initialized (`static char * _slit_10000 =
   "a.txt";`). The string literal is not the problem.
2. Inside `__mgco_outer_body`, the loop variable is declared correctly:
   `char * f;`, fed by `__mgco_inner_value`. So the consumer's *emission*
   is fine.
3. But `_generator_api['outer']['value_ctype']` is **`int64_t`**, not
   `char *`. So `v` in `main` is an `int64_t` and `print(v)` renders the
   pointer's bit pattern. The bytes were always right; the static type is
   what got lost.

Instrumented confirmation — the loop lowering is handed a correct api for
the inner generator, and a wrong one for the outer:

```
[iter] var='f' base='__mgco_inner' vct='char *'
[iter] var='v' base='__mgco_outer' vct='int64_t'
```

### Root cause: `lower()` runs before `register()`

In `gimple_codegen.py`'s compile pipeline:

```python
stmts, _coro_meta = gimple_gen_coro.lower(stmts)   # (1) derives each value_ctype
gen = GimpleGen(...)
gimple_gen_coro.register(gen, _coro_meta)          # (2) populates gen._generator_api
```

Phase (1) is what derives a generator's `value_ctype` from its body's local
variable types — **including** the loop variable of
`for f in <sibling generator>():`. But `_generator_api` is only populated
in phase (2). So during phase (1) the consumer cannot know `inner` yields
`char *`; it types `f` as the `int64_t` default and propagates that into
its OWN `value_ctype`. The wrong type is then registered and reused by
every later consumer, including an ordinary `fn main()`.

The defect therefore **compounds along a chain**: `a` consumed by `b`
consumed by `c` gives `b` and `c` both `int64_t`, and the damage reaches
everybody downstream of the first mis-typed hop.

### Why it is NOT another retry pass

`gen_module` already runs a multi-pass fixpoint retry for a consumer that
cannot see a not-yet-compiled sibling, and the C++ coroutine path has a
matching guard (`_cpp_iterable_is_delegatable_generator_call`, which
consults `_all_generator_names` and raises `_UnsupportedGeneratorShape` to
force a retry). Neither helps here, and the reason is the important part:
**the consumer never raises.** It succeeds, with the wrong type. There is
nothing to retry, so the existing machinery is structurally blind to it.

### Fix direction (not yet written)

A fixpoint over phase (1)'s `value_ctype` derivation itself: seed each
generator's `value_ctype`, use it to type the loop variable of any sibling
generator that generator consumes, re-derive, and iterate until stable —
*then* lower the bodies. Not another retry pass, and not a special case in
the emitter.

The open question is convergence for genuinely cyclic value typing
(`a` yields what `b` yields and `b` yields what `a` yields). That case has
no consistent answer and should end as an honest refusal, not a fixed point
at whatever the last iteration happened to say.

### Blast radius

Any module where a generator consumes another generator is affected; it is
only *visible* when the callee's `value_ctype` is a pointer, because an
`int64_t` is a silent no-op. Strings and bytes are the common case — which
is exactly why `fsutil`'s path-yielding generators surfaced it. A
`double`-yielding callee should be checked too: it would surface as an
int64/double confusion rather than a pointer, which is a *different* wrong
answer from the same root cause.
