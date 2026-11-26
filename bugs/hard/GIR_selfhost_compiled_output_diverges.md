# GIR: the self-hosted compiler's output diverges from the reference's

Found 2026-11-25 while making `selfhost` (the gate job) green. The binary now builds, links,
starts and exits 0 on a program, and writes valid UTF-8; its `.ci` is still not the reference's.
Every item below was measured with `tools/selfhost_probe.py` (build once, probe in seconds, diff each
probe against `python3 fire.py --dump-full`) and `lldb`.

## Measured divergences (HEAD after `annotated self-field`, probes in `test_selfhost.py` terms)

Probe `x = 1` / `print(x)` (TWO_LINE), 36 diff lines against the reference:
1. `print(<int word>)` takes a different arm: the reference writes
   `_t3 = mojo_cstr_or_int_str (_t4); mojo_print (_t3); mojo_cstr_or_int_release (_t5, _t3);`
   and the self-hosted binary writes `_t4 = malloc (256); _t3 = (char *) _t4; sprintf (_t3, _t5, _t2);
   mojo_print (_t3); free (_t3);` with an extra `"0"`-format string literal (`_slit_10000 = "0"`).
   The temps' types differ too (`void * _t4` where the reference has `int64_t`). A decision that reads
   a table the binary leaves empty or differently typed picks the printf arm.
2. The statement lines after it are not `#line`-stamped (`mojo_print (_t6);` at column 0): the
   `_opaque` statements printed by the printf arm carry their own text, and the `#line` stamp is
   missing there.

Probe `def g(a): return a + 1` / `print(g(3))`, 51 diff lines:
3. `g` is emitted with NO return type (`" g_9f63a2 (int64_t a)"`) and the body is `return ;` instead of
   `_t1 = 1LL; _t2 = a + _t1; return _t2;`: the function's return type and its `return` value are
   both the empty string in the binary. Candidates: `_record_home_def_return_type` /
   `_early_return_decision` (`getattr(gen, '_tsolve', None)` and `dict.get` on the frozen table are
   erased words in the compiled path), or `_infer_return_type`'s result for a BinaryOp.

Probe CALL_PROGRAM (`f"x={a} y={b + 1}"`), 178 diff lines: the same two, plus the f-string pieces.

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

## Next step

Reduce item 3 first (it makes every function body empty): probe `def g(a): return a` /
`def g(a): return 1`, find which return expression kinds are lost, then break in `gen_func` (lldb on
`mojo_backend_gimple_emit_funcs_gen_func_*`) and read the `ret_type` and the lowered return value.
Then item 1. `make bootstrap`'s `bootstrap-verify` is the acceptance (stage1 == stage2 == stage3 byte for
byte); `test_selfhost.py` only requires exit 0, valid text and no `unavailable in compiled mode`.
