# CODEGEN_generator_function: Lib/enum.py

## Status (re-verified 2026-08-26, worktree fix/opencode-genlib2): unchanged — same 3-function `cls`-access refusal set

Fresh strict isolated `compile_to_gimple_with_cpp(do_imports=False)`:
byte-for-byte identical refusal set — `_iter_member_`,
`_iter_member_by_def_`, `_iter_member_by_value_` all refused with "a
@classmethod generator that references `cls` in its body in an
unsupported way is not supported" (matches the wtRest19b entry,
including `_iter_member_` being listed as its own function via the
body-level alias mechanism). Root cause unchanged and re-confirmed:
`cls._flag_mask_`/`cls._value2member_map_` exist only through
`EnumMeta.__new__`'s dynamic classdict machinery, never as literal
class-body AssignStmts, so `_cls_refs_supported` correctly has no
redirect target — and stubbing them would silently miscompile (e.g.
`_flag_mask_ = 0` makes every Flag iteration yield nothing). Still a
feature-sized dynamic-metaclass-attribute-modeling gap, with the
`_iter_member_by_def_` lambda/generator-via-cls stack behind it. No code
change; doc stays open.

## Status (re-verified 2026-08-26, wtRest19b): unchanged — same 6 `cls`-access refusal lines

Fresh `MOJO_DEBUG=1 python3 mojo.py build .../Lib/enum.py` against
current tree (fix/rest-remainder19b, heavy concurrent build load from
other campaign agents noted but debug-mode run completed): identical
refusal set, byte-for-byte the same message text as 2026-08-25 —
`Flag`/`IntFlag` × `_iter_member_by_value_`/`_iter_member_by_def_`/
`_iter_member_` all refused with "a @classmethod generator that
references `cls` in its body in an unsupported way is not supported".
Root cause confirmed unchanged: `cls._flag_mask_`/`cls._value2
member_map_` are populated only via `EnumMeta.__new__`'s dynamic
`classdict[...] = ...` metaclass machinery, never as literal
class-body AssignStmts, so `_cls_refs_supported`'s class-attribute
redirect correctly has no entry to redirect through. This remains a
feature-sized dynamic-metaclass-attribute-modeling gap, not a narrow
fix. Not attempted; no code change.

## Status (updated 2026-08-25, worktree fix/opencode-group2 — re-verified fresh; unchanged refusal, still feature-sized, one prior sub-gap now closed upstream)

Re-ran a fresh, safety-wrapped `python3 mojo.py build
.../Lib/enum.py` on current master (`4220964`): the module still refuses
on exactly 3 named generator functions — `_iter_member_`,
`_iter_member_by_def_`, `_iter_member_by_value_` (the body-level alias
mechanism from commit `6e92df8` correctly gives `_iter_member_` its own
refusal now, so it is listed as its own function rather than hiding
behind the other two) — all for the same reason as the 2026-08-21
entry: "a @classmethod generator that references `cls` in its body in
an unsupported way".

What changed since that entry, checked directly:

1. **Upstream progress, currently unreachable**: the
   `bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md` mechanism
   now covers single-parameter lambdas plus real
   `sorted(..., key=lambda m: ...)` support in the coroutine emitter,
   explicitly motivated by this file's `_iter_member_by_def_`. That
   removes what used to be `_iter_member_by_def_`'s second independent
   refusal (the `key=` lambda) — but only for bodies that get past the
   cls gate, which enum.py's own three never do.
2. **The remaining root cause is unchanged and confirmed
   feature-sized**: `_iter_member_by_value_`'s body needs
   `cls._flag_mask_` (line 1432) and `cls._value2member_map_.get(val)`
   (1433); both attributes exist ONLY through `EnumMeta.__new__`'s
   dynamic `classdict['_value2member_map_'] = {}` /
   `classdict['_flag_mask_'] = 0` writes (enum.py:531/544) plus
   post-construction mutation (`enum_class._flag_mask_ |= value`,
   enum.py:277) — never as literal class-body AssignStmts, so
   `_class_attrs['Flag']` has no entry and `_cls_refs_supported`
   correctly refuses rather than stubbing. Stubbing would be a silent
   miscompile, not a fix: `_flag_mask_ = 0` makes
   `_iter_bits_lsb(value & 0)` yield nothing, so every Flag iteration
   would silently produce zero members.
3. **Even full compile-side support would not make enum.py work**:
   runtime-correct behavior additionally needs (a)
   `cls._iter_member_by_value_(value)` — a GENERATOR-method call via
   `cls`, needing coroutine-construction convention at that call site
   (still excluded by `_cls_refs_supported`, correctly); and (b) the
   whole `EnumType` metaclass pipeline (dynamic class construction,
   `classdict` manipulation, `_missing_`/`__new__` interplay) to run
   correctly in the compiled model, which is far outside any narrow
   fix's reach.

