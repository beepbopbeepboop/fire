# Wave-2 Integration Baseline (2026-08-21)

Git HEAD at capture: `436cc16` (pristine master, no refactor changes).

## Gate results

| Gate | Result |
|---|---|
| `python3 test_gimple.py` | **250 passed, 0 failed** |
| `python3 test_module_cache.py` | **76 passed, 0 failed** |
| stdlib dylib rebuild (`rm -f build/libmojostdlib.dylib && python3 -c "import build_stdlib_dylib as bsd; bsd.build_stdlib(jobs=8)"`) | exit 0 |
| **`skip <module>:` lines in stdlib build output** | **0** (none — this is the CLAUDE.md regression metric; must not increase) |

Raw stdlib build log: `/var/folders/bt/pjzl0n_w8xn64y008k907xch0000gs/T/opencode/stdlib_baseline.log`
(rebuild regenerates an equivalent log; compare skip counts, not the noise lines).

Not yet captured on pristine master (run at first milestone): `make check-selfhost`,
`make bootstrap`.

## Notes

- The dylib build emitted only benign linker-stage noise
  (`drop stale export '...'`, `localize N dup symbol(s)`); zero module-level skips.
- Post-integration acceptance: same 250/76 pass counts, check-selfhost PASS,
  bootstrap PASS, and stdlib rebuild still reports **0** skip lines.
