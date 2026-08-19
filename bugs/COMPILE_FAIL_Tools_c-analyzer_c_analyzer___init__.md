# COMPILE_FAIL: Tools/c-analyzer/c_analyzer/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-14)

Still fails to compile as a whole module, but two of the module's four
generators (`analyze_decls`, `check_all`) and the `**kwargs`-forwarding
shape of a third (`iter_analysis_results`) have since been fixed —
tracked separately below. The file's remaining blocker is now narrower
and genuinely structural (dynamic-callee `**kwargs` forwarding inside
`iter_decls`), not the "gap padded with static defaults" miscompile risk
this doc previously investigated.

### Fixed: `**kwargs` forwarded to a statically-known callee inside a
### compiled generator/coroutine body (real runtime dict lookup, not a
### static-default guess)

`gimple_codegen.py`'s coroutine-body expression emitter (`_cpp_expr`'s
`CallExpr` handling, ~line 24170) used to refuse ANY call inside a
compiled generator/coroutine body whose arguments included a `*`/`**`
spread — including the narrow, provably-safe case of `f(pos...,
**kwargs_var)` where `f` is a statically-known local free function (not
a dynamically-obtained callee). An earlier attempt at supporting this
narrow case (never merged — reverted before landing) filled the "gap"
between the given positional args and `f`'s `**kwargs` slot with `f`'s
STATIC DEFAULT VALUES, ignoring what the caller's kwargs dict actually
contains at runtime: `target(i, **kwargs)` with `kwargs = {'b': 5}`
would have silently computed `b=100` (the hardcoded default) instead of
the real override `b=5` — a WORKING WRONG ANSWER, strictly worse than
refusing to compile.

Fixed properly this time (`GimpleGen._cpp_try_kwargs_forward_call`,
gimple_codegen.py): each "gap" parameter is now resolved with a REAL
runtime lookup against a COPY of the caller's kwargs dict
(`mojo_dict_contains` + `mojo_dict_pop_int`, falling back to the static
default only when the key is genuinely absent at runtime), and the
copy's unconsumed remainder is forwarded into the callee's own
`**kwargs` parameter. The dict is copied — never mutated in place —
because the spread variable is commonly reused across a caller's own
loop iterations (this bug's own repro: `while i < n: yield target(i,
**kwargs)`; popping straight from the shared dict on iteration 1 would
silently lose the override for iterations 2/3).

Only fires when it can PROVE the shape is exactly this (every gap
parameter is a plain `int64_t`-typed, in-order, defaulted parameter with
no real `*args` in between, and the callee is a statically-known
ordinary free function — never a generator/async function, which has no
directly-callable C symbol, and never a dynamically-obtained callable).
Returns `None` (never guesses) for anything else, falling through to the
pre-existing honest refusal unchanged.

A closely related, independent bug was found and fixed in the same
session: the ORDINARY (non-coroutine-body) call path that constructs a
compiled generator from a literal-keyword-argument call site (`gen_forward(3,
b=5)`, `_lower_call`'s `fname_raw in self._generator_api` branch, ~line
14330) padded a callee generator's `**kwargs` C-signature slot the same
unsafe way `_func_kwargs_slot`'s own docstring already documents for
ordinary (non-generator) functions: it popped the next literal keyword
argument's raw lowered VALUE straight into whichever positional slot
came next, with no awareness that one particular slot is a `MojoDict *`
— emitting `_t4 = (MojoDict *)_t3` (an integer reinterpreted as a dict
pointer), which segfaults the instant the generator body reads its own
`**kwargs`. This blocked the bug's own repro's *outer* `gen_forward(3,
b=5)` call even after the coroutine-body fix above, since Python's
top-level `for v in gen_forward(3, b=5):` hits this exact call site.
Now packs into a real `MojoDict *` via the same `_pack_kwargs_dict` the
ordinary path already uses, mirroring rather than duplicating that
established, correct logic.

**Verified against the exact repro this doc originally specified**
(`target`/`gen_forward`, `b` overridden via `**kwargs`) — the interpreter
(`python3 mojo.py run`) and the compiled path (`python3 mojo.py build ...
&& <out>`) now both print `205`, `206`, `207` (not `300`, `301`, `302`,
the wrong values a static-default guess would produce). Also verified
the no-override case (`gen_forward(3)`, no `b=`) still gets the real
defaults, `300`/`301`/`302`, on both paths.

Also verified the fix degrades safely (honest refusal, not a miscompile)
for two adjacent shapes it deliberately does NOT attempt: `**kwargs`
forwarded into a callee that is ITSELF a compiled generator (`g = inner(n,
**kwargs)` inside another generator body), and a `for x in
subgen(**kwargs):` sub-generator-delegation call site (a separate,
pre-existing gap in a different piece of codegen entirely, untouched by
this fix) — both still refuse cleanly with no bad C++ ever emitted.

Full 5-part quality gate run clean: `test_gimple.py` 247/247,
`test_module_cache.py` 76/76, `make check-selfhost` clean (an early
attempt at this fix used a nested-tuple-unpack `for` loop shape gcc's
`-fgimple` self-host compile of `gimple_codegen.py` itself couldn't
lower — caught by this exact gate step, per CLAUDE.md's warning, and
rewritten to a plain index loop), a from-scratch stdlib dylib rebuild
with 0 `skip <module>:` lines, and `compile_stdlib.py` (no `-j`) 664/664
with 0 unexpected failures.

### Still failing: `iter_decls`'s `**kwargs` forwarded to a DYNAMIC
### (parameter-valued) callee — genuinely structural, not attempted

```python
def iter_decls(filenames, *,
               kinds=None,
               parse_files=_parse_files,
               **kwargs
               ):
    ...
    parsed = parse_files(filenames, **kwargs)