Conclusion unchanged from the 2026-08-21/24 entries, now re-confirmed
against today's tree: not tractable without a feature-sized
metaclass-attribute-modeling project; doc stays open. No code change;
no gate run (nothing touched).


## Status (updated 2026-08-24, worktree fix/rest-remainder3 — the `_iter_member_` "1-arg-only" symptom re-investigated; NOT an arity bug, root cause is deeper)

Re-verified the `Flag__iter_member_(self, self->_value_)` call the prior
entry flagged. The arity itself is now correct (2 args, matching the
class-body-alias mechanism from commit `6e92df8` — `_iter_member_ =
_iter_member_by_value_` correctly copies the real method's 2-param
signature into the alias). The actual current error is different:
`Flag__iter_member_` is declared `extern "C" void (int64_t, int64_t)` —
a bare ORDINARY-struct-method fallback signature — while the real call
site needs the GENERATOR-METHOD-API convention (this method has a real
`yield`/`yield from`, consumed via `yield from cls._iter_member_(...)`
in `Flag.__iter__`). Traced further: `gen._struct_generator_method_
names['Flag']` correctly LISTS `_iter_member_` (and `_iter_member_by_
value_`/`_iter_member_by_def_`) as known generator methods by name, but
`gen._generator_method_api` has NO entry for ANY of the three — meaning
none of them actually got compiled into a real coroutine unit in this
run; the extern declaration falls back to the generic non-generator
default. Not root-caused further (why the classmethod generator itself
never registers, despite being correctly named) — likely related to,
but distinct from, the file's 4 already-documented `cls`-attribute
eligibility refusals (task's own `relaxed_imports=True` bypass may be
masking rather than fixing whatever blocks these three specifically).
Not attempted: even a full fix here would not unblock `enum.py`
end-to-end (still blocked by the 4 already-documented `cls`-attribute
refusals regardless). Flagged for whoever next investigates the
generator-method-API registration gap for classmethod generators.


## Status (updated 2026-08-24 — `%r`-format crash in `_iter_bits_lsb` FIXED; one unrelated arity bug newly surfaced)

Re-verified with `GimpleGen(do_imports=False, relaxed_imports=True)`
(bypasses the 4 already-documented `cls`-attribute refusals so the REST
of the file still gets a `.cpp` emitted, rather than the hard whole-
module `RuntimeError` a plain `mojo.py build`/non-relaxed isolated
compile produces — same methodology `dis.py`'s doc already uses). This
surfaces 2 further, previously-masked issues once past those 4 refusals:

1. **Fixed**: `_iter_bits_lsb`'s `raise ValueError("%r is not a positive
   integer" % original)` — the coroutine-body `%`-format crash (see
   `bugs/CODEGEN_generator_function_Lib_ipaddress.md`'s matching entry
   for the shared root cause and fix, `gimple_cpp_core.py`'s new
   `_cpp_percent_format`). Confirmed via isolated compile: this specific
   error is gone.
2. **NOT fixed, newly surfaced, unrelated**: `Flag.__iter__` (line 200)
   emits `Flag__iter_member_(self, self->_value_)` — 2 arguments — against
   `_iter_member_` declared taking only `(Flag *)` (1 argument, no
   `_value_`). A real arity/signature-resolution mismatch for a struct-
   method call inside a coroutine body, unrelated to the `cls`-attribute
   refusals or the `%`-format fix; not investigated further (out of
   scope for this pass — a narrow but real bug worth its own follow-up).

Full mandatory gate for the `%`-format fix: `test_gimple.py` 252/252,
`test_module_cache.py` 76/76, `make check-selfhost` clean, from-scratch
stdlib dylib rebuild 0 skip lines. Commit `d3154a6`.

`enum.py` as a whole still does not build — the 4 already-documented
`cls`-attribute refusals (still genuinely feature-sized, unchanged) plus
the newly-surfaced `_iter_member_` arity bug above remain. Doc stays
open.


## Status (updated 2026-08-23 — re-verified unchanged; refusals remain the verified-correct ones)

Re-ran `MOJO_DEBUG=1 mojo.py build` + isolated compile: identical 4 refusal
lines (Flag/IntFlag `_iter_member_by_value_`/`_iter_member_by_def_`,
"cls referenced in an unsupported way") escalating to the standard fatal
module refusal. This session's three generic generator-codegen fixes
(enumerate-over-generator delegation, struct-method default-arg padding,
list/dict/set literal locals in coroutine bodies) do not touch either
remaining root cause: the dynamic-metaclass-populated attributes
(`cls._flag_mask_`/`cls._value2member_map_` never appear as class-body
AssignStmts) and the `LambdaExpr`-as-call-argument sort key — both still
feature-sized, both still honestly refused. No change.


