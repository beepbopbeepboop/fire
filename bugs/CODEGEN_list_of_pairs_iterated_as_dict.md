# CODEGEN: `list(x)` of an erased tuple element is an empty list, or iterates a list as a dict

`mojo/backend_gimple/module_gen.py` (two sites, ~2249 and ~4655):

    for _mangled, (_rc, _pcs, _dflts) in _gg_sigs.items():
        self.func_param_types[_mangled] = list(_pcs)        # compiles to mojo_list_new() + "TODO: comprehension over int64_t"
        if _dflts:
            self._func_param_defaults[_mangled] = list(_dflts)   # compiles to (MojoDict *)_dflts; mojo_dict_iter_new(...)

`_pcs` / `_dflts` come out of a tuple unpack with erased (int64_t) types. `list(_pcs)` silently yields `[]`
(the frozen GimpleGen signature table is never applied self-hosted), and `list(_dflts)` walks a LIST of
(name, default) pairs as if it were a dict. The second one wrote past a malloc block in
`mojo_dict_order_indices` (`tmp` sized from `d->used`, filled from the slot table) and corrupted the allocator
free list; that runtime over-write is FIXED (sized from the slot table, padded to `used`), the type confusion
itself is NOT: even an annotated local (`_pcs_l: list = _pcs`) still lowers `list(_pcs_l)` to the TODO stub.

Fixing it changes the compiled compiler's output for every self-compile (func_param_types would start being
populated), so it needs the gate and probably fixes the native-vs-python `--dump-full` divergence.
Next step: lower `list(<list-typed expr>)` as `mojo_list_copy` whatever the provenance of the type, and make
`list(<dict>)` / `list(<list>)` dispatch on the runtime registry when the static type is unknown.