```

`parse_files` here is a PARAMETER — a callable VALUE the caller may
override at runtime (`parse_files=_parse_files` is only its default) —
not a statically-known local free function. There is no way to know at
compile time which real function's parameter names/defaults `**kwargs`
would need to be resolved against, so the fix above correctly and
deliberately refuses this shape (`_cpp_try_kwargs_forward_call` requires
`fname_raw in self.func_param_types`, which only registers real
`FunctionDef`s, not parameter names). This is the same fundamental
limitation the ORIGINAL 2026-08-06/09 investigations of this file
flagged for codecs.py's analogous `getincrementalencoder(encoding)(errors,
**kwargs)` shape — a dynamically-obtained callee's real signature simply
isn't known at compile time in this codegen's model. Genuinely
structural; not attempted.

```
[gimple_codegen] generator 'iter_decls' not eligible for C++ coroutine
path, falling back to honest refusal: a `*`/`**`-unpack call argument is
not supported in a compiled generator/coroutine body
Error building: cannot compile module: function(s) iter_decls (generator
function(s), contain a `yield`/`yield from`) — this codegen compiles
every function into a single straight-line C function and has no
suspend/resume state-machine transform for generators, nor an event loop
/ suspend-resume codegen for async functions, yet, so these cannot be
represented as compiled C without emitting silently wrong or broken
code; falling back to interpreting this module from source instead
```

Because the whole MODULE still refuses to compile (one ineligible
generator is enough), `iter_analysis_results`'s own `**kwargs`-forwarding
call site (`decls = iter_decls(filenames, **kwargs)`, forwarding into
`iter_decls` — itself a generator, not an ordinary function) never
actually gets exercised end-to-end in this file. Confirmed via a
dedicated minimal repro (`g = inner(n, **kwargs)` where `inner` is
itself a compiled generator) that this shape correctly and safely
refuses on its own (`_cpp_try_kwargs_forward_call` explicitly excludes
any callee in `self._generator_api`/`self._async_api`) rather than
mis-compiling — so fixing `iter_decls`'s dynamic-callee case above is
the sole remaining blocker for this specific file.

(Separately, `iter_analysis_results`'s own Mojo/Python source has a
pre-existing typo unrelated to this codegen — its parameter is spelled
`filenmes` but its body reads `filenames` — a real `NameError` in actual
CPython too were this function ever called; not this codegen's concern.)