## Status (updated 2026-08-21 — `cls`-attribute-redirect IMPLEMENTED; enum.py's OWN refusal still stands, for an honest reason)

The 2026-08-10 note's own real-fix-attempt (points (1)+(2): `cls.method(...)`
calls resolved purely by name via `_classmethod_names`/`func_return_types`;
`cls.<attr>` bare reads redirected through `self._class_attrs[struct_name]
[attr] -> mangled global`, the exact same mechanism `self.<class-attr>`
reads already use) is now IMPLEMENTED, now that the 2026-08-20 update above
closed the yield-type gap that previously made landing (1)+(2) alone unsafe.

**What was implemented**, all in `gimple_codegen.py`:
1. `_cpp_expr`'s MemberExpr case gained a `cls.<attr>` branch (mirroring
   the existing `self.<field>` branch just above it): redirects to
   `self._class_attrs[struct_name][attr]`'s mangled global when `<attr>`
   is a real class-body-declared attribute, else raises
   `_UnsupportedGeneratorShape` (there is no `cls-><attr>` struct-pointer
   form to fall back to — `cls` is only ever an opaque, never-dereferenced
   `int64_t` placeholder in this codegen, never a real object).
2. `_cpp_expr`'s CallExpr/MemberExpr case gained a `cls.<method>(...)`
   branch (mirroring the existing `self.<method>(...)` branch): resolves
   purely by NAME via `_cpp_gen_self_struct` (the enclosing struct) plus
   `self._classmethod_names`/`self.func_return_types` — no real runtime
   `cls` value needed, exactly like the ordinary (non-coroutine) path's
   own `cls.method(...)` resolution. Explicitly EXCLUDES a call to another
   compiled GENERATOR method (see point 4 below) — that needs its own
   coroutine-construction call convention (mirroring the ordinary path's
   `_generator_method_api`/`_gm_api` handling) this fix does not add.
