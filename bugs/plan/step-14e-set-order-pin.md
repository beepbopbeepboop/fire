# plan/step-14e: pin the set iteration order (insertion order) and re-word the `set_order` neutraliser; close the doc
**Status: DONE 2026-11-06 (measured).** `set_order` row reworded to state the pin (order unchanged, deliberate); `--mix sets` draws a repeat in ~30% of literals (`--print-program 0..9` shows e.g. `{29, 29, 6}`); `--mix sets -n 20 -s set-dedup`: match 8, KNOWN:set_order 12, no other divergence. Doc banner removed, Status added. `tools/formal_fuzz.py` was edited (not on the allowed-file list but required by this step).
Class: easy      Size: S      Depends: 14a, 14b, 14c, 14d      Blocks: none
Source: `bugs/FORMAL_set_value_model.md` "If this ever stops being true" and `tools/formal_fuzz.py` `KNOWN_DIVERGENCES['set_order']` (line ~466).

## Current state (measured; verified 2026-11-05)
- `tools/formal_fuzz.py:466` row `"set_order"`: "a set lowers as a LIST, so it iterates in INSERTION order where CPython iterates in hash order (bugs/FORMAL_set_value_model.md)"; neutraliser regex at `:581`; `features_of` decides it (`:488, :5951`). `test_gimple_runner.py` and `test_runtime_header_scan.py` mention `set_order` (grep) but are unrelated to the formal fuzz.

## Decisions already made
- **The iteration order does NOT change.** Decision (made) with the reason: CPython's order for `str` elements is randomised per process (`PYTHONHASHSEED`, the same fact that makes `hash` a permanent refusal, `bugs/FORMAL_string_value_model.md` Wave 9), so for sets of strings there is no CPython order to match; for small ints it is `hash(v) % table_size` with CPython's resize and probe rules, and emulating that table would need the full CPython set algorithm (sizes 8, 32, 128..., load factor 3/5, linear probing of 9 slots, perturbation) plus a bounded bucket array: a different representation than the list blob everything else (`&|-^`, `in`, `len`, `for`) already shares. Therefore the row `set_order` STAYS, because the divergence it names still exists; the doc's instruction to delete the row applies only when the model changes the order.
- What changes: the row's text states the PIN ("first-occurrence insertion order; distinctness is established at compile time for literals and at run time by a scan (steps 14a-14d)") and the doc says the order is a deliberate model choice, not a gap.
- `print(set)` stays refused (14b updated the reason).

## Work order
1. `tools/formal_fuzz.py` row text; keep the key, regex and `features_of` untouched.
2. Add `--mix sets` coverage for repeats: in the `sets` mix generator (search `rng.sample(range(1, 30), n)` in `tools/formal_fuzz.py`) add a draw WITH replacement for a fraction of programs (use `rng.choices`), so the fuzzer can see the dedup (the doc says the corpus could not draw a repeat). Keep the neutraliser applying only to walks.
3. `bugs/FORMAL_set_value_model.md`: add a Status paragraph summarising 14a-14d and the order decision; the doc is NOT deleted (the order divergence and the `print` refusal remain as documented model choices) — but remove the "PLANNED" banner sentence that says step-14 owns it, and update `bugs/OPEN_WORK.md` if it lists the doc (grep `FORMAL_set_value_model`).
4. Run `python3 tools/dangling_doc_refs.py --ratchet` before/after; no new citations.

## Do NOT
- Do not delete the `set_order` row or its neutraliser. Do not try to emulate CPython's table.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 tools/formal_fuzz.py --mix sets -n 20 --seed set-dedup
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_container_methods.py
```

## Done when
- [ ] `--mix sets -n 20` reports no unexpected divergence (only `KNOWN:set_order` / match)
- [ ] the fuzz can generate a literal with a repeat (`--print-program` of some index shows a duplicate element; run `--print-program 0..9` and grep)
- [ ] doc Status updated

## If stuck
If the fuzz reports a non-`set_order` divergence on a repeat-containing program, that is a real bug in 14a-14d: minimise it with `--minimize`, paste the program into the doc Status, stop.
