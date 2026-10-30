# CODEGEN_generator_function: Lib/pickletools.py

## Status (2026-09-25, resumed session — BOTH COMPILE BLOCKERS LANDED; runtime file-object support remains)

Real forward progress landed this session; this doc remains open because the
verification bar is behavioral, not merely a successful build.

1. **Mixed-arity tuple yields are now semantically correct on A3.**
   `mojo/middle/coro.py` records each yield site's actual slot kinds, derives a
   max-width compatible consumer descriptor, and boxes every producer site at
   its ACTUAL arity. It does not pad a 3-tuple yield to the longest 4-tuple
   site: doing so would silently change `len(row)`, tuple equality, iteration,
   and everything a caller forwards from `pickletools.genops()`. New runnable
   regression `gen_tuple_mixed_arity_preserves_length` checks both the 3- and
   4-slot paths and observes the real yielded length.

2. **The `optimize(p)` bytes-slice inference blocker is fixed generally.**
   `_infer_param_types` now recognizes an unannotated parameter as
   `MojoBytes *` when a slice rooted at that parameter is assigned to a local
   already known to contain bytes (literals, `bytes(...)`, `bytearray(...)`,
   aliases, slices, and `+` chains are tracked to a fixed point). This is the
   positive destination signal Stage 2 had left open; it is not a
   destination-specific lowering hack. Regression coverage is in both
   `test_gimple.py` and `test_gimple_runner.py`, plus a negative list-slice test
   proving generic slices still infer `MojoList *`.

With both changes, the real Python 3.14 `Lib/pickletools.py` now:

- passes `compile_to_gimple(do_imports=False)`;
- passes link-mode `driver.compile_program` and links a native executable; and
- reaches runtime instead of being refused during compilation.

The resulting executable still cannot yet run the verification case. On a real
61-byte protocol-4 pickle it exits 1 during module initialization with
`AttributeError: bytes_types`. The emitted top-level initializer is currently:

```c
_t10 = _root_globals.pickle;
_t11 = _mojo_dispatch_getattr (_t10, "bytes_types");
_root_globals.bytes_types = _t11;
```

`pickle` is a link-mode module marker, not a live module object, so this is the
general **imported Python module-global accessor gap** (plain top-level
assignments are emitted with accessors, but `reflect.py` only advertises
struct-typed `VarDecl` globals and plain-import aliases do not register their
member globals as accessors). That global is semantically
`bytes_types = (bytes, bytearray)` and is consumed by
`isinstance(data, bytes_types)`, so fixing only the accessor would still leave
the runtime type-tuple representation open.

After that, the CLI/file-handle path still needs general support for:

- an in-memory `io.BytesIO(bytes)` object with `read(n)` and `tell()`;
- bounded `read(1)` / `tell()` on the existing `FILE *` handle representation;
- runtime discrimination between the polymorphic `MojoBytes *` and file-handle
  values passed to `_genops`; and
- the dynamically typed `opcode.arg.reader(data)` calls.

These are real general object/file-runtime features, not a narrow `_genops`
special case. The old lambda diagnosis is superseded for A3: the generated
callable-local path itself works once eligibility is reached.

### Quality gate for the landed partial fix

Green: `test_gimple.py` 311/0; `test_gimple_runner.py` 61/0;
`test_module_cache.py` 81/0; `make check-linkmode` 3/0;
`make check-selfhost` 1/0; clean stdlib dylib rebuild with 0 module skips;
`compile_stdlib.py` 664/0. `test_gimple_generator_runner.py` remains at its
known baseline 92 passed / 10 pre-existing legacy-path failures, and the new
mixed-arity case passes.

`make bootstrap` and `make check-native-dumpfull` both hit the documented
compiled-compiler failure / 20-minute timeout rather than producing a new
regression report. The focused A/B sweep measured `clean=156`, but a
stash-preserved committed-baseline sweep measured the expected `clean=157`;
set comparison found two transient new failures and one fixed file, and
regenerating all three individually made all three byte-identical. The two
new entries (`test_dispatch_promotions`, `test_dispatch_solver`) therefore
were not persistent regressions from this change; `fire_main` became clean.

## Status (2026-09-25, earlier checkpoint — arity and bytes inference in progress)

Feature-build pass on cluster B. Heterogeneous per-slot types across
yield sites are NOT the blocker here — the A3 tuple-yield model already
unifies those (new regression coverage: `gen_tuple_slot_str_or_none` /
`gen_tuple_slot_list_valued` in `test_gimple_generator_runner.py`).