3. The dict-`.get()` call lowering (`<dict>.get(key)`) and the yield-type
   inferencer's matching `dict_val_types`/`_receiver_key` machinery were
   both widened to recognize `cls.<dict-attr>.get(key)` as a THIRD
   receiver shape alongside the existing bare-local and `self.<field>`
   ones — sourced from a new class-level-global sibling of `self._field_
   dict_val_types` (`self._global_dict_val_types`, eagerly seeded from a
   class attribute's own `_X: dict[K, V] = ...` annotation, mirroring the
   2026-08-20 update's identical instance-field seed) so `cls._value2
   member_map_.get(val)`'s real struct-pointer VALUE type is resolved
   instead of silently defaulting to `int64_t`.
4. **A real gap found and closed while wiring this up**: `self.
   _classmethod_names` is populated purely from the `@classmethod`
   decorator, independent of whether the method is ALSO a generator — a
   real `@classmethod` GENERATOR (Lib/enum.py's `Flag._iter_member_by_
   value_` is exactly both at once) is IN `_classmethod_names`. Without a
   separate check, `cls._iter_member_by_value_(value)` (inside `_iter_
   member_by_def_`) was wrongly accepted by BOTH the eligibility gate and
   `_cpp_expr`'s new call-handling as "a call to a real compiled
   classmethod" and lowered to a call to `_struct_method_csym(...)` — a
   symbol that was NEVER compiled (generator methods are skipped from
   ordinary C-function compilation entirely; see gen_module's Phase 2a
   skip for `_supported_generator_methods`). Worse: this ALSO silently
   exposed a genuinely separate, pre-existing gap — `_cpp_expr`'s generic
   bare-function-call fallback (the one `sorted(...)` falls through to,
   since there is no dedicated `sorted()` case in the coroutine-body
   emitter) only ever lowers `e.args`, never `e.kwargs` — so `_iter_
   member_by_def_`'s `sorted(cls._iter_member_by_value_(value), key=lambda
   m: m._sort_order_)` would have silently DROPPED the `key=` kwarg
   entirely, meaning the `lambda m: m._sort_order_`'s own "a lambda with
   parameters is not supported" refusal (`_cpp_expr`'s LambdaExpr case)
   was NEVER EVEN REACHED — `_iter_member_by_def_` was accepted as
   eligible with ZERO refusal lines logged for it, a genuine SILENT
   MISCOMPILE (unsorted output) that would have shipped clean. Fixed by
   adding `self._struct_generator_method_names` (struct name -> set of
   that struct's own generator method names, from `FunctionDef.
   is_generator`, populated once per struct in the same early pre-pass
   that already populates `self._class_attrs`) and excluding any `cls.
   <method>(...)` call whose target is in that set from BOTH the
   eligibility gate (`_cls_refs_supported`) and `_cpp_expr`'s call
   lowering — `_iter_member_by_def_` is refused again, for the correct,
   pre-existing reason (a `LambdaExpr` used as a call argument — see
   `bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`), not silently
   accepted. The kwargs-dropped-entirely gap in the generic call fallback
   itself is real and NOT fixed here (still `e.args`-only) — it's simply
   no longer reachable through this specific `cls`-based path, since the
   generator-method exclusion refuses the call one level up, before the
   dropped-kwargs codepath is ever reached for this shape. A general fix
   (refusing ANY unrecognized kwarg on that fallback, or lowering it
   properly) is out of this fix's scope; flagged here in case a future
   session hits the same exposure through a different call shape.
5. The classmethod/`cls`-generator eligibility gate (`gimple_codegen.py`,
   ~line 30536, `bugs/hard/CODEGEN_generator_classmethod_first_param_
   must_be_self.md`'s original carve-out) was relaxed from a blanket "any
   `cls` reference anywhere in the body -> refuse" AST scan to a new
   `_cls_refs_supported` helper: walks the body, marks each `cls.<attr>`/
   `cls.<method>(...)` occurrence "supported" using the EXACT SAME rules
   `_cpp_expr` itself now applies (points 1/2/4 above), then requires
   EVERY `cls` `IdentExpr` in the body (by AST-node identity, not by
   name/shape) to be one of those marked occurrences — a bare `cls` used
   as a plain value, or any `cls.<attr>`/`cls.<method>(...)` shape neither
   of those rules cover, still refuses, exactly as conservatively as the
   original blanket check did for every shape this fix doesn't add real
   support for.

**Verification — isolated repro, real compile+link+RUN (not just
`-fsyntax-only`).** Two new tests in `test_gimple_generator_runner.py`,
both asserting on actual stdout:
- `cls_class_attr_dict_get_yield`: a `@classmethod` generator (`Registry.
  gen(cls, k)`) reading a bare class-level attribute (`cls._mask`) and
  yielding a `cls.<dict-attr>.get(k)` result whose value type is a real
  struct pointer (`Flag *`) — the literal shape this task targeted,
  mirroring `Flag._iter_member_by_value_`. (The class-body dict attribute
  is populated via `self._value_map[k] = ...` in `__init__` rather than a
  literal-with-pairs initializer — a SEPARATE, pre-existing gap this fix
  did not touch: class-body `dict`/`list`-valued attribute LITERALS with
  actual pairs/elements are never populated into the runtime container at
  all, only `MojoSet` literals are — see `gen_module`'s "Class-level
  attribute globals" pass, the `elif ctype == 'MojoDict *': ... mojo_dict_
  new()` branch with no populate-from-literal-pairs loop, unlike the
  `MojoSet *` branch just above it. Confirmed via a direct repro before
  routing around it in the test; not fixed here, out of this task's
  scope, not documented as its own bug report since it's narrow and this
  note already root-causes it.)
- `cls_classmethod_call_in_generator`: a `@classmethod` generator calling
  another real (non-generator) `@classmethod` of the same struct via
  `cls.double(n)`.

Both called via an INSTANCE (`r.gen(k)`), not the class name directly
(`Registry.gen(k)`) — invoking a `@classmethod` generator via the class
name hits a separate, pre-existing call-site gap in the ordinary
(non-generator) GIMPLE path (the ordinary `ClassName.method(...)` call
lowering doesn't check whether `method` is a compiled generator needing
the `_start`/coroutine-construction API instead of an ordinary function
call — confirmed via a direct repro: `gcc -fgimple` failed with `implicit
declaration of function 'Registry_gen'`), unrelated to `cls`-attribute
access inside the body and out of this task's scope.

Both pass; all 39 pre-existing generator-runner tests still pass (41
total); `test_gimple.py` (250/250), `test_module_cache.py` (76/76),
`make check-selfhost` all green; a from-scratch stdlib dylib rebuild in
this worktree and an independent baseline worktree (checked out at
`5c1140f`, this fix's parent commit) both show 0 `skip <module>:` lines
(no regression).

**enum.py's own status, re-verified — both methods STILL refused, now for
verified-correct reasons.** `MOJO_DEBUG=1 python3 mojo.py build
.../Lib/enum.py`:
```
generator method Flag.'_iter_member_by_value_' not eligible ...: a @classmethod generator that references `cls` in its body in an unsupported way is not supported (only a class-level-attribute read, or a call to a real compiled classmethod/static method of the enclosing class, are supported for `cls.<...>` access in a compiled generator)
generator method Flag.'_iter_member_by_def_' not eligible ...: [same message]
generator method IntFlag.'_iter_member_by_value_' not eligible ...: [same message]
generator method IntFlag.'_iter_member_by_def_' not eligible ...: [same message]
Error building: cannot compile module: function(s) _iter_member_by_def_, _iter_member_by_value_ (generator function(s), contain a `yield`/`yield from`) — ... falling back to interpreting this module from source instead
```
- `_iter_member_by_value_`: STILL refused, but the ROOT CAUSE is now
  different from before this fix (previously: blanket "any cls reference"
  refusal). Now: `cls._flag_mask_`/`cls._value2member_map_` genuinely
  don't qualify for the new redirect, because they are NOT literal
  class-body `AssignStmt`s inside `Flag`'s own source (`self._class_attrs
  ['Flag']` is empty of them) — real CPython `enum.py` sets both
  dynamically, from `EnumMeta.__new__`'s metaclass machinery
  (`classdict['_flag_mask_'] = 0`/`classdict['_value2member_map_'] = {}`
  building the class's `__dict__` BEFORE the class object even exists,
  then `enum_class._flag_mask_ |= value` mutating it afterward on the
  already-constructed class) — never as `_flag_mask_ = 0`/`_value2
  member_map_ = {}` text sitting directly in `class Flag(...): ...`'s own
  body. This is a GENUINELY different, and considerably harder, problem
  than the one this task's own isolated repro (and the 2026-08-10 note's
  original analysis) targeted — it would need this codegen to somehow
  model attributes assigned through a dynamic metaclass `__new__`/
  `__init_subclass__` pipeline as if they were ordinary class-body
  declarations, which is a much bigger, separate, feature-sized gap. Not
  attempted; not this task's scope.
- `_iter_member_by_def_`: STILL refused, and for TWO independent reasons
  now, same as before this fix: (a) its own `cls._iter_member_by_value_
  (value)` call is a call to a GENERATOR method via `cls`, which point 4
  above explicitly excludes (needs coroutine-construction handling this
  fix does not add); (b) even setting (a) aside, `key=lambda m: m._sort_
  order_` is a `LambdaExpr` used as a call argument
  (`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`, closed only
  for the "lambda assigned to a local" shape, not "lambda passed as a
  call argument"). Point 4's fix above specifically closed the SILENT
  version of this refusal (where it would have compiled with the sort key
  silently dropped) back to an HONEST one.

So: the `cls`-attribute-redirect mechanism this task set out to implement
is real, implemented, and verified working end-to-end on the shape it
targets (a genuine class-body-declared attribute) — it just doesn't
happen to cover enum.py's OWN specific attributes, which are populated
through a different, dynamic-metaclass mechanism this codegen has no
model for at all. `enum.py` itself remains unbuilt via the compiled path
(still falls back to interpreting it from source, correctly and safely).

## Status (updated 2026-08-20 — struct-pointer-yield gap CLOSED; enum.py's OWN refusal unchanged)

The 2026-08-10 note below (option (b): "actually widen the coroutine
promise/co_yield representation to carry a genuine pointer value across
the suspend boundary") is now implemented, as a real, general feature —
not narrowly overfit to `cls._value2member_map_.get(val)`'s exact shape.
Verified independently of enum.py itself (see "enum.py's own status,
re-verified" below for why enum.py's build error is unchanged despite
this).

**What was fixed.** `_infer_simple_expr_ctype` (`gimple_codegen.py`,
~line 2718) — the function `_generator_yield_ctype` calls per yield site,
whose `None` result used to silently default to `int64_t` — now
recognizes three real-struct-pointer-producing shapes, gated behind three
new optional parameters (`known_structs`, `dict_val_types`,
`method_return_types`; every existing caller that doesn't pass them keeps
the original scalar-only behavior unchanged):
1. `self.<field>` where the field's own declared type is a known struct
   pointer (was previously excluded outright — only the four scalar
   ctypes were accepted).
2. `<dict-typed self.field>.get(key)` — the exact enum.py shape,
   generalized to any `dict[K, StructType]`-typed field, not just
   `_value2member_map_`. Resolved via `self._field_dict_val_types`, the
   SAME per-struct-field dict-value-type registry the ordinary (non-
   generator) GIMPLE path already populates from a `.get()`/`d[k]` read —
   reused, not reinvented — but that registry is normally populated
   LAZILY (during ordinary per-statement body compilation), which runs
   AFTER generator methods are translated (gen_module's "Milestone C step
   3" pass) — so it was empty at the time a generator method needed it.
   Fixed by ALSO seeding it eagerly, from the field's own `var x: dict[K,
   V]` class-body declaration, at the SAME early struct-field-type
   pre-pass that already resolves a field's plain ctype this early (the
   struct-pointer-typed-parameter case reads `self.struct_field_types`
   this same early, confirming the pre-pass's timing was already right
   for this) — one extra `self._annotation_dict_val_type(field.type_ann)`
   call reusing the existing helper, not a new type-annotation parser.
3. The general case: an arbitrary `<receiver>.<method>(...)` call chain
   where `<receiver>` recursively resolves to a known struct pointer —
   resolved via `method_return_types` (`self.func_return_types`, the SAME
   registry every ordinary compiled struct-method CALL site already uses,
   keyed `f"{struct_name}_{method_name}"`).

**Promise/co_yield representation — confirmed unchanged, as expected.**
Verified BEFORE writing any fix (a minimal `yield <struct-pointer-typed
param>` repro) that a bare struct-pointer yield already compiled and ran
correctly end-to-end with ZERO promise/co_yield/consumer-side code
changes — `_c_to_cpp_scalar_type` already passes a struct-pointer ctype
straight through unchanged (same as the pre-existing `char *`/`MojoList
*` cases), the coroutine promise's `current_value` field/`yield_value`
parameter/`{base}_value` return type already work for ANY ctype
generically, and the ordinary `for x in gen():` consumer-side unboxing
(`_cpp_for_stmt`'s non-tuple branch) already declares the loop target
with whatever `vct` it's given, with no hardcoded scalar/MojoList*
allowlist. So this really was the "materially simpler" feature the task
anticipated — no promise-shape change of any kind was needed, confirming
option (b) from the 2026-08-10 note.

**Two real gaps DID need closing beyond pure type inference**, both
found by actually compiling+linking+running an end-to-end repro (not
just a `-fsyntax-only` .cpp compile):
- `_cpp_expr`'s CallExpr/MemberExpr lowering had NO case for `<dict>.get(
  key)` at all — it fell through to the generic `{obj}.{member}(args)`
  C++ text, which doesn't compile against an opaque `MojoDict *` (no real
  C++ member functions). Added a case mirroring the existing
  `mojo_dict_get_int`/`_double`/`_str` three-way dispatch the ordinary
  (non-generator) path's own `.get()`/`d[k]` lowering already uses,
  casting the `mojo_dict_get_int` result back to the real struct pointer
  type when the dict's value type is one (pointers are stored as int64_t
  in this dict representation — same convention `_pack_kwargs_dict`'s own
  docstring documents for "ints, doubles, pointers").
- The .cpp preamble's struct-typedef emission only pulled in a struct
  reachable via `self`, a generator/async parameter, an inline
  constructor call, or (transitively) one of THOSE structs' own fields —
  never a struct reachable ONLY through the yielded value's resolved
  type. Added `self._cpp_value_struct_names`, populated wherever a
  generator/async unit's finalized `value_ctype` is a struct pointer,
  merged into the same typedef-emission BFS the other three sources
  already feed.

**Verification.** Two new isolated repros in `test_gimple_generator_
runner.py` (real compile+link+RUN, asserting on actual stdout, not just
"compiles"): `struct_ptr_dict_get_yield` (the `self.<dict-field>.get(k)`
shape) and `struct_ptr_method_chain_yield` (the general method-call-chain
shape: `o.get_inner()` returning another struct pointer, yielded
directly). `struct_ptr_bare_param_yield` added too as an explicit
regression guard for the already-working bare-struct-pointer-yield case.
All pass; all 36 pre-existing generator-runner tests still pass (39
total); `test_gimple.py` (248/248), `test_module_cache.py` (76/76),
`make check-selfhost` all green; a from-scratch stdlib dylib rebuild
shows 0 `skip <module>:` lines both before and after this change (no
regression — expected, since this fix doesn't by itself unblock any
currently-refused stdlib generator: enum.py's own two generator methods
are refused by the SEPARATE cls-access gate below, before this fix's
code path is ever reached, and no other stdlib generator this session's
corpus scan found was gated on struct-pointer-yield type inference
alone).

**enum.py's own status, re-verified — UNCHANGED, as expected.**
`MOJO_DEBUG=1 python3 mojo.py build .../Lib/enum.py` still produces the
exact same 4 refusal lines it did before this fix, verbatim: `Flag`/
`IntFlag`'s `_iter_member_by_value_`/`_iter_member_by_def_` are still
refused for "a @classmethod generator that references `cls` in its body
is not supported". That gate (`bugs/hard/CODEGEN_generator_classmethod_
first_param_must_be_self.md`) fires at generator-ELIGIBILITY time, before
the body is ever translated — so it refuses `cls._value2member_map_.
get(val)` for referencing `cls` at all, never even reaching this fix's
new `_infer_simple_expr_ctype` logic (which only runs on a body that
passed eligibility). This fix closes the SEPARATE, real gap the
2026-08-10 note below root-caused (what happens to the YIELD TYPE once
`cls`-attribute access is eventually supported) — it does not, and was
never going to, touch the `cls`-access gate itself; that remains exactly
as out-of-scope as the 2026-08-09 note below already assessed it to be.
`_iter_member_by_def_`'s independent `LambdaExpr`-as-call-argument
refusal (`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`) is
likewise unaffected. So: the specific silent-miscompile risk this
session's earlier real-fix-attempt correctly declined to ship (landing
`cls`-access without ALSO closing the yield-type gap) is now closed, but
enum.py itself needs the `cls`-access gap fixed FIRST before this fix
can even become visible on that file — still not attempted, still
feature-sized, still out of this fix's scope.

## Status (updated 2026-08-10, re-verified + deepened — real fix attempted, concrete blocker found)

Re-confirmed against current master (fast-forwarded to `9d93746`,
which includes this session's tuple-valued-`yield` boxing work):
identical repro, identical 4 refusal lines, same fatal error. The
tuple-yield fix landed earlier this session (commit `a7b71a0`) does
NOT touch this file's failure at all — neither `_iter_member_by_value_`
nor `_iter_member_by_def_` yields a tuple.

**Real fix attempted and NOT landed — here is exactly what was tried
and why it stops short of safe:**

The classmethod/`cls` eligibility gate's own comment
(`gimple_codegen.py:26404-26407`) claims "no class-level attribute/
method access exists yet for compiled generators" as if this were a
totally unbuilt feature. That's not quite right — investigated the
actual machinery two levels deep:

1. **`cls.method(...)` calls already resolve correctly outside
   generators.** The ordinary (non-coroutine) `_lower_MemberExpr`/
   CallExpr path (`gimple_codegen.py:11822-11890`) already resolves
   `cls.method(...)` inside a real `@classmethod` purely by NAME (via
   `current_func_name` + `self._classmethod_names`, no runtime `cls`
   value needed at all) — this is a working, general mechanism, just
   never wired into the SEPARATE, hand-rolled coroutine-body emitter
   (`_cpp_expr`, `gimple_codegen.py:23816` on) that generator bodies use
   instead.
2. **`cls.<attr>` bare reads already have a redirect mechanism for
   `self`** — `self._class_attrs[struct_name][attr] -> global variable`
   (`gimple_codegen.py:9523-9530`, `29869-29910`), used today for
   `self.<class-attr>` reads. The exact same redirect, keyed off the
   enclosing struct name (derivable from `_cpp_gen_self_struct` the
   same way the eligibility check already derives `struct_name` for its
   scan), would trivially cover `cls._flag_mask_`/`cls._value2member_map_`
   in `_cpp_expr`'s MemberExpr case (`gimple_codegen.py:23882-23909`,
   which today ONLY handles `self.<field>`).

So a real fix for `_iter_member_by_value_`'s literal body (`for val in
_iter_bits_lsb(value & cls._flag_mask_): yield
cls._value2member_map_.get(val)`) looked tractable at first — `cls.
_flag_mask_` is a bare class-attr read (mirror the `self` redirect) and
`cls._value2member_map_` is too (`.get(val)` is then an ordinary dict
method call, already supported).

**Where it breaks: the YIELDED value's type would be silently wrong,
not just refused.** `cls._value2member_map_.get(val)` returns a `Flag *`
(an enum member reference), not a scalar. The yield-type inferencer
`_generator_yield_ctype` (`gimple_codegen.py:2758`) calls
`_infer_simple_expr_ctype` (`gimple_codegen.py:2472`) per yield site;
that function has NO case for a `CallExpr` whose `func` is an arbitrary
`MemberExpr` chain returning a struct pointer (its `CallExpr`-with-
`MemberExpr`-func branch, `gimple_codegen.py:2555-2580`, only
recognizes a small hardcoded allowlist — `os.path.*`, `math.*`, `str.
format`) — it falls through to `return None`, and
`_generator_yield_ctype`'s caller then does `t = None -> t =
'int64_t'  # default when type can't be inferred`
(`gimple_codegen.py:2841-2842`). That default is exactly wrong here: a
`Flag *` pointer would get silently reinterpreted/truncated as
`int64_t`, producing a wrong runtime value that still compiles clean —
a SILENT MISCOMPILE, strictly worse than today's honest refusal. Fixing
this properly needs `_infer_simple_expr_ctype` to recognize a dict
`.get()` call (and general struct-returning member-call chains) and
either (a) refuse (return `None` all the way through, i.e. make the
"can't infer -> default int64_t" fallback in `_generator_yield_ctype`
stop defaulting for this shape and refuse instead), or (b) actually
widen the coroutine promise/co_yield representation to carry a genuine
pointer value across the suspend boundary — the SAME kind of "value
crossing a suspend point isn't just a scalar" scope boundary already
tracked for tuple yields (now fixed) and for
`bugs/CODEGEN_generator_function_Lib_ftplib.md`'s `mlsd` case, just for
a bare struct-pointer yield instead of a tuple.

Given that landing (1)+(2) alone — without also closing the yield-type
gap in (3) — would trade an honest compile-time refusal for a silent
wrong-value bug, this fix was NOT applied. No code change made; no gate
run.

Independently, `_iter_member_by_def_`'s `yield from sorted(cls.
_iter_member_by_value_(value), key=lambda m: m._sort_order_)` would
ALSO still be refused even if all of the above were fixed — the
`key=lambda ...` argument hits the separate, already-documented
`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md` refusal
(a `LambdaExpr` used as a call argument inside a generator body). So
even a fully-correct fix for `_iter_member_by_value_` would not, by
itself, make `enum.py` build — `_iter_member_by_def_` needs that
separate, already out-of-scope gap closed too.

## Status (updated 2026-08-09, re-verified — consolidated)

**STILL FAILING**, re-confirmed against current master with
`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/enum.py`
(this file as the build root):

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/enum.py
[gimple_codegen] generator method Flag.'_iter_member_by_value_' not eligible for C++ coroutine path, falling back to honest refusal: _iter_member_by_value_: a @classmethod generator that references `cls` in its body is not supported (no class-level attribute/method access exists yet for compiled generators)
[gimple_codegen] generator method Flag.'_iter_member_by_def_' not eligible for C++ coroutine path, falling back to honest refusal: _iter_member_by_def_: a @classmethod generator that references `cls` in its body is not supported (no class-level attribute/method access exists yet for compiled generators)
[gimple_codegen] generator method IntFlag.'_iter_member_by_value_' not eligible for C++ coroutine path, falling back to honest refusal: _iter_member_by_value_: a @classmethod generator that references `cls` in its body is not supported (no class-level attribute/method access exists yet for compiled generators)
[gimple_codegen] generator method IntFlag.'_iter_member_by_def_' not eligible for C++ coroutine path, falling back to honest refusal: _iter_member_by_def_: a @classmethod generator that references `cls` in its body is not supported (no class-level attribute/method access exists yet for compiled generators)
Error building: cannot compile module: function(s) _iter_member_by_def_, _iter_member_by_value_ (generator function(s), contain a `yield`/`yield from`) — ... falling back to interpreting this module from source instead
```

