# TEST: test_selfhost_struct_layout_map_regression.py is red on master (ComptimeVarStmt.comptime_params)

**What I ran**, from a clean worktree at master `c04f9f1a5` with no local
changes to `fire_compiler.py` or `module_gen.py`:

    python3 tools/memslot.py --gb 8 --label layout -- \
        python3 test_selfhost_struct_layout_map_regression.py
    -> exit 1, AssertionError: field(s) declared in fire_compiler.py but
       absent from mojo/backend_gimple/module_gen.py's hardcoded
       struct_field_types map — the emitted struct will have no such member
       and the self-host closure will not compile:
       ComptimeVarStmt: ['comptime_params']

**What I expected.** The test to pass, i.e. every class-level annotation in
`fire_compiler.py` to have a row in `module_gen.py`'s hardcoded
`struct_field_types` map, so the self-host closure's emitted C struct defines
the member. That is exactly the defect class the test's docstring records
(`Parser.errors`, `ImportStmt.lazy`, `StructDef.presence_fields`, …).

**What I saw.** `ComptimeVarStmt.comptime_params` (declared at
`fire_compiler.py:1099-1114`, the generic-comptime-alias bracket parameter
block) has no row in the map at `module_gen.py:14483`. No code reads the
member today (`grep -rn 'comptime_params' mojo/` finds only `FunctionDef`'s
same-named field, which does have a row), which is why no build has failed on
it yet — but the field is declared, the parser records it, and the class's own
docstring names `mojo/middle/comptime.py`'s `_comptime_alias_template` /
`_eval_alias_application` as its consumers. The first one of those to read it
in the compiled compiler gets gcc's `'struct ComptimeVarStmt' has no member
named 'comptime_params'`, i.e. a hard failure of `bootstrap-stage2-cc` — the
producer the whole `bootstrap-stage2-dumps` fanout is waiting on.

**Why it has not been noticed.** The test is registered by NO suite job:
`grep -rn test_selfhost_struct_layout_map_regression tools/suite.py` is empty,
so `make check`/`make gate` have never run it. Its three cases are cheap
(pure source-text readers; no compile), so this is a registration hole, not a
cost decision.

**Exact next step.** Add `'comptime_params': 'MojoList *'` to
`module_gen.py`'s `self.struct_field_types['ComptimeVarStmt']` row (the
container spelling is the one the parser's `ListExpr` value gets; verify
against `struct_boxed_fields` — `value` is boxed, the parameter block is a
list), run the test, then register it in `tools/suite.py` with `mem='tiny'`
(and in a bucket, since a registered test in no bucket is the same hole), and
delete this doc in that commit. Until the job is registered and green, a
missing row for the next AST field is again invisible to the gate.
