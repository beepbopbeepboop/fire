# CODEGEN: `max(x, key=f)` / `min(x, key=f)` ignore `key` (`divmod` fixed 2026-11-20)

Found 2026-11-20 by `tools/pydiff.py` (this is what is left of the older "call arguments dropped" doc:
`print(sep, end)`, `str.split/strip/replace/zfill/ljust/rjust/center` arguments and `sum(x, start)` are fixed).

## Repro `minmax_args.py`

```python
def main():
    print(max(1, 2, 3))
    print(min(4, 2, 9, 1))
    print(max([1, 5, 2]))
    print(sum([1, 2, 3], 10))
    print(max(["a", "bb", "c"], key=len))
    print(min(3, 2.5))
    print(divmod(-7, 2))
    print(pow(2, 10))
    print(round(2.675, 2))
main()
```

CPython line 5 is `bb` (`max` by length), compiled prints `c`: `key=` is dropped. `divmod` is fixed (`mojo_divmod` marked its result a tuple before appending to it). `round(2.675, 2)` should print `2.67` (CPython rounds the binary value, not the decimal text).

## Where to look

`max`/`min` with a `key=` keyword: grep `'max'` in `mojo/backend_gimple/emit_calls.py`; the key function
must be called on each element and the extreme taken over the keys. `divmod`: grep `divmod`; it must
return a 2-tuple with floor semantics for negative operands.

## Done when

`python3 tools/pydiff.py <the repro saved as a file>` prints `OK`; add it to `tools/pydiff_corpus/min/` and
`tools/pydiff_ok.txt`, delete this doc, run `python3 tools/dangling_doc_refs.py --ratchet`.
