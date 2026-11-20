#!/usr/bin/env python3
"""Pin: a struct whose NAME collides with a C system struct compiles.

`bugs/stdlib/STDLIB_system_struct_name_helpers_need_the_struct_body.md`. The
typedef pass emits only `typedef struct timespec timespec;` for a name in
`_SYSTEM_STRUCT_NAMES` (the system header owns the layout), so the per-struct
helpers must not read Mojo-level fields or the `__mojo_type_id` tag word --
they do not exist in that layout. Before the fix `_init_timespec` wrote
`_p->__mojo_type_id` and gcc rejected it:

    p.mojo: In function '_init_timespec':
    p.mojo:506:5: error: 'timespec' has no member named '__mojo_type_id'

Run: python3 test_system_struct_helpers_compile.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_stdlib_dylib
import compile_stdlib

# The doc's exact repro. `time_t` is a comptime alias so the field type is not
# the point; the struct NAME is.
SRC = '''\
comptime time_t = Int64

@fieldwise_init
struct timespec(TrivialRegisterPassable, Writable):
    var tv_sec: time_t
    var tv_nsec: Int64


def make_ts(sec: Int64) -> timespec:
    return timespec(sec, 0)
'''


def main():
    c_src = build_stdlib_dylib.compile_module_to_c(
        SRC, 'p.mojo', 'p', linkable=False)
    # The whole point: no helper may reference a member the typedef pass did
    # not declare. `_init_<name>` must not write the tag word for these.
    rc, err = compile_stdlib._gcc_syntax_cached(c_src)
    assert rc == 0, (
        'a system-struct collision no longer compiles:\n' + (err or '')[:2000])
    assert 'has no member named' not in (err or ''), (err or '')[:2000]
    # Guard against a vacuous pass: the repro really does declare the
    # collision, so the typedef is present and the init helper is emitted.
    assert 'typedef struct timespec timespec;' in c_src, c_src[:2000]
    assert 'static void _init_timespec' in c_src, c_src[:2000]
    print('PASS')


if __name__ == '__main__':
    main()
