"""Regression pin: "is this callee a runtime helper" is a table lookup, not a
`mojo_` prefix test.

The compiler's own modules live in the `mojo/` package, so their C symbols are
`mojo_middle_*`, `mojo_backend_gimple_*`, `mojo_tsolve_*`. `emit_infra` skipped
the `mojo_unbox_plain` of a may-box argument for every name starting `mojo_`
(runtime helpers are box-aware), so a `dict.get(k)` miss -- the shared None box
-- reached `presence_word_count (StructDef *)` as a pointer cast of the box, and
the self-hosted compiler crashed in `mojo_list_len` on its first compile
(address 0x74, only under ASLR).
"""
import sys

import mojo.middle.rt_call as rt_call


def main() -> int:
    bad = []
    for name in ('mojo_dict_get_boxed', 'mojo_list_len', 'mojo_unbox_plain'):
        if not rt_call.is_runtime_function(name):
            bad.append('%s should be a runtime function' % name)
    for name in ('mojo_middle_types_presence_word_count_b8e3da',
                 'mojo_backend_gimple_module_gen_gen_module_impl_7e9a9f',
                 'mojo_tsolve_solve_solve_1a2b3c', 'user_function'):
        if rt_call.is_runtime_function(name):
            bad.append('%s is a program function, not a runtime one' % name)
    src = open('mojo/backend_gimple/emit_infra.py').read()
    if "startswith(('mojo_'" in src:
        bad.append("emit_infra.py still tests the `mojo_` prefix")
    if bad:
        print('FAIL: ' + '; '.join(bad))
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
