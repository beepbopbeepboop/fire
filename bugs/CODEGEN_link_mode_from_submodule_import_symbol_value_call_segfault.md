# CODEGEN (link-mode): `from SUBMODULE import SYMBOL`, symbol bound to a
# local, called through that local — SEGFAULTS

## Discovered 2026-08-27/28, via `test_link_mode.py` (the new link-mode
## regression suite added alongside the asyncio/futures.py link-mode fix)

Real link-mode (`driver.compile_program`, the actual default `mojo.py
build` pipeline — NOT the `do_imports=False` inline path every other
gate step, including `compile_stdlib.py`, exercises) segfaults on this
shape:

```python
# pkg/base.py
def triple(x):
    return x * 3

# pkg/main.py
from .base import triple
f = triple
print(f(14))
```

`python3 mojo.py build pkg/main.py && ./main` — builds clean (exit 0),
crashes at runtime: `Segmentation fault: 11`.

Confirmed pre-existing and unrelated to either of the two link-mode
fixes landed the same session (commit fixing `bugs/COMPILE_FAIL_
asyncio_futures.md`'s bare-`from PKG import SUBMODULE`-marker
value-read gap, and the sibling generic-module-call-routing fix in
`gimple_gen_methods.py`) — reproduces identically with BOTH of those
fixes reverted. A genuinely separate, more severe (crash, not a wrong
value or an honest refusal) link-mode bug, surfaced only because this
was the first time anything exercised `driver.compile_program` with a
real multi-file package + this exact shape (`from SUBMODULE import
SYMBOL` where SYMBOL is a plain function, then bound to a NEW local
before being called through that local — as opposed to being called
directly, `triple(14)`, which is untested here and may or may not share
the same root cause).

Not investigated further — filed here rather than chased in the same
pass that found it (out of scope: this doc's only job is to record the
precise repro before it's lost, not root-cause or fix it).

`test_link_mode.py`'s `test_from_submodule_import_symbol_value_read_
KNOWN_BUG` pins this exact repro and expects the crash (`rc == -11`) —
when this doc is closed, that test's expectation (and its `_KNOWN_BUG`
suffix) must be updated to expect success, not just deleted.

## Repro

```
mkdir -p /tmp/repro/pkg
touch /tmp/repro/pkg/__init__.py
cat > /tmp/repro/pkg/base.py <<'EOF'
def triple(x):
    return x * 3
EOF
cat > /tmp/repro/pkg/main.py <<'EOF'
from .base import triple
f = triple
print(f(14))
EOF
cd /tmp/repro && python3 <path-to-mojo-reference>/mojo.py build pkg/main.py && ./main
# Built: .../main
# Segmentation fault: 11
```
