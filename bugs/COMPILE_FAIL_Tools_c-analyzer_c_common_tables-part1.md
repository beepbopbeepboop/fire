# COMPILE_FAIL: Tools/c-analyzer/c_common/tables.py — end-to-end build

## Goal
Confirm that `Tools/c-analyzer/c_common/tables.py` (from CPython 3.14.6) builds and runs end-to-end with the current compiler, so the tracked compile failure is closed.

## Acceptance
`python3 fire.py build -o .tmp/ca/tables_out .tmp/ca/c_common/tables.py` exits 0 when the `c-analyzer` sources are present under `.tmp/ca/` (copied from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/`), and the produced `.tmp/ca/tables_out` binary runs with exit code 0.

## Done when
Run:

```sh
mkdir -p .tmp/ca && \
cp -R /Users/mrs/net/Python-3.14.6/Tools/c-analyzer/. .tmp/ca/ && \
python3 tools/memslot.py --gb 8 --label tables-build -- \
  python3 fire.py build -o .tmp/ca/tables_out .tmp/ca/c_common/tables.py && \
.tmp/ca/tables_out
```

The command exits 0.