`_genops`'s actual blocker is **variable tuple arity within one
generator**: `if yield_end_pos: yield opcode, arg, pos, getpos()` (a
4-tuple) vs `else: yield opcode, arg, pos` (a 3-tuple), selected by the
`yield_end_pos` bool parameter. The A3 model requires (reasonably —
per the cluster-B design note) that all yields in one generator agree
on tuple LENGTH; only slot TYPES may vary. Supporting a
parameter-selected tuple shape would need either specialization on the
bool arg or a max-arity padded representation with a runtime "slot
present" flag — genuinely feature-sized and not bounded. The
`getpos`-lambda concern from earlier entries is moot (zero-arg lambda
through a local now works); arity is the sole remaining blocker.
Consumer `dis()` is also large but is downstream of this. No code
change to the generator model for this file.

## Status (2026-09-07 — cluster B is the gating blocker; cluster A not reachable)

`_eligible` for `_genops` fails at `_generator_value_kind`: "tuple yield
with inconsistent shape (v0)" — i.e. the A3 pre-pass rejects it on the
heterogeneous 4-tuple yield (cluster B) BEFORE the `getpos(...)`
callable-value site is ever reached. So no cluster-A work on this file is
possible until cluster B (tuple-yield) lands. And `getpos = data.tell`
off an opaque `data` has no safe compiled representation anyway (see the
glob doc's 2026-09-07 note — registering it for `mojo_maybe_bound_call`
would be a silent miscompile). No code change.

## Status (2026-09-05 — A3 stack-switch cutover: still REFUSED, clusters A + B)

`_genops` is the module's only generator. Still refused:

```
_genops: a call to unresolved callee 'getpos(...)' ... in a compiled
generator/coroutine body
```

`getpos` is a local bound to either `data.tell` (a bound method) or
`lambda: None`, then called — an opaque callable-value local
(**cluster A**, shared with `glob`/`os`/`test_frame`). `_genops` also
`yield opcode, arg, pos, getpos()` — a heterogeneous 4-tuple yield
(**cluster B**, shared with `modulefinder`/`os.walk`/`test_string`).
Both clusters are feature-sized; no incremental step landed this session.

## Status (re-verified 2026-08-26, worktree agent-aac0d33be914873b5 — independent re-verify, byte-identical, no change)

Independent fresh isolated `compile_to_gimple_with_cpp(do_imports=False,
MOJO_DEBUG=1)` repro on the real file: byte-identical refusal —
`_genops` refused for "a call to unresolved callee 'getpos(...)' is not
supported in a compiled generator/coroutine body" (`getpos = data.tell`,
a bound-method value off an opaque-typed parameter). Confirms the
wtOpencode_genlib3 entry immediately below. Even a hypothetical fix for
this one site would only expose the next opaque-receiver-dependent shape
in the same function body (`io.BytesIO` modeling, `data.read(1)`/
`opcode.arg.reader(data)` dynamically-typed chains, non-literal
`%`-format) — confirmed feature-sized by prior passes' full-body read.
Not attempted. No code change; doc stays open.

## Status (re-verified 2026-08-26, wtOpencode_genlib3): identical refusal

Fresh real `python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/
pickletools.py` against current master (f0f6e78): dies at pickletools'
own module compile with the byte-identical honest refusal —
`Unsupported shape(s): _genops: a call to unresolved callee
'getpos(...)' is not supported in a compiled generator/coroutine body...`
(twice: module-qualify pass + closure pass). None of the campaign
mechanisms landed since 2026-08-25 touch opaque-receiver bound-method
values. The 2026-08-25 entry's depth analysis stands (BytesIO,
`data.read(1)`/`opcode.arg.reader(data)` runtime-typed chains, non-
literal `%`-format all behind the first shape); feature-sized, out of
scope. No code change; doc stays open.

## Status (updated 2026-08-25, worktree fix/opencode-group2 — re-verified fresh; refusal unchanged, and confirmed deeper than `getpos`: the whole function body is dynamically-receiver territory)

Re-ran a fresh isolated
`compile_to_gimple_with_cpp(do_imports=False)` on the real
pickletools.py: `_genops` refuses on EXACTLY the 2026-08-24 entry's
shape — "a call to unresolved callee 'getpos(...)' is not supported in
a compiled generator/coroutine body" — unchanged by any of the
campaign fixes landed since (including `d0ecc2b`'s builtin-container-
methods-as-first-class-values, which covers dict/list/set receivers,
not opaque ones).

