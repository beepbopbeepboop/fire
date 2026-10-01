# CODEGEN: `./mojoc fire.py --dump-full` now runs to the end and prints "Error generating --dump-full: AttributeError: platform"

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