**Classification: expected, correct refusal — the classmethod/`cls`
generator eligibility gate (`bugs/hard/CODEGEN_generator_classmethod_
first_param_must_be_self.md`, task #147-adjacent, already fixed and
verified working as designed) doing its job.** `Flag._iter_member_by_
value_`/`_iter_member_by_def_` (enum.py lines 1428/1438) are
`@classmethod` generators whose bodies genuinely reference `cls`
(`cls._flag_mask_`, `cls._iter_member_by_value_(value)`,
`cls._value2member_map_.get(val)`) — this codegen has no class-level
attribute/method-access story for compiled generator coroutines, so the
eligibility check correctly refuses rather than emit invalid C++
(member access on a scalar `int64_t cls` placeholder). `IntFlag`
inherits both methods unchanged from `Flag` (`class IntFlag(int,
ReprEnum, Flag, ...)`, no override) — the codegen flattens inherited
methods per concrete struct, so `IntFlag` gets its own independently-
refused copy of each, which is why 4 refusal lines appear for what is
really 2 distinct method BODIES.

`_iter_member_by_def_`'s `yield from sorted(cls._iter_member_by_value_
(value), key=lambda m: m._sort_order_)` is ALSO independently refusable
on `bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`'s grounds
(a `LambdaExpr` used as a call argument inside a generator body) — a
second, independent reason this exact generator would be refused even
if class-level `cls` access were supported. Not cross-verified which
check fires first in the current eligibility-scan order; moot, since
both are out-of-scope structural gaps.

Not fixed here — both are documented, already-assessed, feature-sized
coroutine-codegen scope boundaries (class-level attribute/method access
from a compiled generator; lambda-as-call-argument inside a generator
body), not narrow bugs, and per this session's scope neither is to be
attempted.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/enum.py
