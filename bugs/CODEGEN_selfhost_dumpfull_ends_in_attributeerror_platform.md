# CODEGEN: `./mojoc fire.py --dump-full` now runs to the end and prints "Error generating --dump-full: AttributeError: platform"

## Status: the `AttributeError: platform` cause is FIXED and verified at minimal
## scale; the end-to-end `--dump-full` run is NOT re-verified, and two other
## symptoms in this file are untouched

### What was fixed

`sys.platform` was reachable only as a **comptime constant in a condition**.
`mojo/middle/comptime.py`'s `eval_const` folds the `sys.platform` MemberExpr,
which is the whole reason `if sys.platform == 'win32': def f(): ...` works.
Read as a VALUE there was no lowering for it at all, so the read fell to
`_lower_MemberExpr`'s generic dynamic-getattr dispatch — and a bare module
marker is `obj = NULL` there, so it raised `AttributeError: platform` and
exited 1.

That is this file's subject directly, not a related symptom:
`comptime.py`'s own fallback is `platform = sys.platform` (a plain value read,
in the `if platform is None` branch), `comptime.py` is inside the closure being
compiled, and its docstring already records having been bitten by this — it
reads

> That fallback is a PLAIN `import sys`, and the "plain" is load-bearing: it
> was once `import sys as _sys`, and the self-hosted binary raised
> `AttributeError: platform` on it.

so the line had been worked around rather than fixed, and the workaround was
one that itself reads the missing attribute.

Second, independent defect found while reproducing it, and the reason a bare
`sys.platform` repro was not the whole story: **every module-attribute
lowering was keyed on the local binding, not the module.** `import os as _o`
binds `_o`, and all nine module-attribute cases compare against the canonical
name, so an aliased import missed every one of them and landed in the same
`obj = NULL` dispatch. Measured on the whole-program path:

| | before | after |
|---|---|---|
| `print(sys.platform)` | `AttributeError: platform`, exit 1 | matches CPython |
| `import sys as _s; print(_s.platform)` | `AttributeError: platform`, exit 1 | matches CPython |
| `import os as _o; print(_o.sep)` | `AttributeError: sep`, exit 1 | matches CPython |
| `import signal as _g; print(_g.SIGTERM > 0)` | `AttributeError: SIGTERM`, exit 1 | matches CPython |

An unaliased `os.sep` always worked, which is what let this read as a bug about
aliases rather than about modules.

Both are fixed in `mojo/backend_gimple/emit_exprs.py::_lower_MemberExpr`: the
canonical name is now resolved through `imported_symbols` (a SEPARATE local,
because the struct/class/`var_types` branches further down want the local
binding and would fire on a name they know nothing about), and `sys.platform`
is emitted as the same compile-time constant its own folding uses.

Pinned by `test_gimple_runner.py::gimple_module_attribute_value_and_alias`
(each case bare AND aliased, plus both `sys.platform` condition forms to keep
the fold intact). It fails at the parent commit. Note it lives in
`test_gimple_runner.py` rather than `test_link_mode.py` because unlike the
polymorphic-parameter bug this reproduces on the single-translation-unit path
too — measured, both ways.

### What is NOT re-verified, and why

`./mojoc fire.py --dump-full` was not run. That needs a self-host build
(`python3 fire.py build fire.py`) and 12-31 GB, and is not available to the
session that made this change. So the claim is "the identified cause is fixed
and verified at minimal scale", NOT "`--dump-full` now succeeds". Those are
different claims and only the first is established.

### What is untouched

Both of these are separate and still open, and neither is the subject of this
file:

- `# ERROR: compiling imported module 'module_loader' ... '_mojo_type' is
  ambiguous` — `CODEGEN_bootstrap_resource_blowup.md`, "Native re-export
  failure investigation".
- the `_default_expr_to_pair: unavailable in compiled mode` stubs.

### Next step

1. Rebuild `mojoc` and run `./mojoc fire.py --dump-full` to find out which
   symptom the `AttributeError` was masking. The other two entries above are
   both still live, so it should still fail — on a different message — and
   that message is the next thing to look at. `mojoc`'s Makefile rule lists
   only `fire.py` plus the runtime files as prerequisites, not its real
   transitive closure, so `rm -f mojoc && make mojoc` rather than `make mojoc`
   alone (this has bitten before; see
   `CODEGEN_selfhost_actual_types_identifier_field_key.md`'s closing note).
2. Once it does produce a `fire.ci`, this file's subject is done and what
   remains belongs to the two entries above.

---

## Original report (2026-09-30, unedited)

After the 2026-09-30 memory work the self-hosted binary no longer crashes on fire.py (it used to SIGSEGV at 34-47 GB);
it runs ~60 s, peaks at 12.2 GB, exits 0, writes NO fire.ci and ends with
`Error generating --dump-full: AttributeError: platform` (a `sys.platform` read in compiled mode). It also prints
`# ERROR: compiling imported module 'module_loader' ... '_mojo_type' is ambiguous` (known: CODEGEN_bootstrap_resource_blowup.md,
"Native re-export failure investigation") and many `_default_expr_to_pair: unavailable in compiled mode` stubs.
Consequences: native-dumpfull / bootstrap-stage2-dumps will still fail, now on a missing artifact rather than a crash;
the `expect=` markers stay correct but their reason text is stale. Crashes removed on the way, all self-hosted-only:
`mojo_dict_order_indices` heap overflow (list iterated as a dict, see CODEGEN_list_of_pairs_iterated_as_dict.md);
`gen._bool_valued` NULL set (`hasattr` true self-hosted, lazy init never ran: now declared in GimpleGen.__init__);
ownership_destruct's nested `_arg_is_safe` closure (captured-variable env read in a different order than built) and its
`_m is not None and _m.params and ...` and-chain (feeds the bool 1 to `mojo_list_len`, the same class as emit_infra
_reset_func in e7fc3ec). Other `and`/`or` chains mixing a bool and a list operand, and nested closures capturing several
variables, are the likely next ones.
