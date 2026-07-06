# Codegen Backlog (superseded)

This file's content has been migrated: fixed items moved to `IMPL.md`
("Recent Work (2026-07)"), still-open items moved to `PLAN.md`. Kept as a
thin redirect because a number of in-code comments still reference this
file's old section numbers — see the mapping below.

| Old section | Status | New home |
|---|---|---|
| §1 — exceptions/setjmp + the 9 bootstrap segfault bugs | Fixed | `IMPL.md`, "Exceptions actually work at runtime on macOS arm64" |
| §2 — `_TYPE_MAP` vs `ABI.md` divergence | Fixed | `IMPL.md`, "Smaller fixes" |
| §3 — `fix_gimple_*.py` defects | Fixed | `IMPL.md`, "Smaller fixes" |
| §4 — struct-method stub guard, try/finally, typed except, setjmp address | Mixed | Fixed parts in `IMPL.md` ("Smaller fixes"); typed except dispatch and BUG-013 still open in `PLAN.md` |
| §4b — `test_span.mojo` / compile_stdlib 595/0 | Fixed | `IMPL.md`, "`compile_stdlib.py` reaches 595/0" |
| §4c — deferred generalizations (RTTI, generators, tuple-keyed dicts) | Still open | `PLAN.md`, "Deferred generalizations" |
| §4d — ternary eager evaluation | Fixed (ternary); `and`/`or` still open | `IMPL.md`, "Ternary expressions branch for real"; `PLAN.md` for `and`/`or` |
| §4e — `re` flags stubbed, not honored | Still open | `PLAN.md`, "Known feature gaps (regex)" |
| §4f — `.finditer()`/`re.sub()` regex engine | Fixed (finditer + foldable sub); findall/split/flags still open | `IMPL.md`, "Real regex engine"; `PLAN.md` for the remaining gaps |
| §5 — structure/maintainability refactors | Still open | `PLAN.md`, "Structure / maintainability" |
| Snapshot harness note | N/A | `PLAN.md`, "Tooling notes for future refactor work" |
| Environment notes (MOJO_STDLIB, lexer.mojo, stale dylib) | Fixed / operational note | `IMPL.md` for the two fixes; `PLAN.md` for the stale-dylib gotcha |
