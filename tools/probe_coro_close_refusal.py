#!/usr/bin/env python3
"""Trace every read of one module global through `_lower_IdentExpr`, with the
generator-api state the `.close()` / `next()` refusal depends on.

    python3 tools/probe_coro_close_refusal.py ENTRY.py [--name _coro] [--do-imports]

Used by CODEGEN_the_collections_abc_coro_close_idiom_refuses_only_in_a_full_closure:
the refusal `generator .close() on a value with no known generator API` is
decided by which table holds the name at the moment of the read. This prints,
for each read of NAME, one line per table so the first read that loses the
api names the arm that lost it. The compile itself is unchanged: the wrapper
only observes, and returns exactly what `_lower_IdentExpr` returned.

Output goes to stderr, one `PROBE` line per read, then the compile verdict:

    PROBE module=<gen.module_name> name=_coro ctype=<ctype> temp=<temp>
          api_table=<bool> poisoned=<bool> accessor=<bool> captured=<bool>
          narrowed=<bool> boxed=<bool> toplevel_gen=<bool> async_api=<bool>
          unsupported=<bool> carried=<base or None>
    COMPILE: OK  |  COMPILE: REFUSED <message>

Run it under the memory cap, one row at a time (a row closure is heavy):

    python3 tools/memslot.py --gb 8 --label probe-coro -- \\
        python3 tools/probe_coro_close_refusal.py ENTRY.py --do-imports
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gimple_codegen
from mojo.backend_gimple import emit_exprs


def _base_of(api):
    """The C symbol family of a recorded generator api, for the log only."""
    if isinstance(api, dict):
        return api.get('base')
    return getattr(api, 'base', api)


def _install(name: str) -> None:
    real = emit_exprs._lower_IdentExpr

    def probed(gen, node):
        ctype, temp = real(gen, node)
        if node.name == name:
            api = gen._generator_var_api.get(temp)
            print(
                f"PROBE module={gen.module_name!r} name={name} "
                f"ctype={ctype} temp={temp} "
                f"api_table={name in gen._global_generator_api} "
                f"poisoned={name in gen._global_generator_api_poisoned} "
                f"accessor={name in gen._imported_global_accessors} "
                f"captured={name in gen._captures} "
                f"narrowed={f'i:{name}' in gen._narrowed_exprs} "
                f"boxed={name in gen._boxed_mut_locals} "
                f"toplevel_gen={bool(gen._in_toplevel_gen)} "
                f"async_api={name in gen._async_api} "
                f"unsupported={name in gen._unsupported_generator_names} "
                f"carried={_base_of(api)}",
                file=sys.stderr, flush=True)
        return ctype, temp

    emit_exprs._lower_IdentExpr = probed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('entry')
    ap.add_argument('--name', default='_coro')
    ap.add_argument('--do-imports', action='store_true')
    args = ap.parse_args()

    with open(args.entry) as f:
        src = f.read()
    _install(args.name)
    try:
        gimple_codegen.compile_to_gimple_with_cpp(
            src, do_imports=args.do_imports,
            filename=os.path.abspath(args.entry))
    except Exception as e:  # the refusal is a raised error; report it verbatim
        print(f"COMPILE: REFUSED {e}", file=sys.stderr)
        return 1
    print("COMPILE: OK", file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
