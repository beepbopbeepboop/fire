"""Compatibility shim - implementation moved to `mojo.backend_gimple.emit_loops`.

`import gimple_gen_loops` and `from gimple_gen_loops import ...` keep working.
Prefer `mojo.backend_gimple.emit_loops` in new code.
"""

# Re-export implementation from mojo.backend_gimple.emit_loops (self-hosted globals() is a weak stub).
from mojo.backend_gimple.emit_loops import *  # noqa: F401,F403
from mojo.backend_gimple.emit_loops import (
    _as_str, _emit_generator_pending_exc_check, _emit_generator_tuple_unpack, _emit_unsupported_iter, _gen_for_bytes, _gen_for_cstr,
    _gen_for_dict, _gen_for_enumerate, _gen_for_enumerate_generator, _gen_for_enumerate_str, _gen_for_generator_iter, _gen_for_iter,
    _gen_for_list, _gen_for_list_iter_cursor, _gen_for_memoryview, _gen_for_range, _gen_for_regex_iter, _gen_for_set,
    _gen_for_str, _gen_for_struct_iter, _gen_for_zip, _gen_for_zip_longest, _gen_lifted_closure, _get_actual_type,
    _gfd_flatten_target, _gfl_declare_target_name, _lower_re_sub_callback, _pair_key, _re_sub_repl_is_callback, _try_const_fold_int,
    _try_const_fold_str, _tuple_elem_value, _tuple_unpack_slot_elems, _zip_bind_slot
)
