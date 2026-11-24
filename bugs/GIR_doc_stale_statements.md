# doc/GIR.md: stale and self-contradicting statements (found 2026-11-23)

`doc/GIR.md` is the only GIR document, and workers read it as ground truth, so a wrong sentence there
costs a worker a wrong turn. Fix each item below; check each against the code before editing.

1. Line ~3, the header Status: "stages 0, 1, 2a, 3a, 3b and 5a landed". Stages 2b, 3c, 5b, the stage-6
   rounds and stage-7 T1-T6 have landed too. Rewrite it as one current line, and add that stage 4
   (types) and 5c (None) are the open stages.
2. Line ~4 points at `doc/GIR_WORKERS.md`, which was merged into this file. Delete the pointer.
3. Stage 7 (~lines 541-542) says the GCC bridge `gcc/fire/fire-gimple-bridge.cc` is "today a stub".
   There is no `gcc/` directory in this repo (`git log --all` on that path is empty). Say it does not
   exist here, and that stage 7's T1-T8 cover only the C++ printer.
4. Stage 7 (~548-553): "The builder it prints through (stage 2b) is still the blocker." That is
   contradicted by T1-T6 being done. Delete the sentence.
5. "Stage 6. Shape." bullet (~537): one loop builder "replaces the 18 copies". `_loop_head` and
   `_loop_tail` exist (see the counted-loops bullet), so this is stale. Merge it into that bullet, or
   delete it.
6. Section 5 (~563-564): "step W0.1 below turns it into tools/c_oracle.py". The tool exists. Say so.
7. Section 5 (~588): "(owner-run; see §6)". §6 is now the stage-7 section. Point at CLAUDE.md instead.
8. Section 6's first paragraph (~590-595) has pre-T3 counts (24 `.show()`, 11 `-> str` functions).
   Re-measure: `grep -c '\.show()' mojo/backend_gimple/cpp_core.py` gives 12 today, and the `-> str`
   functions are `_cpp_expr` (the named boundary), `_cpp_str_compare`, and `cpp_async.py`'s
   `_cpp_dict_key_expr` and `_cpp_fresh_name`.
9. The T4 tick says "58 to 7" `.show()`. After T6 the count is 12. Fix the tick, or say "7 after T4".
10. T5's tick says "the one `'\n'.join` site". Wrong: there is one RENDERER (`render_lines`,
    `mojo/ir/instr.py`) and three function-assembly join sites in `cpp_async.py`. Reword it.
11. T7 says the transcription-only sites are "listed in the Status entries". There is no such list.
    Either build the table (file:line | site | probe | reached or impossible) from the T3-T6 entries,
    or delete that clause from T7.
12. The per-entry "Still open: T5 to T8" / "T4 through T8" tails (~684, 718, 727, 774) and the trailing
    "Status: ... Still open: T3 to T8" paragraph (~776-778) contradict the ticks. Keep only one
    current "open: T7, T8" line.
13. Stage 5b: say that `Erased(T)` has no writer yet (it is modelled and carried only). Reword
    "carry only FILLS": a Box source upgrades a Dyn or Erased destination, and only an Int destination
    is protected (`mojo/middle/valueinfo.py` `carry`).
14. Stage 6 "NOT moved: 29 nested functions". An AST count finds 32 nested `def`s under
    `gen_module_impl` (30 direct). Re-measure how many capture a local and correct the number.

Run `python3 tools/dangling_doc_refs.py --ratchet` before committing. Delete this doc in the same
commit.
