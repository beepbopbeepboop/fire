# CODEGEN: `hasattr(obj, n)` is True for a field the compiler inferred from an assignment outside `__init__`

## Repro (2026-11-01, re-measured)

    class P:
        def __init__(self):
            self.a = 1

    def main():
        p = P()
        p.b = 5
        q = P()
        print(hasattr(q, 'b'))            # CPython: False   compiled: True
        print(getattr(q, 'b', 99))        # CPython: 99      compiled: 0
        print(hasattr(p, 'b'), getattr(p, 'b', 99))   # True 5 in both
    main()

Measured: `python3 .tmp/run_compiled.py` (compile via `test_gimple_runner.compile_mojo_to_gimple_exe`,
run, print stdout) gives `True / 0 / True 5`; CPython gives `False / 99 / True 5`. The interpreter
(`python3 fire.py run`) is already correct.

## Status (2026-11-01): ROOT CAUSE LOCATED, DESIGN DECIDED, NOT YET LANDED

No code change landed this round. The fix touches enough store sites that a partial landing would be
unsafe (see "Why not a partial fix" below), so this round's output is the implementation guide.

### Root cause (measured)

The field `b` is MINTED onto the struct definition, not onto the object:

- `mojo/backend_gimple/module_gen.py` `_scan_body_for_local_field_access` (def at ~7209, called at
  ~7349 for `stmts` and ~7351 for `imported_stmts`). Inside it, the phantom-field mint loop
  (~7288-7347) runs `self.struct_field_types[target_struct][fn] = _mft` (~7343) and
  `target_def.fields.append(VarDecl(name=fn, ...))` (~7344). `_assigned_member_ctypes` (~7265) is the
  `o.m = v` evidence that types the minted field. `p.b = 5` in `main` mints `b` onto every `P`.
- `mojo/backend_gimple/module_gen.py` ~7010-7057: the self-write pass (`_gmi_collect_self_assigns`
  called once per METHOD, not only `__init__`) also mints fields for `self.x = ...` in any method.
  A field first assigned in a non-`__init__` method is minted the same way.
- The `hasattr` lowering (`mojo/backend_gimple/emit_calls.py` ~3596-3630) is correct for what it is
  given: it probes `_mojo_dispatch_getattr` under `_mojo_getattr_nothrow` and answers
  `_mojo_getattr_missed == 0`. The generated `_mojo_getattr_P` (module_gen.py ~1980-2090: `get_lines`
  built from `struct_field_types`) has an unconditional `"b"` arm that returns `obj->b`. Nothing in
  that arm knows whether THIS object was ever assigned `b`. Same for the 3-arg `getattr` lowering
  (emit_calls.py ~3816-3860).

Because the mint is a whole-struct fact, it cannot be fixed per body: a second function that only
READS `q.b` also mints a read-only phantom `int` field (same loop, `_mft = 'int'`), so the struct
is changed for every instance regardless of which body saw the store.

### Decision: representation = a hidden per-struct presence bitmask, one bit per minted field

Options considered:

1. **dynattr route** (keep `p.b = 5` out of the struct, store via `mojo_setattr`). Rejected as the
   primary route: the mint is global across bodies, so it would need a whole-program pre-pass that
   decides every minted member's representation before any body is lowered, AND it drops the typed
   storage (`_mft`) that `o.x = "hello"; print(o.x)` depends on. Reads of an undeclared member would
   come back as a boxed int64 word, a broad change to the self-hosted compiler's own AST reads.
2. **Runtime side table keyed by object address** (like `_mojo_dynattr_objects`). Rejected: a freed
   object's address is reused, so a fresh instance can report a stale presence bit (a false True);
   and a by-value copy (`_mojo_dispatch_copy` memcpy, emit_methods forwarding copy) gets a different
   address and loses its presence.
3. **Hidden per-struct presence bitmask inside the C struct** (CHOSEN). `_init_<S>` already
   `memset`s the whole struct (module_gen.py ~16165), `calloc` zeroes heap slots (module_gen.py
   ~14868), and `_mojo_dispatch_copy` memcpys the whole struct (module_gen.py ~2359). So a bit is
   zero by default, and survives every copy. It keeps typed storage and every existing read
   unchanged.

Semantics to implement: a MINTED field (one not declared by an annotation, a class-body default, or
an `__init__` self-assignment) is PRESENCE-TRACKED. Its bit is set by every codegen store to it.
The generated `_mojo_getattr_<S>` arm for it answers "missed" when its bit is clear, and falls
through to `mojo_obj_getattr` (which raises AttributeError in non-nothrow mode, as CPython does).
Reads of a tracked field on an object whose bit is clear would still return the zero word through a
direct field read; that is a known separate gap (CPython raises), out of scope for this bug.

