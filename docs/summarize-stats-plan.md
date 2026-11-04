# Plan: summarize_stats typed callable slots

Source bug: bugs/hard/COMPILE_FAIL_Tools_scripts_summarize_stats.md

## Decomposition

Step 1 — types.py callable_ctype for str/pointer-returning closures
Step 2 — cpp_async.py closure-factory gates (lines ~1568/1592)
Step 3 — cpp_core.py typed dispatch
Step 4 — typed std::function<R(P...)> slots
Step 5 — Measure read_table-like generator eligibility
