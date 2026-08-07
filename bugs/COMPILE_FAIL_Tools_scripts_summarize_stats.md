# COMPILE_FAIL: Tools/scripts/summarize_stats.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-06)

Re-ran; current failure is an honest up-front refusal, not a GCC error:

```
Error building: cannot compile module: function(s)
iter_optimization_tables, iter_parts, iter_pre_succ_pairs_tables,
iter_specialization_tables (generator function(s), contain a `yield`/
`yield from`) — this codegen compiles every function into a single
straight-line C function and has no suspend/resume state-machine
transform for generators, nor an event loop / suspend-resume codegen
for async functions, yet, so these cannot be represented as compiled C
without emitting silently wrong or broken code; falling back to
interpreting this module from source instead
```

Generator codegen refusal, part of the separate, already-tracked
compiled-generator/async-codegen project (tasks #95-135) — not
investigated further here per that project's scope.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py: In function '_alloc_Count':
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py:182:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  182 | class OpcodeStats:
      | ^~~~
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py: In function '_alloc_DiffRatio':
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py:196:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  196 |     def get_pair_counts(self) -> dict[tuple[str, str], int]:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py: In function '_alloc_Doc':
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py:210:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  210 |         for name, opcode_stat in self._data.items():
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py: In function '_alloc_OpcodeStats':
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py:224:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  224 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py: In function '_alloc_Ratio':
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py:238:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  238 |     def get_predecessors(self, opcode: str) -> collections.Counter[str]:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py: In function '_alloc_Section':
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py:252:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  252 |         family_stats = self._get_stats_for_opcode(opcode)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py: In function '_alloc_Stats':
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py:266:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  266 |                 label = key
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py: In function '_alloc_Table':
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py:280:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  280 |     def get_specialization_failure_total(self, opcode: str) -> int:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py: In function 'pretty_584a43':
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py:1073:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
 1073 |                 [
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py:1071:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
 1071 |                 "Deferred by instruction",
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py: In function '_load_metadata_from_source_get_defines':
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py:75:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   75 |             Path("Include") / "cpython" / "pystats.h", "EVAL_CALL"
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py:73:10: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
   73 |         ],
      |          ^   
/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py:72:10: warning: variable 'start' set but not used [-Wunused-but-set-variable]
   72 |             op for op in opcode._specialized_opmap.keys() if "__" not in op  # type: ignore
      |          ^  ~~
... (6443 more lines)
```

Exit code: 1
Elapsed: 14.37s