### Implementation plan (exact files, ordering)

Step A — tracked set (`mojo/backend_gimple/module_gen.py`):
  - Record each minted field: add `self._presence_fields: dict[struct -> ordered list of field
    names]`. Populate at (i) the scan mint ~7343, (ii) the self-write mint ~7055-7056, but ONLY when
    the minting method is not `__init__`. Ordering trap: `__init__` may be processed after another
    method that mints the same field. So compute tracked-ness after the mint passes: tracked =
    minted AND not assigned by `__init__`'s own self-assigns. Remove any name `__init__` assigns.
  - Assign each tracked field a bit index per struct (stable, sorted order).

Step B — struct layout (`module_gen.py` `_render_struct_typedef_body` ~1456): when a struct has
  tracked fields, emit `uint64_t __mojo_present[N];` with N = ceil(count/64). Do NOT add it to the
  `fields` dict or `struct_field_types` (it must not appear in `_mojo_fieldnames_`, repr, asdict,
  or the self-hosted field tables). Thread the word count through the 3 typedef emitters
  (module_gen.py ~14733, ~15664, ~16011, and the cpp preamble call that uses
  `_render_struct_typedef_body`). Check `tools/audit_selfhost_struct_fields.py` after.

Step C — set the bit at EVERY codegen store to a tracked field. Full inventory (measured):
  - `mojo/backend_gimple/emit_stmts.py` ~2050 (AssignStmt direct field write)
  - `emit_stmts.py` ~2636 (AugAssign field write)
  - `emit_stmts.py` ~3844 (MultiAssign target field write)
  - `emit_stmts.py` ~2276-2339 (field-by-field copy of a whole struct element, `addr->f = v->f`)
    — must ALSO copy the presence word(s), or the copied object reads as missing
  - `emit_methods.py` ~4190-4240 (`_emit_fw_copy`: field-wise forwarding copy) — same rule
  - `emit_calls.py` ~9857-9864 (constructor positional/kwarg field init) — tracked fields are not
    ctor args, but the copy loop above must be checked the same way
  - `mojo/backend_gimple/cpp_core.py` ~5800 and ~6371 (self field assign / augassign in the C++
    coroutine path) and ~4547 (class-attr init) — the compiled-generator path has its own emitter
  - the generated `_mojo_setattr_<S>` arm (module_gen.py ~2136-2143 `set_lines`): set the bit
  - `emit_stmts.py` ~1139 is a READ (`_is_some` side-band), not a store; no change
  - `emit_stmts.py` for-loop / with-target writes into `obj.field` (not yet enumerated; grep
    `target.member` in emit_loops.py and emit_stmts.py before landing)
  The bit set is `obj->__mojo_present[k/64] |= 1ULL << (k%64)`, emitted by one helper
  (`gen._emit_presence_set(struct, member, obj_c)`) so the 6+ sites share one rule.

Step D — read side (`module_gen.py` `get_lines` ~1980-2000, and `_mojo_getattr_<S>`): for a tracked
  field, the arm becomes `if (strcmp(attr,"b")==0) { if (!(obj->__mojo_present[k/64] >> (k%64) & 1))
  break/fall-through-to-miss; return ...; }`. The miss must set `_mojo_getattr_missed` under
  nothrow and otherwise fall to `mojo_obj_getattr`. Verify the fallthrough reaches
  `mojo_obj_getattr` (module_gen.py ~2375-2380 is `_mojo_dispatch_getattr`'s fallback).

Step E — `setattr`/`hasattr` consistency: `_mojo_dispatch_setattr` → `_mojo_setattr_<S>` is the
  dynamic store path (covered in C). Confirm `setattr(p,'b',v)` sets the bit.

Step F — the gate (integrator): this changes the generated C of every struct that has a minted field,
  including the self-hosted compiler's own structs. Expect byte-level changes in stage1/2/3 and the
  `stdlib-syntax` / `stdlib-dylib` skip counts. Per CLAUDE.md, run `make gate` and compare
  `skip <module>:` counts and `FAILED: N (E expected, U unexpected)` before/after.

### Tests (to add with the fix)

- `test_runtime_class_creation.py` CASES (CPython-diffed via `test_gimple_matches_cpython`), named
  `inferred_field_assigned_outside_init_is_absent_on_other_instances`: the repro above, plus
  (i) a method-assigned field (`def set(self): self.c = 1`) read by hasattr on an instance that
  never called `set`; (ii) a field set on one instance then copied by value (`_mojo_dispatch_copy`
  path) and hasattr on the copy; (iii) `setattr(p,'b',5)` then `hasattr(p,'b')`; (iv) a struct
  with >64 minted fields to exercise the multi-word bitmask.
- Quick check to run before landing: the repro via `.tmp/run_compiled.py` must print
  `False / 99 / True 5`, and the new CASES must FAIL before the fix (they do today: `True 0`).

### Why not a partial fix

Setting the bit at only some store sites would make `hasattr` return False for a field that really
was assigned through an uninstrumented path, which is a regression for every currently-working
`getattr(node, f, default)` on the compiler's own AST (the self-hosted compiler uses this
extensively). The bit must be set at ALL sites in Step C in the same commit.