Re-assessed tractability once more before standing down, reading the
full coroutine-body call emitter (`_cpp_expr`'s CallExpr handling):
the `getpos = data.tell` branch is the FIRST unsupported shape, but it
is not plausibly the LAST even if a runtime bound-method-off-opaque-
receiver representation existed for it — the SAME function body also
needs `isinstance(data, bytes_types)` + `data = io.BytesIO(data)`
(no BytesIO model exists anywhere in this codegen), `data.read(1)` and
`opcode.arg.reader(data)` (calls through an entirely dynamically-
typed chain), and a `%`-format against non-literal pieces. Every one
of those is the same "the receiver's real type is only known at
runtime" family; a narrow `getpos`-only patch would trade today's one
honest refusal for the next one (or worse, silent stub values feeding
`pos` into every yielded opcode tuple). Confirmed feature-sized,
consistent with every prior assessment in this file. Doc stays open;
no code change; no gate run.


## Status (updated 2026-08-24, worktree fix/gen-core — the 2026-08-23 "`_genops` now compiles" claim was stale; `_genops` refuses again, honestly, on a real remaining gap)

Re-verified from scratch (a real `python3 fire.py build .../Lib/
pickletools.py`, and an isolated `compile_to_gimple_with_cpp(do_imports
=False)` matching the exact repro the entry below used). Both now
raise: `` cannot compile module: function(s) _genops (generator
function(s), contain a `yield`/`yield from`) ... Unsupported shape(s):
_genops: a call to unresolved callee 'getpos(...)' is not supported in
a compiled generator/coroutine body (not a builtin this emitter
supports, a known module-level/imported function, a same-module struct
constructor, or a declared callable-value local).`` — i.e. the exact
refusal the entry below says was closed.

This is not a regression of the tuple-yield fix; it's a LATER same-day
commit (`fd909e9`, "generators: refuse unresolved callees honestly")
converting what used to be a silent bare-identifier miscompile into an
honest `_UnsupportedGeneratorShape` refusal. Before `fd909e9`, `_cpp_
expr`'s CallExpr fallback emitted ANY unresolved callee as a bare `name
(...)` C++ call unconditionally — including `getpos()` after `pickletools.
py:2273`'s `getpos = data.tell` (a bound-method-VALUE assignment off a
PARAMETER of unknown/opaque type, not a known struct), which is invalid
C++ whenever `getpos`'s declared type isn't the coroutine model's one
callable-value category (`_CPP_CALLABLE_CTYPE`) — which it wasn't here,
since `_cpp_is_callable_value_expr` only recognizes a bound method off
`self` or an already-known STRUCT-typed local, not an opaque/unknown-
typed one like `data`. So the 2026-08-23 entry's "compiles clean"
verdict was checking only that the Python call didn't raise — it never
ran the emitted text through a real C++ compiler, and would have
produced silently-broken output had the whole-program build reached
codegen for this function before `fd909e9` landed same-day.

**Current, accurate state**: `_genops`'s `getpos = data.tell` /
`getpos = lambda: None` (branch-dependent bound-method-or-lambda local,
then called later as `getpos()`) is a genuine instance of this
codegen's already-documented "opaque callable value has no
representation" structural gap — the same family as `Lib/operator.py`'s
`attrgetter`/`itemgetter` blocker (`bugs/CODEGEN_generator_function_Lib_
tempfile.md`'s 2026-08-11 entry) and `Lib/codecs.py`'s kwargs-spread-
against-dynamic-callee blocker. Extending `_cpp_is_callable_value_expr`
to cover a bound method off an OPAQUE (not statically-known-struct)
receiver would need real runtime bound-method dispatch for arbitrary
values, not a narrow one-spot fix — not attempted here, consistent with
this cluster's established scoping for the sibling cases. Doc stays
open; every prior "generator-codegen gap closed" claim below this entry
about `_genops` specifically should be read as superseded by this one.

## Status (updated 2026-08-23, worktree branch fix/gen-lib-b — the last generator gap (varying-arity tuple yields) FIXED; `_genops` now compiles; file still blocked by transitive-only errors)

Stacked gap 3 from the 2026-08-11/08-20 entries below is now closed:
`_generator_tuple_yield_slot_ctypes` no longer refuses differing element
COUNTS across tuple-yield sites. It unifies to the LONGEST site's shape
(pad shorter sites' slot lists with the longer site's tail types,
first-contributing-site-wins per tail position), and the producer side
(`_cpp_yield_tuple`) boxes every site out to the unified arity using a
pre-body-emission slot pass stashed on the gen (`_cpp_pending_tuple_slots`,
set in `_gen_cpp_generator_unit` before body emission since the post-emission
slot computation runs too late to influence emission) — so every
`co_yield`'d list carries exactly the unified arity and consumer-side
per-slot accessor reads stay in bounds. `(True, None)` now means only an
irreconcilable per-slot TYPE disagreement. Commit f7cf084.

Verified against this file's real `_genops`: the 3-tuple site
(`yield opcode, arg, pos`) now boxes `[opcode, arg, pos, 0]` and the
gated 4-tuple site is unchanged; both eligibility passes unify to 4 slots.
Isolated `compile_to_gimple_with_cpp(do_imports=False)` on pickletools.py:
compiles clean, `_genops` emitted through the coroutine path (previously
the hard refusal). A real `python3 fire.py build .../Lib/pickletools.py`
now shows **0 errors attributed to pickletools.py's own source** — the
build still exits non-zero solely on the already-documented transitive
cascade (`codecs.py`, `argparse.py`, `enum.py`; e.g. argparse's
`invalid operands to binary %` ×12 / `trunc_mod_expr` ×10 clusters).
Doc kept open per convention (file doesn't build end-to-end), but every
generator-codegen gap this doc was tracking is now closed.

Quality gate for the change: `test_gimple.py` 250/250, `test_module_cache.py`
76/76, `make check-selfhost` clean, from-scratch stdlib dylib rebuild
0 `skip <module>` lines (same as baseline).

## Status (updated 2026-08-20, two of three stacked gaps CLOSED — one remains)

`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md` is now fixed
for the shape this file needs: `gimple_codegen.py` gained a real
callable-value declared-type category for the coroutine (`.cpp`)
codegen (`_CPP_CALLABLE_CTYPE = 'std::function<int64_t()>'`), a
`LambdaExpr` case in `_cpp_expr` that emits a native, capturing C++
lambda for a zero-argument lambda literal, and a bound-method-as-VALUE
case in the same `MemberExpr` handling (`self.<method>` and
`<struct-pointer local>.<method>`, not immediately called) that wraps
the method's already-known mangled C symbol in an equivalent capturing
lambda — both convertible to the one declared type, and callable at
the use site as a plain `name()` with no separate call-site change
needed (`std::function::operator()`). This closes stacked gaps 1 (the
opaque-callable-value category) and (most of) gap 2's mechanism from
the 2026-08-11 update below — re-verified directly against
`_genops`'s own two-line, two-branch shape.

Re-verified via `MOJO_DEBUG=1` + a direct `compile_to_gimple_with_cpp`
call against the real `Lib/pickletools.py`: the `LambdaExpr` refusal is
GONE. `_genops` now fails for a DIFFERENT, single remaining reason —
stacked gap 3 from the 2026-08-11 update, unchanged and NOT attempted
here (out of this task's scope):
```
[gimple_codegen] generator '_genops' not eligible for C++ coroutine
path, falling back to honest refusal: _genops: every `yield` must
carry a value, and all values must agree on one scalar type
(int64_t/double/_Bool)
```
`_genops` yields both a 3-tuple (`yield opcode, arg, pos`) and a
4-tuple (`yield opcode, arg, pos, getpos()`) at two call sites in the
same body — the tuple-valued/varying-arity-yield structural gap,
entirely independent of `LambdaExpr`/bound-methods. This file's `fire.py
build` therefore still fails end-to-end; doc kept open (not deleted —
see `bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`'s own
2026-08-20 update for why THAT doc's LambdaExpr-specific scope IS
closed even though this file as a whole is not yet unblocked).

## Status (updated 2026-08-11, real fix attempted — found genuinely stacked, not narrow)

Re-verified against current master via a real `python3 fire.py build
/Users/mrs/net/Python-3.14.6/Lib/pickletools.py`: identical `_genops`/
`LambdaExpr` refusal reproduces exactly, unchanged from below.

This time actually attempted a real fix rather than re-confirming the
classification: traced what it would take to make `getpos = lambda:
None` compile (lift the lambda to a real non-capturing C++ function,
give `getpos` the existing "opaque callable pointer" `int64_t`
convention `_cpp_stmt`'s bare-call branch already uses via
`mojo_fnptr_call_N`, and add a matching VALUE-producing-call case to
`_cpp_expr`'s `CallExpr`/`IdentExpr` branch — that call form only
exists today in `_cpp_stmt`'s value-discarding bare-`ExprStmt` case,
around `gimple_codegen.py:24846`, not in `_cpp_expr` itself, so `pos =
getpos()` — a VALUE use — has no path to it either).

That alone would not unblock this file — `_genops` has (at least) two
further, independent stacked gaps in the exact same function body,
confirmed by reading both `gimple_codegen.py` and the real source
(`pickletools.py:2268-2298`):

1. The `if hasattr(data, "tell"): getpos = data.tell` branch (the
   sibling of the `lambda` branch, same `getpos` local) assigns a
   BOUND METHOD reference (`data.tell`, no call parens) as a value.
   `_cpp_expr`'s `MemberExpr` case (`gimple_codegen.py:23972-23982`)
   has no bound-method-value case at all — a non-self `MemberExpr`
   read falls through to the generic `f"{obj}.{member}"` fallback,
   which is invalid/wrong C++ here (`data` is a raw `int64_t`/`char *`
   in this scalar model, not a real object with a `.tell` member —
   `g++`: "member reference base type ... is not a structure or
   union"). Both `if`/`else` branches of the SAME statement are
   compiled unconditionally (this is straight-line C++, not templated
   per-branch), so fixing only the `lambda` side leaves this side
   broken.
2. `_genops` yields BOTH a 3-tuple (`yield opcode, arg, pos`) and a
   4-tuple (`yield opcode, arg, pos, getpos()`, gated by the
   `yield_end_pos` parameter) at two different call sites in the same
   function body. Confirmed directly against
   `_generator_tuple_yield_slot_ctypes` (`gimple_codegen.py:2689-2755`):
   its own docstring and `elif len(slots) != len(site): return True,
   None` make disagreeing ARITY across tuple-yield sites an
   unconditional refusal — "this generator's single promise type can
   only ever carry one fixed shape." This is a third, fully
   independent blocker from the other two.

Net: fixing the `LambdaExpr` gap alone provably would not unblock this
file — `_genops` has three independent, stacked structural gaps (an
opaque-callable-value type category for `_cpp_expr`, a bound-method-
value representation, and varying-arity tuple yields), each on its own
already the class of change this project's process reserves for a
dedicated, carefully-verified pass rather than a drive-by fix bundled
with two others at once. Not implemented — genuinely feature-sized,
confirmed (not assumed) via direct code tracing this session, matching
the existing `bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`
classification. Doc kept open.

## Status (updated 2026-08-09, re-verified — unchanged)

Re-verified against current master (`c79a013`) via a real
`python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/pickletools.py`.
Identical refusal reproduces exactly:

```
[gimple_codegen] generator '_genops' not eligible for C++ coroutine
  path, falling back to honest refusal: unsupported expression in
  generator body: LambdaExpr
Error building: cannot compile module: function(s) _genops (generator
  function(s), contain a `yield`/`yield from`) — ...
```

Still exactly `_genops`'s `getpos = lambda: None` (pickletools.py:34
in this checkout — the `if hasattr(data, "tell"): ... else: getpos =
lambda: None` fallback). No new information; the 2026-08-07
classification below (`bugs/hard/CODEGEN_generator_lambda_expr_
unsupported.md`, feature-sized, needs a lifted-closure-style value
category for `LambdaExpr` in the coroutine body model) still stands.
Not re-attempted here.

## Status (updated 2026-09-25) — CLUSTER A TARGET, in progress this session

This doc is now the **primary restart point** for the cluster A workstream
(see the work summary at the bottom). Read this section first.

### What is actually blocking `pickletools.py` today

Two independent blockers, in the order they surface:

**(1) `_genops` tuple-yield arity — being fixed this session.**
`_genops` yields two different tuple arities:
- `yield opcode, arg, pos`            (3-arity, the common path)
- `yield opcode, arg, pos, getpos()`  (4-arity, `yield_end_pos=True`)

The A3 (`MOJO_CORO=stackswitch`) generator gate in `mojo/middle/coro.py`'s
`_eligible`/`_generator_tuple_slots` refused this as
`'tuple yield with inconsistent shape (v0)'` and fell back to the dying
C++ coroutine emitter — so this was **NOT actually the lambda blocker**
the 2026-08-07 classification assumed; the lambda was never reached.

Fix in flight (`mojo/middle/coro.py`): refactor the slot-shape probe into
`_generator_tuple_shapes(fn, env)` (returns the list of per-site arities
+ kinds) and `_generator_tuple_unify(shapes)` (pads every site to the
longest arity with a per-slot default from `_tuple_slot_default(k)`;
returns `None` only when a shared slot has genuinely differing KINDS).
`_generator_tuple_slots`/`_generator_nested_slots` now sit on top of
these. A module-level `_PENDING_TUPLE_KINDS` (set in `_lower_one` right
after `env = _static_env(fn, struct_def)` and the `kind` computation) is
consulted by `_rewrite_expr`'s tuple path so a SHORT yield site is padded
to the unified arity at rewrite time. **Edits applied, NOT yet rebuilt/
verified** — first action on restart:

```
python3 fire.py build fire.py -o mojoc    # MUST rebuild mojoc first;
                                          # `make bside` does NOT notice .py changes
python3 -c "import gimple_codegen as gc; \
  p='/Users/mrs/net/Python-3.14.6/Lib/pickletools.py'; \
  gc.compile_to_gimple(open(p).read(), filename=p)"
```

After the arity fix, `_genops` is accepted by `_eligible` and lowered by
ORDINARY codegen (which has full callable-local dispatch via
`mojo_maybe_bound_call_N`). **Confirmed 2026-09-25**: the `getpos`
opaque-callable pattern (`getpos = glen` / `getpos = lambda: None`, then
`getpos(...)`) is NOT itself a blocker on the A3 path — a synthetic
`/tmp/bugrepro/opaque_gen.py` builds and runs cleanly (rc=0) once the
generator is eligible. So the 2026-08-07 "feature-sized, needs a new
callable-typed-local value category" assessment applies only to the OLD
C++ coroutine path, which A3 bypasses. `bugs/hard/CODEGEN_generator_
lambda_expr_unsupported.md` is therefore likely SUPERSEDED for this
instance — verify and downgrade once pickletools compiles.

**(2) `optimize` bytes-slice typing — NEWLY SURFACED, separate bug.**
With (1) fixed, `compile_to_gimple(pickletools.py)` advances past
`_genops` and now fails in `optimize`:

```
cannot coerce MojoList * to MojoBytes * (incompatible container kinds)
  at pickletools.py: value='_t108' dest='protoheader'
```

Source (`pickletools.py` ~2336/2356):

```python
protoheader = b''                      # infers protoheader: MojoBytes *
...
protoheader = p[pos:end_pos]           # _t108 is MojoList *  -> R2 refusal
```

`p` is `optimize`'s **unannotated** parameter. `_infer_param_types`
(and/or the `p[...]` usage scan) types it `MojoList *`, so `_lower_slice`
(emit_calls.py:4798) takes the `MojoList *` branch and returns
`mojo_list_slice`; the destination `protoheader` is `MojoBytes *` from the
`b''` init, and R2's kind mismatch refuses the coercion.

**Minimal repro (verified, fails identically):** `/tmp/bugrepro/bslice.py`:

```python
def f(p):
    protoheader = b""
    if len(p) > 0:
        protoheader = p[0:2]
    out = io.BytesIO()
    out.write(protoheader)

def main():
    f(b"abcdef")

main()
```

This is the **"unannotated param inferred `bytes` from body usage"**
item, which is still unimplemented for the slice case. Note
`_lower_slice` ALREADY handles a genuinely-`MojoBytes *` receiver
correctly (emit_calls.py:4777) — the whole problem is that `p` is never
inferred to BE bytes. There is currently **no runtime bytes-vs-list
discrimination** available (no `mojo_boxed_is_bytes` / bytes registry —
`runtime/fire_runtime.c` has only `mojo_bytes_*` ops), so a runtime-
dispatch fix (as used for registered containers) is NOT available here.

**Likely fix shape (pick one, verify against the full gate):**
- (a) Extend `_infer_param_types`/`infra_infer.py` to infer `bytes` for
  an unannotated param whose body slices/indexes it AND which is assigned
  to / compared with a `bytes`-typed value (matches Stage 2's plan), or
- (b) In `_infer_local_var_types` (resolve_shared.py:728), when a slice's
  destination target is already inferred `MojoBytes *`, type the slice
  value accordingly (destination-driven), or
- (c) Make `_lower_slice` treat an `int64_t`/unknown receiver as bytes
  when the *destination* is `MojoBytes *` (needs a destination hint
  threaded into `_lower_slice`, which it does not currently receive).

Option (b) is the most local and lowest-risk; (a) is the most general and
matches the documented Stage 2 plan. Either way, re-run the full quality
gate (see CLAUDE.md) — bytes typing is heavily bug-tuned.

### Verification bar for this doc
Do NOT mark this fixed until:
1. `python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/pickletools.py`
   links AND the resulting binary runs on a real pickle stream
   (byte-compare against `python3` reference if practical).
2. `test_gimple.py`, `test_gimple_generator_runner.py`, `make
   check-selfhost`, `compile_stdlib.py` (no new `U`), stdlib dylib (no
   new `skip`), and the A/B sweep (`make ab-clean && make -j24 aside
   bside && python3 tools/ab_compare.py`) show no regression vs the
   `clean=157` baseline on merged tree `326ac5e`.
3. `bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md` updated (this
   instance resolved or explicitly re-scoped to the legacy cpp path only).

## Status (updated 2026-08-07, classified — doc reference now exists) — SUPERSEDED

**Classification: `bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`**
— this file's `_genops`/`getpos = lambda: None` is that doc's own
first confirmed occurrence (written 2026-08-07). See the 2026-09-25
section above: this classification is now believed SUPERSEDED for the A3
path (the lambda is not the real blocker there; the tuple-arity gate is).
Retained for the legacy C++ coroutine path.

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, confirmed reproducing identically against current
master (`2b0c4c5`) — the 2026-07-30 note's diagnosis was correct; this
elaborates it.

```
$ MOJO_DEBUG=1 python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/pickletools.py
[gimple_codegen] generator '_genops' not eligible for C++ coroutine path, falling back to honest refusal: unsupported expression in generator body: LambdaExpr
Error building: cannot compile module: function(s) _genops (generator function(s), contain a `yield`/`yield from`) — ... falling back to interpreting this module from source instead
```

**Root cause:** `_genops`:
```python
def _genops(data, yield_end_pos=False):
    ...
    if hasattr(data, "tell"):
        getpos = data.tell
    else:
        getpos = lambda: None          # <-- the refused expression
    while True:
        pos = getpos()
        ...
        yield opcode, arg, pos
```
`getpos = lambda: None` assigns a `LambdaExpr` to a local inside the
generator's own body. The coroutine codegen's expression lowering
(`_cpp_expr`) has no case for `LambdaExpr` at all — every AST node shape
it doesn't recognize is refused via `_UnsupportedGeneratorShape` at that
statement, and (same escalation as the struct-typed-param and dynamic-
`raise` gaps found elsewhere in this cluster) refusing a MODULE-LEVEL
generator like this one hard-fails the entire file's `fire.py build`.

**New, narrow gap — not yet folded into a hard-bug doc** (only one
instance seen in this cluster so far). A `lambda` literal used as a
plain callable value (assigned to a local, later called with `()`) is a
common enough Python idiom that this is likely to recur; if a second/
third instance turns up elsewhere in this cluster, fold into a new
`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md` — the likely
minimal fix shape (worth noting for whoever picks it up) mirrors how
this codegen already handles ordinary (non-generator) closures elsewhere
via `_gen_lifted_closure`: lower the lambda to a lifted, non-capturing-
or-capturing helper function the SAME way, then have `_cpp_expr`'s
`LambdaExpr` case just reference that lifted function's pointer, rather
than inventing new lambda-specific C++ codegen inside the coroutine path.

Not fixed here — narrow-looking but touches expression-lowering inside
the coroutine `.cpp` emission path, which this task's guidance flags as
warranting its own dedicated verification pass rather than a drive-by
change during cluster classification.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/pickletools.py

## Work summary / restart context (2026-09-25, cluster A)

Full session state for whoever restarts here:

**Harness.** A/B sweep =
`make ab-clean && make -j24 aside bside && python3 tools/ab_compare.py`
(`aside` = `python3 fire.py --dump`, `bside` = `./mojoc --dump`). Baseline
on merged tree `326ac5e`: `clean=157, CI-DIFF=605, SELFHOST-CRASHED=0,
AST/TOK-DIFF=0, SHIM-FAILED=2, BOTH-FAILED=1`. **`make bside` does NOT
rebuild `mojoc` when only `.py` sources change — always run
`python3 fire.py build fire.py -o mojoc` first, or comparisons are
invalid.**

**Cluster A targets (this workstream, user chose option 2):**
- `glob.py` → `select_recursive`, `select_recursive_step`,
  `select_wildcard` — nested generators defined INSIDE `_GlobberBase`
  methods. Needs a `_hoist_nested_async`-equivalent for nested
  generators; `_eligible` (coro.py:558) only handles top-level defs +
  direct struct methods.
- `pickletools.py` → **this doc**: `_genops` arity (fix in flight) +
  `optimize` bytes-slice (newly surfaced, see top section).
- `os.py` → `_fwalk`, `walk` — needs `scandir()` iteration + mixed
  tuple/non-tuple yield.

**Cluster B (generator tuple slots) — LANDED/committed** as `7fec968`
("cluster B: tagged nested-tuple generator slots + self-host-safe
tuple-target parser fix"). Producer `coro.py`
(`_box_tag`/`_tagged_nested_box`/`_generator_nested_slots`); ABI externs
in `gimple_codegen.py` (~4450, now unconditional), `module_gen.py`
(~5962); runtime `runtime/fire_coro_gen.c`
(`__mojo_tuple_box_tag_*`, `mojo_tagged_word_dyn`, `mojo_tagged_tag_dyn`,
`MOJO_TAG_*`); consumer `emit_loops.py:_emit_generator_tuple_unpack`
(~2063 nested path), `emit_stmts.py` tuple-target (~605 tagged-dynamic),
`emit_infra.py:_tagged_dyn_read` + `_gen_print` tag-dispatch (~2660),
`emit_exprs.py:_lower_IdentExpr` (~309). Parser fix in `fire_compiler.py`
(`nm, = args` 1-elem tuple target; parallel `group_elems`/
`group_had_comma` lists after the tuple-of-tuples form regressed 58 A/B
files). Verified on real `Lib/modulefinder.py` (compiles + links). Spec
doc: `bugs/CODEGEN_generator_function_Lib_modulefinder.md`.

**Self-host safety rules (compiler compiles itself — obey these):**
64-bit int literals become `-1` natively; `isinstance(<boxed>, str/int)`
unreliable; **2-tuple unpack over `list` elements boxes slots to
int64_t** (caused a 58-file regression); genexpr/comprehension targets
trap; `not <empty MojoList*>` is FALSE natively (use `len(x or []) == 0`);
`re.fullmatch` unreliable; avoid `next(iter(...))`.

**Quality gate status** (last full run, all green): `test_gimple.py`
310/0; `check-selfhost` 1/0; `test_module_cache.py` 81/0;
`check-linkmode` 3/0; `check-runtimediff` 24/0; `check-no-new-casts` 28
(baseline); stdlib dylib 0 skips; `compile_stdlib.py` 664/0; A/B
clean=157. `test_gimple_generator_runner.py` 91 passed / 10 failed (all
pre-existing `mojo`-path failures) after fixing stale `mojo_coro*` →
`fire_coro*` runtime paths in the test. Default coro backend is
`MOJO_CORO=stackswitch` (A3); `MOJO_CORO=cpp` is the escape hatch.

**Known-red / skipped (pre-existing, NOT caused by this work):**
- `make check-native-dumpfull`: `./mojoc fire.py --dump-full` SIGSEGVs
  (exit 139, no `fire.ci`, `discover_closures`/`_moids` corruption) —
  documented in `bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md`;
  not bisected.
- `make bootstrap` Stage 2 fails (`_default_expr_to_pair: unavailable in
  compiled mode`) — another agent is working it; **user directed us to
  skip `make bootstrap`.**

**Immediate next move on restart:**
1. Implement imported module-global accessors for plain `import module`
   aliases, including public top-level `AssignStmt` globals in
   `reflect.collect_exports`; verify `pickle.bytes_types` resolves without
   dynamic getattr on a null module marker.
2. Add a real type-tuple representation/runtime check for
   `isinstance(value, bytes_types)` rather than special-casing this global.
3. Add a file-like runtime object for `io.BytesIO` and bounded
   `FILE *` `read(n)` / `tell()`, then revisit the `opcode.arg.reader(data)`
   dynamic-call path and run the real CPython disassembly byte comparison.
4. Only after the behavioral verification bar passes should this doc close.
