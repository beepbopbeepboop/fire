#!/usr/bin/env python3
"""Static audit for constructs that make the SELF-HOSTED compiler's output
depend on heap addresses.

Every pattern here is one this project has already been bitten by. They are
all fine under CPython — which is why `python3 fire.py --dump` is
byte-reproducible while the compiled compiler was not — and all wrong once
self-hosted, because the backend erases the values involved to int64_t and
the runtime then hashes/orders/compares them as raw pointers.

Patterns, worst first:

  TUPLE-KEY     `d[(a, b)]`, `.get((a, b))`, `(a, b) in d`, `dict[tuple, ...]`
                A tuple lowers to a MojoList; the dict keys on its ADDRESS.
                Lookups miss, and can spuriously HIT on a reused address.
                Fix: a composite string key (`_sms_key`).

  TUPLE-IN      `<tuple> not in <list of tuples>` — compares handles, never
                contents, so the guard never fires.
                Fix: compare a composite string, or field-by-field.

  UNPACK        `for a, b in <container>` — boxes EVERY slot to int64_t, so
                `a == 'literal'` compares a pointer against a string.
                Fix: index the tuple and recover with _as_str/_as_int.

  GENEXPR       `any(... for ...)` / `all(... for ...)` — a bare generator
                expression's body has appended nothing on the compiled path.
                Fix: an explicit loop.

  SORT          `sorted(<a list>)` whose element type the backend may not
                know — falls to `mojo_sorted`, which orders by the raw
                int64_t payload, i.e. by ADDRESS for strings.
                Fix: sort a set (mojo_set_sorted dispatches on slot tags),
                or make the element type provably `char *`.

  SET-ITER      `for x in <a set>:` without sorted() — set iteration is now
                insertion-ordered, so this is only a warning: it is stable
                but still depends on insertion order rather than content.

  ID-KEY        `id(...)` used to build a key — an address by definition.

  ISINSTANCE-SCALAR
                `isinstance(x, str/int/float/bool)` — those are raw unboxed
                values with no runtime marker, so mojo_isinstance cannot
                answer and returns 0: the test is ALWAYS FALSE self-hosted.

Usage: tools/audit_determinism.py [files...]   (default: the compiler sources)
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))

DEFAULT = ([f for f in sorted(os.listdir(HERE))
            if f.startswith('gimple') and f.endswith('.py')]
           + ['fire_compiler.py', 'module_loader.py', 'ast_rewriter.py',
              'imports.py', 'regex_compile.py'])

PATTERNS = [
    ('TUPLE-KEY', re.compile(r'\.(?:get|setdefault|pop)\(\(\s*[^()\[\]]+,')),
    ('TUPLE-KEY', re.compile(r'\[\(\s*[A-Za-z_][\w.]*\s*,\s*[^()\[\]]+\)\]')),
    ('TUPLE-KEY', re.compile(r':\s*dict\[\s*tuple')),
    ('TUPLE-IN',  re.compile(r'\(\s*[A-Za-z_][\w.]*\s*,[^()]*\)\s+(?:not\s+)?in\s+')),
    ('UNPACK',    re.compile(r'\bfor\s+[A-Za-z_]\w*\s*,\s*[A-Za-z_*][\w,\s*]*\s+in\s+')),
    ('GENEXPR',   re.compile(r'\b(?:any|all)\s*\(.*\bfor\b.*\bin\b')),
    ('SORT',      re.compile(r'\bsorted\s*\(')),
    ('SET-ITER',  re.compile(r'\bfor\s+\w+\s+in\s+\w*(?:_set|_names|_needed|s)\b\s*:')),
    ('ID-KEY',    re.compile(r'\bid\s*\(')),
    ('ISINSTANCE-SCALAR',
                  re.compile(r'isinstance\s*\([^,]+,\s*\(?\s*(?:str|int|float|bool)\s*[),]')),
]

# Lines already carrying a deliberate, reviewed fix.
EXEMPT = re.compile(r'_as_str|_as_int|_as_set|_as_list|_sms_key|_c_field_name'
                    r'|mojo_set_sorted|sorted\(set\(')


def audit(paths):
    hits = {}
    for rel in paths:
        p = os.path.join(HERE, rel)
        if not os.path.exists(p):
            continue
        for n, line in enumerate(open(p, encoding='utf8'), 1):
            s = line.split('#', 1)[0]
            if not s.strip():
                continue
            for kind, rx in PATTERNS:
                if not rx.search(s):
                    continue
                if kind in ('SORT', 'UNPACK', 'SET-ITER') and EXEMPT.search(s):
                    continue
                hits.setdefault(kind, []).append((rel, n, line.rstrip()[:130]))
    return hits


def main(argv):
    paths = argv or DEFAULT
    hits = audit(paths)
    order = ['TUPLE-KEY', 'TUPLE-IN', 'ID-KEY', 'GENEXPR', 'UNPACK',
             'ISINSTANCE-SCALAR', 'SORT', 'SET-ITER']
    total = 0
    for kind in order:
        rows = hits.get(kind, [])
        total += len(rows)
        print(f'\n=== {kind}: {len(rows)} ===')
        for rel, n, line in rows[:40]:
            print(f'  {rel}:{n}: {line.strip()}')
        if len(rows) > 40:
            print(f'  ... and {len(rows) - 40} more')
    print(f'\nTOTAL: {total}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