### Round 2026-11-01 (b): re-measured, cross-unit constraint added to the plan

Re-measured on the current tree (`python3 tools/memslot.py --gb 8 --label repro -- python3 .tmp/repro.py`,
where `.tmp/repro.py` calls `test_gimple_runner.compile_mojo_to_gimple_exe` on the repro above and
prints the exe's stdout): `True / 0 / True 5`. Still open, matches the repro.

Store-site count, measured (`grep` over `mojo/backend_gimple/*.py`): about 20 emitter sites that write a
struct member through `_safe_field(...)` alone (cpp_core 4547/5800/6371/8449; emit_calls 2965/9960;
emit_exprs 2329/2706/2951/3075/3078; emit_methods 414/4198; emit_stmts 2059/2068/2292/2645/3853;
module_gen 1982/2136/16029/16047/16140/16143), plus raw `->{member}` spellings that do not pass through
`_safe_field`. Step C above must be re-enumerated against this list, not against the earlier 10-site list.

**New constraint the plan above does not yet state.** The mint writes into the SHARED `StructDef.fields`
(module_gen.py ~7344-7346) while `struct_field_types` is PER-GEN (comment at ~7000-7010: "the two tables are
per-gen while `StructDef.fields` is shared"). The struct typedef is emitted only by the owning TU, i.e. the
gen with `emit_struct_defs=True` (module_gen.py ~1549, emit_funcs.py ~3167/3427, emit_resolve.py ~731). Sibling
gens with `emit_struct_defs=False` compile member stores and reads against that same layout. So a presence
word whose bit index is decided per gen would disagree between TUs: a sibling sets bit `k` that the owner's
typedef does not have, which is an out-of-bounds write. Consequence for the design:

- The tracked set and each tracked field's bit index MUST be derived from one authority that every gen
  sees identically: the shared `StructDef` (e.g. a deterministic bit index per tracked field, stored on the
  `StructDef`, or recomputed from the sorted tracked names), NOT from a gen's `struct_field_types`.
- The presence word count must be included in EVERY typedef emission path that the owner and the siblings
  depend on: `_render_struct_typedef_body` callers at module_gen.py ~14672, ~17273, ~17371 (and the
  C++ preamble `_struct_typedef_texts` path). A typedef rendered without the word while a sibling writes it
  is the exact ABI break this section is about.
- The existing minted field `b` already has this exposure (the owner's layout can lack a sibling's mint).
  That is a pre-existing hazard and this change must not widen it: a presence word added to a struct makes
  the layout depend on the same shared authority, so it is no worse than the field itself.

**Next round, concretely (this is the implementation order; nothing below is landed yet):**

1. Establish the authority: add a `presence_fields` list to `StructDef` (set by the mint passes at
   module_gen.py ~7343 and ~7055, only for names not assigned in that struct's `__init__`), with a stable
   sorted order. Index = position in that list. Re-run the repro after this step alone: no output change
   expected (it is data only).
2. Layout: render `uint64_t __mojo_present[ceil(n/64)];` in `_render_struct_typedef_body` only when
   the StructDef has presence fields. Not in `fields`, not in `struct_field_types`. Byte-compare the generated C
   of a struct with no minted fields before/after (must be identical).
3. Stores: one helper `gen._emit_presence_set(struct, member, obj_c)`; call it at every site in the list
   above that writes a presence field, and in the field-wise copy sites (emit_stmts 2292, emit_methods
   4198) copy the presence words too. Do steps 2 and 3 in one commit: the read side may not land before
   every store site does.
4. Read side: `_mojo_getattr_<S>` arms for presence fields test the bit and fall through to
   `mojo_obj_getattr` on a clear bit (module_gen.py ~1980-2090). `_mojo_setattr_<S>` sets the bit.
5. Tests: `test_gimple_matches_cpython`-style cases in a file next to hasattr coverage (test_comptime_function_alias_r2.py
   and test_dataclasses_formal.py mention hasattr; the runtime-class-creation file is about `type()` and is
   the wrong home for this). Cases: the repro; a method-assigned field read on an instance that never
   called the method; a copy by value then hasattr on the copy; `setattr` then `hasattr`; more than 64 presence
   fields. Each must FAIL before step 4 and pass after.
6. Integrator gate (not run here): `stdlib-dylib` and `stdlib-syntax` skip / FAILED counts before vs after, and
   byte-compare of generated C for a struct with no presence fields.

### Round 2026-11-01 (c): store-site inventory, verified by reading the branches

Re-measured this round (`python3 tools/memslot.py --gb 8 --label repro -- python3 .tmp/repro.py`,
`.tmp/repro.py` calls `test_gimple_runner.compile_mojo_to_gimple_exe` on the repro): `True / 0 / True 5`.
Still open.

The grep inventory in the Decision/Plan above is NOT complete. A member store does not go through one
helper: each `MemberExpr`-target branch has its own dispatch ladder, and a presence set must be placed in
every branch that reaches a raw `->field = v` write. Verified this round, `mojo/backend_gimple/emit_stmts.py`:

- **Single-target AssignStmt**, `MemberExpr` branch at ~1880. Ladder, in order: `sys.argv` runtime store
  (~1889, not a field); `Cls.attr` / `cls.attr` run-time class table (~1897, not a field); opaque-receiver
  dynattr dispatch `_mojo_dispatch_setattr` (~2040-2060, a minted member on an opaque object goes here and
  its bit must be set by the dispatch, not by the field store); known-field typed store (~2064 onward,
  `field_type = known_fields.get(...)`). The nullable-receiver guard (`_nullable_ptrs`) sits before the raw
  store. The presence set goes at the end of the known-field store, after the nullable guard.
- **AugAssign**, `MemberExpr` branch at ~2592 (same `sys.argv` head, then the field read-modify-write).
  Presence set after the store. Note an AugAssign on a MINTED field reads an unset member first: CPython
  raises AttributeError there, the compiled path reads 0. That is the separate "read of an unset tracked
  field returns 0" gap already recorded under Related, and it is out of scope here.
- **MultiAssign / chained-assign** target loop, `MemberExpr` branch at ~3808. Same two sub-paths as
  single-target: `ot in ('int', 'int64_t', 'void *')` goes to `_mojo_dispatch_setattr` (~3815-3830); the
  raw path ends at ~3850-3880 with the `field_type = gen.struct_field_types.get(sn, {})` coercion and the
  nullable guard. Presence set on the raw path only; the dispatch path must set it inside the generated `_mojo_setattr_<S>`
arm (Plan step 4). That arm does not set it today.
- **Dynattr fallback** `gen._emit_dynattr_setattr_dispatch(target.member, ...)` (emit_stmts ~3850-3852) is
  called from the multi-target loop. It must set the bit exactly as `_mojo_setattr_<S>` does.
- **Field-wise struct copy** (`addr->f = v->f` per field, ~2276-2339 per the earlier grep): copies the
  presence words too. Not yet re-read this round.
- **Not yet re-read this round, must be before landing:** `emit_stmts.py` for-loop and with-target member
  writes (`emit_loops.py`); `emit_methods.py` `_emit_fw_copy` (~4190-4240); `emit_calls.py` constructor
  field init (~9857-9885, and the `_safe_coerce_emit` sites at 9878/9885); `cpp_core.py` self-field assign
  (5800), augassign (6371), class-attr init (4547); `module_gen.py` class-attr cell writes (16203-16206).
  The C++ coroutine emitter in `cpp_core.py` is a separate implementation of the same stores, so each of its
  sites needs the same set.

Why this round still lands no code: the presence set is a store-site-complete invariant. Setting it at
some of these branches and not others makes `hasattr`/`getattr(..., default)` return False for a field
that really was assigned through the missed branch. The compiler's own AST code relies on that
`getattr` pattern (see Decision), so a partial landing is a silent regression that only the integrator's
`stdlib-dylib` / `stdlib-syntax` gate would see. The next round should land the whole store set and the
read side together, in one commit, per Plan steps 1-5.

### Related, not this bug

- A read of a tracked field on an object that never had it set returns 0 instead of raising.
  Separate (getattr without default on an unset attribute); it falls out of Step D for `getattr`
  (no default) but a direct `p.b` read is untouched.
- The dynattr storage (`mojo_setattr`) and its per-object presence are correct but are not reached
  for these fields today, because the mint makes them struct fields first.
