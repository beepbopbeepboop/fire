# GIR: the self-hosted compiler's output diverges from the reference's

Found 2026-11-25 while making `selfhost` (the gate job) green. The binary now builds, links,
starts and exits 0 on a program, and writes valid UTF-8; its `.ci` is still not the reference's.
Every item below was measured with `tools/selfhost_probe.py` (build once, probe in seconds, diff each
probe against `python3 fire.py --dump-full`) and `lldb`.

## Measured divergences

2026-11-25, first measurement (binary at `51a54776f`): 36 diff lines on `x = 1; print(x)`, 51 on `def g(a): return a + 1`,
178 on the f-string program. ROOT CAUSE of most of it, found and fixed the same day (`codegen: mod.Class.method(args)
through a module alias`, two commits): `gimple_ctypes.TypeLattice.<predicate>(x)` (about 2,600 call sites after the stage-4
codemod) was lowered to the unknown-method stub, so every type predicate was false in the compiled compiler. The closure's
stubbed calls went from 2,941 to 611.

Second measurement (binary built after that fix; probes `/tmp/shb/p/*.mojo`, `tools/selfhost_probe.py probe -v`): `x = 1;
print(x)` differs in 11 lines (the two-space indent of `mojo_print`/`mojo_cstr_or_int_release` statements, below),
`def g(a): return a + 1` in 45, the f-string program in 135. What is left:
1. A function header and prototype with BLANK parameter types and a zero overload hash: `int64_t g_000000 ( a)` where the reference
   has `int64_t g_9f63a2 (int64_t a)`; the call site names the same `g_000000 (3)`. `_signature_ctypes` returns a one-element list
   holding `''` (lldb: `mojo_list_get_str(result, 0)` is `""`), `_param_ctype` itself answers `int64_t` when asked directly, and
   `GimpleGen__param_ctype` is never called, so the empty entry comes from another branch of `_signature_ctypes`
   (`funcs_shared.py` ~152-300; candidates: the `_msig_ct` per-method table, `c_client_callable_ctype(ct)` whose `isinstance(ct, str)`
   is `mojo_isinstance_p (ct, 4)` on an unannotated word).
2. An integer literal operand of a binary operation is empty: `_t1 = ;` where the reference has `_t1 = 1LL;`, and the `a + _t1`
   statement disappears (`def g(a): return a + 1`).
3. Statements built from `_rt_void` / `_void_call` are `'opaque'` (printed at column 0, no `#line`) instead of modelled calls
   with indent 2: `mojo_print (_t3);` at column 0.
4. `print(<int word>)` takes the printf arm in some programs (`malloc (256); sprintf (_t3, "%d", ...)` and an extra `"%d"` string
   literal): a decision that reads a table the binary leaves empty.
5. 611 stubbed calls remain in the closure (`grep stubbed selfhost.ci`): most are real externals (`sys.exit`, `tempfile`,
   `importlib`, `os.makedirs`), and a group is calls into compiler modules this compile had not finished
   (`monomorphize.mangle` x26, `elaborate.extract_struct_source` x27, `module_loader.module_name_for_path` x11,
   `gimple_ctypes.CallExpr(...)` constructor x16): the same order dependence inside the import cycle.

## Method (so the next round does not rediscover it)

    python3 tools/memcap.py --limit-gb 24 -- python3 tools/selfhost_probe.py build /tmp/shb   # 15 min
    python3 tools/selfhost_probe.py probe /tmp/shb p1.mojo p2.mojo -v                         # seconds
    # a crash needs ASLR ON (lldb defaults it off and hides ASLR-only crashes):
    lldb -b -o 'settings set target.disable-aslr false' -o 'run --dump-full p.mojo' -o 'bt 12' /tmp/shb/mojo_selfhost
    # an AttributeError: -o 'breakpoint set -n mojo_raise_attribute_error'
    # a wrong string: break on the producer, `finish`, then `memory read -s1 -c40 -fc $x0`

Classes of defect found this way, in the order they were peeled (each is a landed fix with a pin test;
the pattern is what to look for in the next one):
- an unannotated parameter/field read as `.field` is a dynamic getattr on a boxed word
  (`sdef.presence_fields`, `ctx.var_types`, `getattr(gen, name, '')`);
- field-usage struct inference picks the only struct with that field (`node.args` -> `Ex`);
- a call path that skips the tagged-parameter convention (`= None` parameters, forwarding wrappers);
- `dict.get(k)` with no default on an untyped value domain is the BOXED read;
- an annotated `self.f: T = call()` field typed from the value (erased) instead of the annotation;
- order dependence inside the import cycle (presence bits, parameter hashes).

## Next step (updated)

Item 1 first (every function is wrong until it is fixed), then 2 and 3.
(Old text:) Reduce item 3 first (it makes every function body empty): probe `def g(a): return a` /
`def g(a): return 1`, find which return expression kinds are lost, then break in `gen_func` (lldb on
`mojo_backend_gimple_emit_funcs_gen_func_*`) and read the `ret_type` and the lowered return value.
Then item 1. `make bootstrap`'s `bootstrap-verify` is the acceptance (stage1 == stage2 == stage3 byte for
byte); `test_selfhost.py` only requires exit 0, valid text and no `unavailable in compiled mode`.
