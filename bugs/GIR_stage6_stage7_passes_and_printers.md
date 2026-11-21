# GIR stages 6 and 7: the loop and pass shapes, and the other printers

Plan source: `doc/GIR.md`, Stage 6 (counted loops, arms of the giant functions, passes of
`gen_module_impl`) and Stage 7 (the other printers, including the C++ coroutine lowering in
`cpp_core.py`).

## Still open

- Stage 6: the single loop builder (`gen._loop_head`) is used by the counted loops. The remaining
  copies, and the passes of `gen_module_impl` that were started on 2026-11-16, are not finished.
- Stage 7: `cpp_core.py` is the C++ coroutine printer. Its lowering still spells types and
  statements as strings; the plan moves it onto the same builder as stage 2b.

## Next step

Finish one pass of `gen_module_impl` per change, checking each byte-identical on
`tools/pydiff_corpus`. Stage 7 starts after stage 2b and 3c are done, so it is blocked on them.
