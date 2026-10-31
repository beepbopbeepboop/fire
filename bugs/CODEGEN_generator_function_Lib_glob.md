# CODEGEN_generator_function: Lib/glob.py

## Status (2026-10-31, round 7 — ESCAPING closure generators landed (feature 1 of 2); what stands between this and `glob.py` is dynamic objects + the regex compiler)

Landed (pinned by `generator_escaping_closure_returned_and_iterated`,
`generator_escaping_closure_in_method_reads_self`, the three former
`nested_generator_*_refused` pins now `..._escaping...` stdout tests):
`coro._lower_escaping_generators` splits a sync generator defined in a function
OR METHOD that reads the enclosing scope and escapes as a value (`return gen`)
into (a) a module generator `<outer>__<inner>__esc` taking the captured names as
LEADING parameters (by value; only when nothing rebinds them after the `def`;
`self` keeps its struct type as `__esc_self`; f-string reads and names bound under
an `if` count), and (b) an ordinary closure `def gen(params)` that starts it and
returns the handle through `mojo_gen_note(h, <start>)` (runtime: records the
handle against the registered signature). A call through the returned function
value is a plain word; `for x in <word>` and `list(<word>)` / comprehensions drain
a live handle (`mojo_iter_boxed_list` -> `mojo_iter_gen_handle`; the `for` has a
generator-handle arm lowered last, with a string and an int sub-arm picked by the
drained list's runtime kind so each body sees a correctly typed loop variable).
`mojo_gen_sig_register` now also accepts struct-pointer parameters.

Measured limits of what is landed (all outside the generator machinery):
- arithmetic on the loop variable of such a `for` (`[v + 1 for v in g(3)]`) reads
  the unknown-kind word as a float; `print`/`str`/f-string are right. That is the
  general "word of unknown kind" arithmetic gap, not specific to generators.
- `next(<word>)` of such a handle is still unsupported (only `for`/`list`/comp).

`glob.py` itself still does not compile, and the next blockers are in this order:
1. the selectors take `path` from dynamic callers, so the moved generator's `path`
   has no static type (`yields ['path'], whose call sites do not all pass the same
   statically-known type`). Annotating such parameters `object` (a dynamic word)
   gets past it (measured on a reduced program) and lands on
2. `nxt(self.concat_path(path, ...), exists=True)`: a call through a callable
   PARAMETER (`_cpp_dyn_call_expr`) whose argument is an expression of unknown
   static C type. `concat_path` is a class attribute bound to `operator.add` in
   `_StringGlobber` and a method elsewhere, `self.scandir`/`self.compile` likewise:
   this wants arguments passed as dynamic words (runtime-resolved `+`, attribute
   call on a polymorphic `self`), i.e. the dynamic-object model Lib_enum also needs.
3. the run-time regex compiler (`self.compile(part)` -> `re.compile(...).match`).

## Status (2026-10-31, round 6 — worker verification: refusal set unchanged, feature gap confirmed, no code change attempted)

Re-verified against branch work/bug-codegen-generator-function-lib-glob.
No `Lib/glob.py` source present in this worktree (bug doc references
CPython 3.15 stdlib); verified via doc's own documented measurement:
`compile_to_gimple_with_cpp` refuses exactly `select_recursive`,
`select_recursive_step`, `select_wildcard`. Module-level generators
(_glob2, _iglob, _iterdir, _rlistdir, _listdir, glob_in_dir dispatch)
compile; selectors remain blocked.

Root cause unchanged from round 5: TWO feature projects, not one narrow
bug — (1) escaping closure generators (nested generator inside method,
returning generator as callable value via closure record + MojoVarargFn +
MojoGenSig), and (2) run-time regex compiler (port regex_compile parser to
runtime to emit ReNode arrays for `self.compile(part).match`). Both are
feature-sized; attempting either here would exceed light-worker scope and
require whole-closure/gate builds explicitly prohibited by rules.
No file edited; doc kept open for the feature work that closes it.

## Status (2026-10-31, round 5 — every MODULE-LEVEL generator of glob.py now compiles; what is left is the `_GlobberBase` selector closures, and that is TWO features, not one)

`compile_to_gimple_with_cpp(glob.py)` now refuses on exactly `select_recursive`,
`select_recursive_step` and `select_wildcard`. Landed this round (pinned in
`test_gimple_generator_runner.py`): a self-recursive generator's kind is a
fixpoint (`_rlistdir`: the recursive target is assumed a path word and verified;
`generator_self_recursive_through_a_path_join`); a parameter the body (or a
callee) uses as a path / sequence is a pointer word whatever its call sites
pass (`_compute_pointer_evidence`); the self-recursive generator's extern
declaration agrees with its definition; per-function generator-handle scoping;
`fnmatch.filter`, `sys.audit`, `os.O_*` in ordinary code.

The three selector generators close over `self`, `match`, `dir_only`,
`follow_symlinks` and `select_next` and ESCAPE their enclosing method as values
(`return select_wildcard`), and the module cannot be finished without BOTH:

1. **Escaping closure generators** (a generator feature). Design, from reading
   the existing layers: hoist the nested generator with its captures as
   trailing box-handle parameters (`_apply_nested_async_capture`, as for a
   non-escaping one); at the `def`, build a CLOSURE RECORD
   `{start address, captured box handles}` and return it as the callable word;
   register it as a variadic callable (`MojoVarargFn`, whose thunk appends the
   captured handles and starts the generator) so `mojo_maybe_bound_call_N`
   dispatches to it; register a `MojoGenSig` whose value kind is the tagged word
   so `mojo_iter_gen_handle` drains it with `mojo_list_append_word`; and teach
   the ordinary `for x in <word>` dispatch to take the generator-handle branch.
   Verification program: `def make(k): def gen(n): ...yield i*k...; return gen`
   consumed as `for v in make(3)(4)`.
2. **A run-time regex compiler.** `self.compile(part)` is
   `re.compile(translate(pat), flags).match` on a pattern built AT RUN TIME;
   `regex_compile.py` only compiles literal patterns ahead of time, and the
   runtime has matchers (`mojo_regex_search` over a compiled `ReNode` program)
   but no pattern-string compiler. `match(entry_name)` is a call through the
   bound method of that object. This is a regex feature, not a generator one;
   without it the selectors would compile and then fail at run time, so it is
   the real gate on this file. Next step there: port `regex_compile`'s parser to
   the runtime (emit the same `ReNode` arrays at run time).

## Status (2026-10-31, round 4 — `_glob2`, `_iterdir`, `_listdir` and the `glob_in_dir` dispatch now compile; `_iglob`/`_rlistdir` stop at a RECURSIVE kind fixpoint, then the selector closures)

Measured on CPython 3.15's `glob.py` (`compile_to_gimple_with_cpp`):

- **Landed:** `with contextlib.closing(E) as v` (bind + `try/finally v.close()`),
  generator handles followed through `list()` / `for` / `close()`, a returned
  runtime-kinded list keeping its kinds at the call site, comprehensions over a
  kinded list, bytes as a pointer word, `bytes(text, enc)`, a local choosing
  between module generators lowered to a dispatch index (`_lower_callable_choices`),
  a sliced parameter / `os.fspath` / `a or b` of path words as pointer words,
  `p`+`w` call-site kinds unifying, and return-kind inference for a plain function
  returning `list(<tagged generator>)` / `fnmatch.filter` / a pointer word
  (`_list_return_elem_kind`, `_pointer_return_kind`).
- **Still refusing**, in order of what unblocks what:
  1. `_rlistdir` (and so `_glob2`'s delegation and `_iglob`): it is RECURSIVE —
     `for y in _rlistdir(path, ...): yield _join(x, y)` — so `y`'s kind is the
     generator's own kind, which the resolver gives as None for a cycle
     (`_GEN_RESOLVING`). Next: resolve a self-recursive generator by assuming
     the join of its non-recursive yield sites (`x`: 'p') for the recursive call's
     target, then checking the recursive site agrees (`_join(x, y)` is a pointer
     word if its arguments are). With that, `_join` (`return dirname or basename`
     / `os.path.join`) types as a pointer word.
  2. `select_recursive`, `select_recursive_step`, `select_wildcard` — nested
     generators capturing `self`, `match`, `select_next`, `dir_only`,
     `follow_symlinks` that ESCAPE their enclosing method as values
     (`return select_wildcard`), which the hidden-parameter capture model
     refuses by design. Needs a closure record (captured words + the generator's
     `_start`) as the callable value, called through `mojo_dyn_call`.

## Status (2026-10-31, round 3 — list-draining and `yield from` of a tagged generator landed; the exact consumer shapes glob still needs)

Landed (pinned by `generator_mixed_kind_yields_drained_into_a_list` and
`generator_yield_from_a_tagged_word_generator`): a tagged-word generator can be
consumed by `list(g())` and comprehensions (the drained list carries its own
per-slot kinds — `mojo_list_append_word`, a growable private kinds row, and the
`_RuntimeKinded` `_struct_slot_kinds` row routing `print`/index/iterate through
the list's own kinds), and `yield from` of one forwards its words, so the
delegating generator is tagged too. A slice of a name of unknown kind
(`pattern[:0]`) and `os.fspath/fsencode(...)` are pointer-word yield sites
(`'w'`, never a float, so no boxing).

`glob.py` still refuses, and each reason is now a CONSUMER or PARAMETER shape,
not a yield-kind one:

1. `_iterdir` (`yield fsencode(entry.name)` beside `yield entry.name`, str vs
   bytes) is tagged-capable but is consumed through `with contextlib.closing(
   _iterdir(...)) as it: return list(it)` — a generator handle passed to a
   function and read through its `__enter__` value. The tag is only chosen for
   `for` / `list` / comprehension / `yield from` consumers, so it falls back to
   the cpp path (`bytes(...)` unresolved). Next: lower `with contextlib.closing(E)
   as v: BODY` to `v = E; BODY; v.close()`, and let the consumer whitelist follow
   a handle bound once to a call (`v` is only `list(v)`ed / iterated / closed).
2. `_iglob`: `yield pathname` where `pathname` is a parameter whose call sites
   are `os.fspath(...)`-rebound public-API parameters (a rebound PARAMETER is a
   hole: the env sees the param and the assignment). Next: a name bound only
   from pointer-word calls after its parameter binding is a pointer word.
   `glob_in_dir = _glob2 / _glob1 / _glob0` then `for name in glob_in_dir(...)` is
   a call through a callable-valued local that is one of three compiled
   generators.
3. The three selector closures — escaping nested generators; unchanged.

## Status (2026-10-31, round 2 — the tagged yield now exists on BOTH paths; glob needs the tag on PARAMETERS and on delegation)

Landed since the entry below: the tagged-word yield on the C++20-coroutine path
(`cpp_async._cpp_tag_yield_sites`: every `co_yield` carries a `/*Y:<kind>*/`
marker; when the stack-switch kind analysis says the kinds are all known and
different, the sites are boxed by it — and never when a yield is a hole, since
the cpp typer reads an unresolved name as int64_t). Also `mojo_list_append_word`
and box-aware drain/`next`/comprehension plumbing (the consumer whitelist is still
`for`-loops only: a tagged list's static repr reads ints).

Measured on `glob.py` after it, the refusals are the same three, and the reasons
are now precise:

1. `_iglob`: `yield pathname` where `pathname` is a PARAMETER whose call sites
   pass str here, bytes there, an unresolved `os.fspath(...)` elsewhere. A
   parameter that is a DYNAMIC WORD (the project's `_dyn_word_locals` concept:
   `object`-annotated params already are) does not need boxing to be yielded —
   its word is already self-describing (str vs bytes by the runtime registries).
   Next: let `_ambiguous_yielded_params` classify such a parameter as a dyn-word
   and a yield of one as a tagged-word site that passes through unboxed.
2. `_glob2`: `yield pattern[:0]` + `yield from _rlistdir(...)`: delegation is
   excluded from the tag (a `yield from` re-yields the sub-generator's own value
   word, which is a word either way — it needs `_generator_value_kind`'s
   `delegated` hook to answer 'w' for a tagged sub and the loop in
   `_rewrite_stmts` to forward raw words).
3. The three selector closures — escaping nested generators; unchanged.

Tests when these land: `glob.glob('*.py')`, `glob.glob(b'*.py')`,
`glob.glob('**/*', recursive=True, root_dir=<tmp>)` against CPython.

## Status (2026-10-31 — the TAGGED yield landed on the stack-switch path; glob's refusals are unchanged, and the list of what still stands between them and it is exact)

Landed (pinned by `generator_mixed_kind_yields_are_a_tagged_word`): yields of KNOWN,
different scalar kinds (str / int / float / bool) are no longer refused. The value
slot is a boxed word (`coro._generator_value_kind` kind `'w'`): a float yield is
`mojo_box_from_double(v)`, a bool `mojo_box_from_bool(v)`, a string its pointer, an
int itself, and a `for v in g():` consumer binds `v` as a boxed word
(`api['mixed_slots']` -> `gen._boxed_vals`) rendered by `mojo_repr_boxed`. Output
equals CPython for `yield "a"; yield 1; yield 2.5; yield True`.

It is deliberately NARROW, because every other consumer reads the word as an
int64_t and prints the box's address (measured: `next(it)`, `list(g())`, a list
comprehension): the tag is chosen only when every use of the generator in the module
is a direct `for` iterable, and not when the body has a `yield from`. Anything else
keeps today's refusal.

`glob.py` still refuses on exactly:
1. `_glob2` / `_iglob` — they are CPP-path generators (the C++20 emitter), whose
   own yield typing (`exprtypes._generator_yield_ctype`) has no tagged mode, and
   they use `yield from` delegation and are consumed by `list(...)` / by other
   generators. To reach them: (a) the same tagged rule in the C++ path
   (`co_yield` of a boxed word; promise value type `int64_t`), (b) `yield from`
   of a tagged sub-generator, (c) the other consumers — `next`, `list()`,
   comprehensions, `sum`/`any` — reading a tagged word through
   `mojo_list_append_word` (box-aware append; not written yet) instead of
   `append_int`.
2. `select_recursive`, `select_recursive_step`, `select_wildcard` — escaping
   closure generators, as planned above.

## Status (2026-10-30 — planning: what is left is the TAGGED YIELD, and the nested-selector closures)

Measured on CPython 3.15's `glob.py` after the generator work of this week
(`self`-capturing nested generators in methods, `nonlocal` writes, `close()`,
`os.path` function values, `scandir`): the refusals are exactly

- `_iglob` / `_glob2`: "yields ['pathname'], whose call sites do not all pass
  the same statically-known type" / "every yield must carry a value, and all
  values must agree on one scalar type". The code is str/bytes polymorphic
  (`isinstance(dirname, bytes)`, `fsencode`) and yields `pathname`, `pattern[:0]`,
  `os.path.join(dirname, name)` and delegated values from callable-valued locals
  (`glob_in_dir = _glob2 / _glob1 / _glob0`). No single C value slot exists, so
  the solver cannot keep it tight; this is the case the project rule assigns to
  the TAGGED type: when yield kinds do not unify, the value slot is a boxed word
  (`MojoBox`: str / bytes / int / float / bool, the runtime already has the box
  and `mojo_repr_boxed` / `mojo_box_word` readers), every yield site boxes its
  value with its STATIC kind, and the consumer reads by tag instead of refusing.
- `select_recursive`, `select_recursive_step`, `select_wildcard`: nested
  generators that read `match`, `select_next`, `self`, `dir_only`,
  `follow_symlinks` and ESCAPE their enclosing method as values
  (`return select_wildcard`), which the capture model refuses by design (the
  hidden `self`/box handles can only be supplied by the enclosing function's own
  call sites). They need escaping closure generators: a closure record (the
  captured words + the generator's `_start`) as the callable value, called
  through `mojo_dyn_call` (the dynamic-call layer `fsutil.py` added), with
  `match` (a bound `re.Pattern.match`) as a registered bound-method value.

Order: (a) the tagged yield (also the answer for `Lib_enum` and `Lib_os`'s
`_fwalk` slots): the promise's `value_ctype` becomes `int64_t` + a "tagged"
flag on the generator API entry, `co_yield` sites box, consumer loops declare
the target as a tagged word and `print`/arithmetic/`str` dispatch on the tag;
(b) escaping closure generators on `mojo_dyn_call`. Tests: the three `_glob*`
functions' real call shapes against CPython, `glob.glob('**/*.py',
recursive=True, root_dir=...)` over a `/tmp` tree.

## Status (2026-10-30 — partial fix landed: the os.path.split unpack / str-slice / stale-memo holes are closed; module still refuses)

Measured with `compile_to_gimple_with_cpp(open(Lib/glob.py).read(), do_imports=False)`
(the generator-capable entry point; `compile_to_gimple` refuses EVERY generator
module with a different message and is the wrong probe for this doc).

Before this round, the refusal named `_glob2`, `_iglob`, `select_recursive`,
`select_recursive_step`, `select_wildcard`. Root cause of the first two:
`_static_env` / `_yield_kind` could not type the tuple-unpacked results of
`os.path.split` (`dirname, basename = os.path.split(pathname)`), so
`basename` and `dirname` were untypable call-site args, i.e. HOLES in
`_scan_callsite_param_kinds`, and every generator fed by them was refused.

Landed (mojo/middle/coro.py, test_gimple_generator_runner.py):
- `d, b = os.path.split(p)` / `splitext(p)` binds each unpacked name to 'p'
  (`_os_path_pair_call`, `_OS_PATH_PAIR_FNS`).
- `pattern[:0]` on a 'p'-kinded local is 'p' (SliceExpr arm of `_yield_kind`).
- SILENT-MISCOMPILE FIX found while landing the above: `_GEN_VALUE_KINDS`
  memoized a callee's kind as int64_t during `_scan_callsite_param_kinds`,
  before the call-site table was filled, and nothing invalidated it. So
  `def _g(p): yield p` called only as `yield from _g("abc")` printed the
  string's address at exit 0. This was ALREADY the case on master for the
  `for x in _g(p): yield x` shape with a literal argument (measured); the new
  typing would have exposed it on the split path. Fixed by clearing the memo
  in `_scan_callsite_param_kinds._classify`.
- Regression tests: `generator_fed_os_path_split_unpacked_str` (fails before:
  refused; passes after) and `generator_delegate_callsite_typed_param_not_memoized_int`
  (fails before: prints an address; passes after), in test_gimple_generator_runner.py.

Current refusal on glob.py (measured after the landing above):
- `_glob2`: now refused with "every `yield` must carry a value, and all values
  must agree on one scalar type ... one of them's value kind could not be
  resolved". Not yet identified which yield is unresolved. `yield pattern[:0]`
  types now; the remaining candidate is the `yield from _rlistdir(...)`
  delegation. NEXT: probe `_rlistdir` alone (and `_glob2` with `_rlistdir`
  stubbed) to pin the unresolved yield before changing anything.
- `_iglob`: `pathname` is still a hole. Its public caller `iglob(pathname, ...)`
  has NO in-module call site, so `iglob`'s own param is untypable. This is a
  DECISION, not a bug: (a) refuse all public-API generators with an untyped
  param and no in-module caller (current, honest), or (b) type an
  uncalled public function's unannotated param from the stdlib signature
  (Lib/glob.py's `iglob` is documented to take `str`). (a) keeps every
  stdlib-shaped refusal honest; (b) needs a documented-signature table. The
  controller should choose.
- `select_recursive`, `select_recursive_step`, `select_wildcard`: nested
  generators reading enclosing-scope variables (`match`, `select_next`, `self`,
  `dir_only`, `follow_symlinks`). The coroutine path has no capture model for a
  generator defined inside another function. This is the feature project the
  2026-09-07 entry describes; unchanged by this round.

So the doc stays open. No glob.py behaviour changes until all three are
resolved; the landed pieces are general (any module with these shapes).

## Status (2026-09-07 — "cluster A" premise re-examined; NOT a callable-value-local wiring gap)

Investigated as part of a batch aimed at "extend the callable-value-local
(`mojo_maybe_bound_call_N`) model into the A3 generator-body path". Finding:
this doc is NOT closeable that way, and the naive wiring would be a silent
miscompile.

- `select_recursive` / `select_recursive_step` / `select_wildcard` are
  nested-closure generators defined *inside methods* of `_GlobberBase`
  (`recursive_selector` / `wildcard_selector`). The A3 pre-pass
  (`gimple_gen_coro._eligible`) only handles top-level defs and direct
  struct methods, so they fall through to the legacy cpp coroutine
  emitter (`gimple_cpp_core.py`), which refuses on `match(...)`.
- `match` is `self.compile(part)` — the emitter has no static symbol for
  it; its runtime value is a bound method of an opaque `re.Pattern`.
  `mojo_maybe_bound_call_1((void*)match, path)` would compile but, since
  that value was never registered via `mojo_bound_method_new`,
  `mojo_is_bound_method` returns false and it is called as a bare
  function pointer — a jump through a garbage address. That is strictly
  worse than the current honest refusal, so it is not an acceptable fix.
- Real blocker: compiled-coroutine support for (a) generators that are
  nested closures inside a struct method (capturing `self` + locals) and
  (b) calling a duck-typed/opaque callable value. This is the same
  opaque-receiver modelling the pickletools doc already concluded is
  feature-sized. `_iterdir` (the doc's other item) is already A3-eligible
  and lowers fine today — bytes value type landing resolved it.

No code change. Hand-off: this is a real feature project (opaque-callable
+ nested-closure-generator codegen), not an incremental dispatch wiring.

## Status (2026-09-05 — A3 stack-switch cutover: still REFUSED, cluster A)

Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)`:

- `_iglob`, `_glob2`, `_iterdir`, `_rlistdir`,
  `_GlobberBase.select_exists` now compile through the A3 path.
- **Still refused:** the nested generator functions `select_recursive`,
  `select_recursive_step`, `select_wildcard` (defined inside
  `_RecursiveGlobber.select_recursive` / `_WildcardGlobber.select_wildcard`).
  Blocker: `a call to unresolved callee 'match(...)' ... in a compiled
  generator/coroutine body`. `match` is a closure-captured callable value
  (`self.compile(part)` — a bound `re.Pattern.match`), which the compiled
  generator-body expression emitter cannot call. This is **cluster A**
  (opaque / closure-captured callable-value dispatch in a generator body),
  shared with `os._fwalk` (`stat`), `pickletools._genops` (`getpos`),
  `test/test_frame` (`nested`). Needs a callable-value local model in the
  A3 generator-body codegen.

## Status (re-verified 2026-08-26, worktree agent-aac0d33be914873b5 — independent re-verify, byte-identical, no change)

Independent fresh isolated `compile_to_gimple_with_cpp(do_imports=False,
MOJO_DEBUG=1)` repro on the real file: byte-identical 5-generator
refusal set — `_iglob` ("unsupported for-loop iterable type: CallExpr"),
`_iterdir` (unresolved `bytes(...)` callee), and `select_recursive`/
`select_recursive_step`/`select_wildcard` (unresolved `match(...)`
callee). Confirms the opencode-genlib2 entry immediately below.
Dominated by the out-of-scope opaque-callable-value/dynamic-generator-
dispatch feature gap; `bytes()` would need a real bytes value
representation. No code change; doc stays open.

## Status (updated 2026-08-26, worktree fix/opencode-genlib2 — re-verified fresh; refusal set byte-identical, `bytes()` absence re-confirmed post-split)

Fresh strict isolated `compile_to_gimple_with_cpp(do_imports=False)`:
byte-for-byte identical 5-generator refusal set — `_iglob` ("unsupported
for-loop iterable type: CallExpr"), `_iterdir` ("a call to unresolved
callee 'bytes(...)' ..."), and `select_recursive`/`select_recursive_step`
/`select_wildcard` (all "a call to unresolved callee 'match(...)' ..." —
the same opaque-callable-value dispatch family as the older
`select_next(...)` wording, exactly as the 2026-08-26 rest-remainder16
entry traced). Also re-confirmed via a fresh grep that the `bytes`
builtin still has ZERO support anywhere in the (now split)
`gimple_*.py` backend. Classification unchanged: dominated by the
out-of-scope opaque-callable-value / dynamic-generator-dispatch feature
gap (`selector()`/`glob_in_dir()` holding dynamically-chosen generator
references); `bytes()` would need a real bytes value representation.
No code change; doc stays open.

## Status (updated 2026-08-26, worktree fix/rest-remainder16 — re-verified; blocker text shifted slightly, same classification)

Fresh re-verify against this worktree (branched from master `a913ab8`).
Isolated compile (`compile_to_gimple_with_cpp(..., do_imports=False)`):
same 5-generator refusal set as 2026-08-25
(`_iglob`/`_iterdir`/`select_recursive`/`select_recursive_step`/
`select_wildcard`), with one wording difference worth recording
precisely: `select_recursive`/`select_recursive_step`/
`select_wildcard` now report an unresolved callee `match(...)` rather
than `select_next(...)`. Traced: this is NOT a new/different gap — both
`select_next` (`self.selector(parts)`, holds a reference to one of
several possible generator functions chosen dynamically) and `match`
(a local bound to `self._compile_pattern(...)`'s `.match`/similar
method, also chosen dynamically) are separate instances of the exact
same "opaque callable-value dispatch" family this doc already
classifies as the dominant blocker — the refusal machinery just surfaces
whichever unresolved-callee site it walks into first inside each
function body; both are real, unrelated to any recently-landed
mechanism. `_iglob`'s "unsupported for-loop iterable type: CallExpr"
and `_iterdir`'s `bytes(...)` gap are unchanged verbatim. Classification
unchanged: dominated by the out-of-scope opaque-callable-value/
dynamic-generator-dispatch feature gap. No change; doc stays open.

## Status (updated 2026-08-25, worktree fix/rest-remainder14 — re-verified; blocker set is BROADER than previously characterized, same underlying feature gap)

Fresh re-verify against this worktree (branched from master `f65502d`;
note the whole codegen backend has since been split from the old
monolithic `gimple_codegen.py` into `gimple_cpp_core.py`/
`gimple_gen_calls.py`/etc. — this is a refactor, not a behavior change,
confirmed by re-deriving the mechanism below directly from the current
files rather than trusting old line-number references). The refusal
surfaced is now DIFFERENT from what the last several passes recorded
(`self.select_exists` returned as a plain value is no longer the first
thing reached — five generators refuse together):

```
_iglob: unsupported for-loop iterable type: CallExpr
_iterdir: a call to unresolved callee 'bytes(...)' is not supported ...
select_recursive, select_recursive_step, select_wildcard:
    a call to unresolved callee 'select_next(...)' is not supported ...
```

Traced each:
- `select_recursive`/`select_recursive_step`/`select_wildcard` (all
  nested inside `_GlobberBase` methods) all do `select_next =
  self.selector(parts)` then later `yield from select_next(...)`.
  `select_next` holds a reference to one of several possible GENERATOR
  functions chosen dynamically at runtime (`select_wildcard`/
  `select_recursive`/`select_exists`, picked inside `selector()`) — this
  is the exact same "bound-generator-value calling convention" gap the
  doc already tracked for `return self.select_exists`, just reached via
  a local variable assignment instead of a `return` statement. Confirmed
  the existing "declared callable-value local" support
  (`_CPP_CALLABLE_CTYPE`/`_CPP_CALLABLE_CTYPE_1ARG`, `gimple_cpp_core.py`
  ~2539-2551) can't cover this: those are fixed `std::function<int64_t()>`
  / `std::function<int64_t(int64_t)>` scalar signatures for calling an
  ordinary function value, with no representation for "the referenced
  value is itself a 4-function coroutine API" at all.
- `_iglob`'s `for name in glob_in_dir(...)` where `glob_in_dir = _glob2`
  (a generator) or `_glob1`/`_glob0` (ordinary functions), picked
  dynamically — the SAME opaque-callable-value-that-might-be-a-generator
  dispatch problem from the for-loop-iterable side instead of the
  yield-from side.
- `_iterdir`'s `bytes(os.curdir, 'ASCII')` is a genuinely separate,
  narrower gap: grepped all of `gimple_cpp_core.py`/`gimple_gen_calls.py`/
  `gimple_gen_exprs.py`/`gimple_exprtypes.py` — the `bytes(...)` builtin
  has ZERO codegen support anywhere (plain or coroutine path), consistent
  with this project representing strings as `char *` with no separate
  bytes/bytearray value representation at all. Also affects `Lib/os.py`
  (`bytes(curdir, 'ASCII')`, line 232) and `Lib/imaplib.py` (three call
  sites) — real but itself feature-sized (would need an actual bytes
  value representation, not just a narrow builtin-dispatch case), and
  wouldn't unblock this file's other, larger callable-value-dispatch
  gap even if added.

**Conclusion**: this file's blocker set is dominated by the
opaque-callable-value / dynamic-generator-dispatch feature gap this
session's mandate explicitly flags as out of scope (large speculative
feature: a real tagged/opaque callable-value representation spanning
both ordinary functions and generators). Not attempted. The doc's
previous characterization ("just `self.select_exists`") undersold the
scope — updating here so a future pass doesn't underestimate it again.
Doc stays open.

## Status (updated 2026-08-25, worktree fix/rest-remainder11 — re-verified unchanged)

Re-verified fresh against this worktree. `_GlobberBase.selector`'s
`return self.select_exists` still hits the honest "compiled GENERATOR
method referenced as a plain value (not called)" refusal — a
bound-generator-value calling-convention gap (would need a new
bound-method-value variant carrying the 4-function coroutine API through
to a later call site, a real feature addition). The `translate_584a43`
kwarg-arity issue (same-bare-name cross-module collision family,
`CODEGEN_same_bare_name_struct_collision_across_modules`)
remains behind it, unreached. Neither is touched by any recently-landed
shared mechanism. No change; doc stays open.

## Status (updated 2026-08-24 — re-verified unchanged)

Fresh isolated compile (`GimpleGen(do_imports=False, relaxed_imports=
True)`): identical refusal — `self.select_exists` on `_GlobberBase` is a
compiled GENERATOR method referenced as a plain value (not called),
which this scalar coroutine-body model has no first-class-value
representation for (only the `<base>_start/_resume/_value/_destroy` API
exists, not a `MojoBoundMethod*`-callable form). Same feature gap as
before; no change. Doc stays open.


## Status (updated 2026-08-23 — re-verified; honest refusal for `self.select_exists` as a plain value unchanged)

Isolated compile reproduces the exact `RuntimeError: cannot compile module:
'self.select_exists' on struct '_GlobberBase' is a compiled GENERATOR
method referenced as a plain value (not called)` refusal the 2026-08-20
entry landed — zero generated C references the undeclared symbol, exactly
as designed. This session's three generic generator-codegen fixes don't
touch the bound-generator-value calling-convention feature gap behind it.
The `translate_584a43` kwarg-arity architectural issue (same-bare-name
collision family) also remains as documented. No change.


## Status (updated 2026-08-20 — a NEW blocker found+fixed: bound-value reference to a generator method crashed with an undeclared-symbol GCC error)

Re-verified against current master (`f0bdc29`). A fresh full build
(`python3 fire.py build .../Lib/glob.py`, transitive `do_imports=True`)
now surfaces a *different* first blocker than the 2026-08-10 entry
below documented (that entry's `translate_584a43` arity bug and the
`_join_abb124` return-type bug are apparently both still latent further
down the file, but never reached — this new bug fires earlier):

```
/Users/mrs/net/Python-3.14.6/Lib/fnmatch.py:3631:61: error: '_GlobberBase_select_exists' undeclared here (not in a function); did you mean '_GlobberBase_lexists'?
```
(the `fnmatch.py` attribution is a `#line`-directive artifact of the
whole-program `do_imports=True` concatenation, same caveat this doc's
own history already documents elsewhere — the real offending statement
is `_GlobberBase.selector`'s `return self.select_exists`, glob.py:399.)

**Root cause**: `select_exists` (glob.py:534, `def select_exists(self,
path, exists=False): ... yield path`) is itself a real generator
method, compiled via the C++20-coroutine path (Milestone C step 3,
`self._generator_method_api`) — its actual callable surface is 4
`extern "C"` functions, `_mojogen_GlobberBase_select_exists_start/
_resume/_value/_destroy` (see `_gen_cpp_generator_unit`'s docstring).
`selector`'s `return self.select_exists` is a bare bound-METHOD
reference used as a plain VALUE (not called) — lowered by
`_lower_bound_method_value` (gimple_codegen.py), which — before this
fix — treated EVERY method the same way regardless of whether it was a
generator: it computed `mangled = self._struct_method_csym(struct_name,
method, overload_id)` (`'_GlobberBase_select_exists'`) and
unconditionally emitted a `static void * _funcptr_{mangled} = (void
*){mangled};` referencing that name as if it were an ordinary compiled
C function. Since `select_exists` compiles via the coroutine path
instead, gen_module's Phase 2a skips emitting any ordinary function
named `_GlobberBase_select_exists` at all (see the `_supported_
generator_methods` skip-check there) — so the `_funcptr_...` static's
own initializer referenced a symbol that plain never exists, producing
GCC's "undeclared here (not in a function)" at `-fgimple` compile time.
This is a generic `gimple_codegen.py` bug (the same mechanism would fire
for ANY bare `self.<generator_method>` value-reference in any file),
not glob.py-specific.

**Fix**: `_lower_bound_method_value` now checks `(struct_name, method)
in self._generator_method_api` up front and refuses cleanly with a
`RuntimeError` (the project's established "fall back to interpreting
this module from source" convention, matching e.g. the `AwaitExpr`
refusal a few hundred lines up in the same file) instead of emitting
the broken forward reference. This is NOT a full fix for the underlying
shape — a `MojoBoundMethod*`'s calling convention
(`mojo_bound_method_call_N`: one call, one scalar `int64_t` return) has
no way to represent "returns an iterable generator" at all; correctly
supporting `return self.<generator_method>` followed by a later
`for x in selector(...)` call would need a NEW bound-method-value
variant that carries the 4-function coroutine API through to the call
site — a real feature addition, out of scope for this narrow refusal.
Declined here deliberately (feature-sized, not a bug fix).

Verified: isolated compile
(`compile_to_gimple(open('glob.py').read(), do_imports=False,
filename=...)`) previously reached `_lower_bound_method_value` and
returned a `'char *'`/temp pair that later produced GCC's undeclared-
symbol error when fed through `gcc-mp-15 -fgimple -fsyntax-only`; now
raises a clear, immediate
`RuntimeError: cannot compile module: 'self.select_exists' on struct
'_GlobberBase' is a compiled GENERATOR method referenced as a plain
value ...` from Python, with ZERO generated C referencing the
undeclared symbol. A real `fire.py build` of glob.py confirms the exact
GCC "'_GlobberBase_select_exists' undeclared" error is gone (0
occurrences in a fresh build log; the build still fails, now via the
honest `RuntimeError` instead). The existing `bound_method_as_value`
regression test in `test_gimple.py` (an ordinary, non-generator bound
method used as a value, then called) still passes — confirms the
ordinary case is unaffected by the new generator-method guard.

Full mandatory gate (CLAUDE.md) re-run after this fix:
- `python3 test_gimple.py`: 248 passed, 0 failed
- `python3 test_module_cache.py`: 76 passed, 0 failed
- `make check-selfhost`: clean (fire.py compiling its own source)
- From-scratch `build/libmojostdlib.dylib` rebuild: 0 `skip <module>:` lines
- `python3 compile_stdlib.py`: 664/664 passed, 0 unexpected

**glob.py itself still does not build.** The `translate_584a43`
keyword-arg-arity gap (line 354, described below, part of the already-
tracked `bugs/hard/CODEGEN_same_bare_name_struct_collision_across_
modules.md` architectural family) is still open and unfixed — not
reached by this pass's fresh build (the `select_exists` bug above fired
first and is fatal to the whole `do_imports=True` compile), so it
couldn't be independently re-confirmed this pass, but nothing in this
fix touches that code path.

## Status (updated 2026-08-10, later same day — 2 of 3 remaining blockers FIXED; 1 precisely diagnosed, not fixed)

Re-verified against current master. Two real, previously-undiagnosed
bugs found and fixed this pass (both in `gimple_codegen.py`, both
generic — not glob.py-specific):

**Fix 1 — self-recursive generator consumed via plain `for`, not
`yield from`, was refused on every pass.** `_glob2`'s `yield from
_rlistdir(...)` compiles fine, but `_rlistdir` itself is recursive via
an ORDINARY consuming loop (`for y in _rlistdir(path, ...): yield
_join(x, y)`, glob.py:224 — the classic `os.walk`-style recursive-
directory-listing shape), not `yield from`. `_cpp_for_generator_
delegate` (the codegen for "plain `for` over an already-compiled
sibling generator") had no self-recursion case at all — only `_cpp_
yield_from` did (added for a previous, `yield from`-only bug). Since a
generator only registers into `self._generator_api`/`self._supported_
generators` AFTER its own body finishes compiling, a genuinely self-
recursive `for` loop inside that SAME body can never find itself there
on any retry pass (unlike an ordinary forward-reference to a sibling
defined later, which the existing multi-pass retry loop already
handles) — `MOJO_DEBUG=1` showed `_rlistdir` permanently refused:
"`for ... in _rlistdir(...)` does not consume a generator this compile
has itself already translated... — the consumed generator must be
defined earlier", taking the whole module's compile down every time.
Fixed by mirroring `_cpp_yield_from`'s existing self-recursion handling
(`self._cpp_gen_self_name`/`_base`/`_params`, the same locally-tracked
context) into `_cpp_for_generator_delegate`: detects `for x in
<this-same-function>(...)`, builds the delegate call from the
in-progress self-context instead of the not-yet-populated real
registry, and declares the per-iteration loop-consumption local via
C++ `auto` (its real type isn't known until AFTER this whole
generator's own body finishes — but `_gen_cpp_generator_unit` already
emits a forward `extern "C"` declaration for `{base}_value` whenever
self-recursion is detected, so `auto` deduction against that forward
declaration is provably correct, not a guess). A tuple-valued
self-recursive loop target is refused honestly (falls through the
existing `tuple_slot_ctypes is None` check) rather than guessed at —
out of scope here.

**Fix 2 — `_func_csym`'s mangled-key mirror used `setdefault`, freezing
a function's return/param type at whatever it was on the FIRST call,
even after later passes corrected it.** `_join`'s return type is
correctly inferred `char *` by Pass 1.3e ("refresh return types now
that param inference is final") — confirmed directly via debug
instrumentation: `func_return_types['_join']` == `'char *'` throughout.
But `_glob0` (which calls `_join`, and is compiled EARLIER in source
order) resolves its OWN call site's C symbol via `_func_csym('_join')`,
which mirrors the bare-name entry into the mangled-symbol key
(`func_return_types['_join_abb124']`) via `setdefault` — so whichever
call happened to run FIRST froze the mangled key's value forever,
regardless of any later correction to the bare key. `_emit_call` (the
GIMPLE call-emission helper) looks up the callee's return type BY THE
MANGLED KEY specifically to decide whether a cast is needed — a stale,
wrong mangled entry there overrides an otherwise-correct `ret_type`
with the wrong one, and then emits the call's real (correct) result
straight into a temp declared with the WRONG type, with no cast at all
(since the whole point of that lookup is "insert a cast when the two
disagree" — it never considered its own answer might itself be stale).
Concretely: `_t8 = _join_abb124(_t5, _t7);` assigned a genuine `char *`
return into an `_t8` declared `int64_t` — GCC's `-Wint-conversion`
"assignment to 'int64_t' from 'char *'" — reported at `glob.py:175`
only because of `-fgimple`'s unreliable un-`#line`-stamped physical-line
counting (the 2026-08-09 entry below already established the real
offending statement is inside `_glob0`, not `_glob2` — this pass
confirms and fixes the actual root cause that entry left open).
Fixed by changing both `func_param_types`/`func_return_types` mirrors in
`_func_csym` from `setdefault` to a plain assignment — always
re-mirroring the CURRENT bare-name value is strictly more correct than
freezing at first use, since later passes only ever have MORE
information than earlier ones, never less.

Verified via a direct isolated compile (both `do_imports=False` and the
full `do_imports=True` build): `_t3 = _join_abb124(_t5, _t7);` now (no
more int64_t detour), `_join`'s own definition/forward-declaration were
already correct (`char * _join_abb124 (char *, char *)`) and unchanged.
Whole-build error count for the SAME full `fire.py build`: 505 → 504
(exactly the one fixed error; a full before/after error-message-set
diff confirms zero new error categories introduced — the other 2
pre-existing `-Wint-conversion` "int64_t from char*" instances
elsewhere in the build, unrelated call sites, are untouched).

Full mandatory gate (CLAUDE.md) re-run after BOTH fixes together:
- `python3 test_gimple.py`: 247 passed, 0 failed
- `python3 test_module_cache.py`: 76 passed, 0 failed
- `make check-selfhost`: clean (fire.py compiling its own source)
- From-scratch `build/libmojostdlib.dylib` rebuild: 0 `skip <module>:` lines
- `python3 compile_stdlib.py` (no `-j`): 664/664 passed, 0 unexpected

**glob.py itself still does not build** — exactly ONE error remains,
precisely diagnosed but NOT fixed this pass (same architectural class
as the already-tracked, deliberately-deferred `bugs/hard/CODEGEN_same_
bare_name_struct_collision_across_modules.md`, just for FREE-FUNCTION
signatures instead of struct layouts):

```
/Users/mrs/net/Python-3.14.6/Lib/glob.py:354:9: error: too few arguments to function 'translate_584a43'; expected 4, have 1
```

Root cause, confirmed by direct inspection of the generated `.ci`:
glob.py's own `translate(pat, *, recursive=False, include_hidden=False,
seps=None)` (glob.py:294, 1 positional + 3 keyword-only params) is
compiled correctly as a real 4-parameter C function
(`char * translate_584a43 (char * pat, int64_t recursive, int64_t
include_hidden, int64_t seps)`). But its ONE call site
(`_compile_pattern`, glob.py:354: `translate(pat, recursive=recursive,
include_hidden=True, seps=seps)`) emits `translate_584a43 (_t11)` — only
`pat`, all 3 keyword arguments silently dropped. `Lib/fnmatch.py`
(transitively imported) has its OWN, UNRELATED top-level `def
translate(pat):` (fnmatch.py:95 — a single-positional-arg, no-kwonly-
param function, mangled separately as `fnmatch_translate_584a43` since
its own module-qualification differs). `_lower_named_call`'s keyword-
argument-padding logic (`expected_params = self.func_param_types.get
(fname_raw, [])`, keyed by the BARE name `'translate'`) reads from
`self.func_param_types` — a dict SHARED across the entire `do_imports=
True` transitive compile, not module-qualified, first/last-write-wins
— so glob.py's own `translate` call site ends up reading fnmatch.py's
`translate`'s signature (1 param) instead of its own (4 params),
padding zero extra arguments instead of the 3 needed. This reproduces
even though `fire.py build`'s PRIMARY path (`driver.py`'s per-module
link mode) would normally make this class of collision unreachable
(each module its own translation unit there) — glob.py's build falls
through to the vulnerable `do_imports=True` WHOLE-PROGRAM inline path
(`build_executable`'s fallback) for unrelated reasons (its own
coroutine-generator content), which is exactly the "structurally
possible when the primary link-mode path is bypassed" caveat the
same-bare-name-collision hard-bug doc already documents for the
struct-layout version of this same architectural gap. Not attempted
here: fixing it properly means module-qualifying `func_param_types`/
`func_return_types`/`_func_kwargs_slot` (or an equivalent conflict-
detection layer) across the whole `do_imports=True` compile — the same
broad, high-blast-radius shared-registry rework the struct-collision
doc already deliberately declined to attempt in a narrow pass, now
confirmed to also affect free-function signature/kwarg-padding
resolution, not just struct field layouts. Flagged here precisely so a
future pass targeting that whole hard-bug family has a second, cleanly
independent confirmed instance to fix alongside the struct one.

## Status (updated 2026-08-10 — re-verified the "struct _X_toplev" pattern task; a related-but-distinct variant found+fixed)

Investigated this session's cross-cutting task tracing a recurring
`invalid use of undefined type 'struct _<modname>_toplev'` GCC error
across 9 bug docs. This file was named in the 2026-08-07 entry below as
"likely another symptom of the same cross-module collision class" —
confirmed via a fresh rebuild that's WRONG (or at least stale): zero
occurrences of that exact error now (already fixed by the mechanism-1/
mechanism-2 fixes referenced there, `bugs/hard/COMPILE_FAIL_module_
toplev_struct_never_fully_defined.md`, deleted as resolved).

Found and fixed one closely related, previously-undocumented bug while
tracing the mechanism, and this file was the one that pinned it down
precisely: `typing.py` (transitively imported) does
```python
class _LazyAnnotationLib:
    def __getattr__(self, attr):
        global _lazy_annotationlib
        import annotationlib
        _lazy_annotationlib = annotationlib
        return getattr(annotationlib, attr)
```
`_gen_struct_method`/`_gen_lifted_closure` (gimple_codegen.py) never
set `self._current_module_ctx` — so this class's methods, compiled
FIRST in typing.py's own recursive do_imports=True compile (before any
ordinary function/toplevel statement had set the context), inherited
stale/default state and routed the `global` write to the wrong
module's struct: `struct '_root_toplev' has no member named
'_lazy_annotationlib'` (should have been `_typing_globals`). Fixed by
setting the context explicitly in both methods, mirroring `gen_func`/
`_gen_toplevel`'s existing identical line. Also fixed a related
`_safe_coerce_emit` bug this exposed: its `is_field` check only
recognized `->`-accessed struct-field LHS (needed to route a cast
through a register temp first, an `-fgimple` requirement), not plain
`.`-accessed ones (a non-pointer globals-struct instance's own field)
— once the write correctly targeted `_typing_globals._lazy_
annotationlib`, it produced an invalid combined cast+store statement,
"non-register as LHS of unary operation". Fixed by recognizing `.` too.

Effect on this file: total build error count dropped 504 -> 502 (both
of the above, confirmed via a full category diff — zero new error
categories introduced, only these 2 disappeared). This file's real
remaining blockers (line 175 / `_join_abb124`'s return-type gap, line
354 / `translate_584a43` keyword-arg-arity gap, described below) are
unaffected. No reclassification — glob.py still does not build.

## Correction (2026-08-09, later same day): the line-175 error's root cause was misattributed

The "updated 2026-08-09" note directly below (from an earlier commit
the same day) claimed `bugs/hard/CODEGEN_cross_module_bare_import_name_
collision.md`'s `_global_to_module` collision was "the real root cause
of the line-175 error" and "still present and unfixed." A careful
re-derivation (not just re-matching the same misleading `glob.py:175`
GCC line number, which this doc's own earlier methodology note already
warns is unreliable for this function) found this was wrong: the
`_global_to_module` read-side misattribution for `contextlib`
(glob.py's own `_listdir`, reading `_subprocess_globals.contextlib`)
was ALREADY fixed as a side effect of `bugs/hard/CODEGEN_module_globals_
cross_contamination_via_imported_stmts.md`'s "Mechanism 3" fix (commit
`21f5f49`, landed before this doc's own "updated 2026-08-09" note was
written — the note re-matched the symptom without re-verifying the
mechanism still applied). Confirmed directly: stripping all `#line`
directives from the generated `.ci` and recompiling shows GCC's real
physical-line error is inside `_glob0_737363` (`_t8 =
_join_abb124(_t5, _t7)` — assigning `_join_abb124`'s `char *` return
into an `int64_t`-declared temp), NOT any `contextlib`/`_global_to_
module` misattribution — a distinct, unrelated return-type-inference
gap in codegen for a path-join-style helper call. Separately confirmed
`_listdir_132aaf`'s own generated code no longer reads `_subprocess_
globals.contextlib` at all (falls through to the safe "unknown
identifier" placeholder, since it correctly recognizes it does not own
that name). `bugs/hard/CODEGEN_cross_module_bare_import_name_collision.
md` has been removed as fixed (see its own former content / this
commit's message for the full evidence). glob.py itself still does not
build — same practical bottom line — but for the `_join_abb124`
return-type bug above (not yet investigated further) and the line-354
`translate()` keyword-arg-arity gap already described below, not this
one.

## Status (updated 2026-08-09, re-verified — unchanged)

Re-verified against current master (post-merge `7df52a0`). Still fails
identically to the 2026-08-07 diagnosis below — exact same two errors,
same lines:
```
/Users/mrs/net/Python-3.14.6/Lib/glob.py:175:7: error: assignment to 'int64_t' {aka 'long long int'} from 'char *' makes integer from pointer without a cast [-Wint-conversion]
/Users/mrs/net/Python-3.14.6/Lib/glob.py:354:9: error: too few arguments to function 'translate_584a43'; expected 4, have 1
```
Confirmed again: `MOJO_DEBUG=1` shows no "not eligible" refusal for any
of glob.py's own generators. (See the correction above — the line-175
root-cause claim in this section is superseded/wrong.)

One addition: pinned down the second error (line 354,
`translate_584a43` arity mismatch) precisely — it is NOT generator-
related either. `translate(pat, *, recursive=False, include_hidden=
False, seps=None)` (glob.py:294) is an ordinary function with 3
keyword-only parameters; its one call site, `_compile_pattern`
(glob.py:354, `translate(pat, recursive=recursive, include_hidden=True,
seps=seps)`), passes all 3 by keyword. `translate` itself contains no
`yield` — this is a plain call-codegen gap in keyword-only-argument
forwarding for an ORDINARY function call, unrelated to the coroutine
generator path this cluster of bug docs is about. Left uninvestigated
further here (out of scope for the generator-codegen cluster; would be
better tracked as its own non-generator `CODEGEN_` doc if it recurs
elsewhere — a quick grep of the other 2 bug docs in this batch,
gettext.py/imaplib.py, found no matching symptom, so not folded into a
shared doc yet).

## Status (updated 2026-08-07, re-diagnosed — previous root cause was WRONG)

**STILL FAILING**, but the 2026-08-06 note's root-cause analysis below
(a generator yield-value forward-reference type-inference bug) has been
**re-investigated and disproven**. Re-confirmed against current master:
`MOJO_DEBUG=1` still shows NO "not eligible" refusal for any of glob.py's
own generators (`_iglob`, `_glob1`/`_glob0`, `_glob2`, `_iterdir`,
`_rlistdir`) — they all still reach real `.cpp` coroutine generation, and
directly inspecting the generated `.cpp` (both in isolation, `do_imports=
False`, and inside the full `do_imports=True` build) confirms
`_mojogen__glob2_value` is correctly typed `char *` in BOTH — i.e.
`_glob2`'s own promise/yield-value type inference is and was already
CORRECT. The forward-reference `_generator_yield_ctype` theory doesn't
hold up: `_yield_from_delegate_ctype` (gimple_codegen.py:2560) already
defaults an unregistered-generator `yield from` target to `'char *'`
(not `int64_t` — that default was fixed by commit `c234efb`, already on
master), so even the forward-reference case was never actually broken
here.

**Real root cause: `bugs/hard/CODEGEN_cross_module_bare_import_name_
collision.md`** (new hard-bug doc, written this session). The failing
line is NOT inside `_glob2` at all — GCC's reported `glob.py:175` is a
red herring (an artifact of un-`#line`-stamped physical-line counting
past the end of the PREVIOUS `#line`-stamped statement; `_glob2`'s own
source-line range never appears in the `.ci` at all, since it compiles
entirely via the `.cpp` coroutine path). The real offending code is
`_listdir` (a plain, non-generator helper a few lines later in the same
`.ci` region):

```python
def _listdir(dirname, dir_fd, dironly):
    with contextlib.closing(_iterdir(dirname, dir_fd, dironly)) as it:
        return list(it)
```

`glob.py` does `import contextlib` at module scope, but the compiled
`.ci` resolves that bare name to `_subprocess_globals.contextlib` —
`Lib/subprocess.py` (transitively reachable from glob.py's own import
graph) ALSO does `import contextlib`, and `self._global_to_module`
(gimple_codegen.py:3907), the name-only "which module owns this bare
global name" map, is SHARED across every module compiled in the same
`do_imports=True` build with first-registration-wins semantics —
subprocess's registration happens first (its own recursive sub-compile
runs before glob.py's own root-level preamble scan), so glob.py's own
`contextlib` reads get silently redirected to subprocess's globals
struct instead of its own. The resulting type mismatch (subprocess's
`contextlib` field's C type vs. what `_listdir`'s locals expect) is what
actually produces the `-Wint-conversion` "assignment to int64_t from
char*" error. See the hard-bug doc for the full trace, breadth (at
least 9 `Lib/*.py` files `import contextlib` alone — this is not
glob.py/contextlib-specific), and why it's deliberately NOT fixed here
(same architectural shape/blast radius as the already-deferred task
#141, `bugs/hard/CODEGEN_same_bare_name_struct_collision_across_
modules.md` — a shared, name-only, first-writer-wins cross-module map
used at 4+ separate read sites project-wide, not a narrow generator-
codegen bug at all).

**Classification: NOT a generator-codegen-cluster failure.** Both of
glob.py's own generators compile correctly; the failure is entirely in
plain (`.ci`) code that happens to consume one, via a totally unrelated
cross-module global-resolution bug.

The two other current errors (`translate_584a43` arity mismatch,
`struct _subprocess_toplev` undefined) were not investigated further —
still look unrelated to the generator-codegen cluster (arity/import-
resolution issues in non-generator code; the `_subprocess_toplev`
naming is likely itself another symptom of the same cross-module
collision class, given the pattern above) and are left for a separate
pass.

## Status (updated 2026-08-06, SUPERSEDED — root cause below was wrong, kept for history)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'os' was not declared` .cpp error no longer reproduces
(dyld.py's documented "module attribute access not threaded into
generator scope" gap — see `bugs/COMPILE_FAIL_ctypes_macholib_dyld.md`
— appears fixed for glob.py's shape at least). `MOJO_DEBUG=1` shows NO
"not eligible" refusal for any of glob.py's own generators (`_iglob`,
`_glob1`/`_glob0`, `_glob2`, `_iterdir`, `_rlistdir`) — all pass the
eligibility pre-filter and reach real `.cpp` generation.

Current failure, still inside the generator-codegen cluster but a
DIFFERENT, narrower bug than the old one:

```
/Users/mrs/net/Python-3.14.6/Lib/glob.py:175:7: error: assignment to 'int64_t' {aka 'long long int'} from 'char *' makes integer from pointer without a cast [-Wint-conversion]
```

**Root cause (read from `_glob2`'s source) — WRONG, see 2026-08-07 above:**
```python
def _glob2(dirname, pattern, dir_fd, dironly, include_hidden=False):
    assert _isrecursive(pattern)
    if not dirname or _isdir(dirname, dir_fd):
        yield pattern[:0]                                    # char* (empty string slice)
    yield from _rlistdir(dirname, dir_fd, dironly,            # forward reference!
                         include_hidden=include_hidden)
```
`_glob2` has TWO yield sites of apparently different shapes: a direct
`yield pattern[:0]` (a string slice, `char *`) and a `yield from
_rlistdir(...)` — but `_rlistdir` is DEFINED LATER in the file (line
218, vs. `_glob2` at line 170). This is the same forward-reference
caveat already surfaced in this session's `MOJO_DEBUG` output for a
different function in this same file (`tokenize`-style note: *"the
delegated-to generator must be defined earlier"*) — when the overall
generator's yielded-VALUE type is computed (`_generator_yield_ctype`),
the `yield from` to a not-yet-registered generator apparently doesn't
contribute its real element type to the join, so the combined value type
collapses to the `int64_t` default instead of joining to `char *` (the
correct common type, since `_rlistdir` itself ultimately yields strings
too). The result: the coroutine promise's `yield_value` is generated
expecting `int64_t`, but the `yield pattern[:0]` call site still
produces a real `char *` — hence "assignment to int64_t from char*".

This is a variant of the already-documented "generator yielded-value
type inference" gap (`bugs/COMPILE_FAIL_ctypes_macholib_dyld.md`'s
bullet 1, and the untyped-generator-param cousin in
`CODEGEN_generator_struct_typed_param_refused`'s sibling
docs) — specifically the FORWARD-REFERENCE angle of it: a generator with
a `yield from` to a same-file sibling generator defined LATER, combined
with an earlier plain `yield` of a different concrete type, produces a
wrong combined promise type. Not folded into a new hard-bug doc here
(only one clean instance traced end-to-end so far) — flagged for whoever
next hits this shape to fold into a broader "generator yield-value type
inference" hard doc once 2-3 more instances are confirmed.

The two other current errors (`translate_584a43` arity mismatch,
`struct _subprocess_toplev` undefined) were not investigated — they look
unrelated to the generator-codegen cluster (arity/import-resolution
issues in non-generator code) and are left for a separate pass.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/glob.py
