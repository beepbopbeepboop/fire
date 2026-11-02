# CODEGEN: an iterated parameter passed a list AND a str segfaults

Found 2026-11-01 while fixing the three red test_gimple.py cases (the
str-beside-list call-site fix, module_gen.py `_param_noncontainer_obs`).

## Repro (compiled path, exit -11, stdout cut short; CPython runs fine)

    def each(xs):
        for x in xs:
            print(x)
    each([4, 5])
    each("de")

Expected (CPython): `4`, `5`, `d`, `e`. Compiled: `4`, `5`, then SIGSEGV.

## What the generated C shows

`each_<hash>` is emitted as `void each_<hash> (MojoList * xs)`, and the
`each("de")` call site is `each_<hash> (_t7)` with `_t7` a `char *`: a str
passed where a `MojoList *` is declared. The loop then calls
`mojo_list_len(xs)` / `mojo_list_get_int(xs, i)` on the string's bytes.

## Why it is not the same fix as the print case

The print-only shape (`def show(x): print(x)`) is fixed: `show` is typed by
the call-site contract, and `_param_noncontainer_obs` (module_gen.py) makes a
mixed slot an `int64_t` box. Here the parameter's type is set earlier, by
`_infer_param_types` from the USE (iteration => `MojoList *`). Two places
still reach that guess unchallenged:

- `_gmi_apply_call_site_param_evidence` (module_gen.py ~223) only acts on
  UNANIMOUS literal evidence, so `{MojoList *, char *}` is declined and the
  usage guess stands.
- `_reconcile_param_container_kinds` / the scalar pass (`_has_cs` branch,
  ~11000) only overrides a `MojoList *` guess when every observer is `char *`.
  A mixed `{char *, container}` observation is left at the guess.

## Next step

1. Decide the representation for an iterated parameter whose call sites
   disagree on container kind. Options: (a) the `int64_t` box, with the
   for-loop lowered through a runtime kind dispatch (`mojo_cstr_or_int_*`-style,
   or the `_tagged_dyn_` machinery); (b) an honest refusal
   (`_UnsupportedGeneratorShape`-style, interpreter fallback). (b) is the
   sound minimum; (a) is the program this compiler should compile.
2. Whichever is chosen, a `for` over a boxed parameter must not be lowered as
   `mojo_list_len` on the box. Check the `for`-loop emitter
   (mojo/backend_gimple/emit_loops.py) for the lowering of an `int64_t`-typed
   iterable first.
3. Test: the repro above, as a `test_gimple.py` case through `_compiled_stdout`
   on single-TU and link-mode, next to
   `test_a_str_call_beside_a_list_call_does_not_make_the_parameter_a_list`.

## Status (2026-11-01): partial fix — the silent SIGSEGV is now a loud refusal

Landed (`mojo/backend_gimple/module_gen.py`, `_refuse_mixed_container_params`,
after `_propagate_forwarded_container_kinds`): a parameter that has BOTH a
container observation and a non-container observation (`_param_noncontainer_obs`),
and whose final inferred type is `MojoList *` / `MojoDict *` / `MojoSet *`,
raises `RuntimeError` at compile time instead of emitting a binary that casts
the str to a list header. Narrow on purpose: the print-only mix (no container
guess) keeps its `int64_t` box and is not refused.

Verified: the repro's `_run_pipeline` now raises (it returned C before);
`python3 fire.py <repro>` prints `4 5 d e` via the interpreter fallback,
matching CPython. Regression test:
`test_an_iterated_parameter_passed_a_list_and_a_str_refuses_to_compile`
in `test_gimple.py`.

Still open (the actual compile of this program): step 1(a) — a representation
that serves both kinds. The `int64_t` box cannot tell `MojoList *` from
`char *` (`mojo_cstr_or_int_str` only separates str from int), so (a) needs
either a container kind tag carried in the box, or per-kind specialization of
the function (one clone per call-site kind). Step 2 (the `for` lowering of an
`int64_t` iterable) is not needed while the refusal holds, and becomes
relevant only once (a) lands.
