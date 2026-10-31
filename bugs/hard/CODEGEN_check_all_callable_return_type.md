# Callable return type for check_all: research for Sonnet 5.5

Owner direction (2026-10-30): maximal compatibility with Python; eventually fix all bugs; the compiled code must coexist with the C API (fopen, write and so on), with the usual limits. Research and ANSWER this, do not start a fix.

## The question
The callable-return-type fix for `check_all` (Tools/c-analyzer) can take one of three routes:
- A-rev: a whole-program reverse-import index, which needs a module CAS key change and a full gate.
- A-local: local only. It fixes nothing for this file.
- C: keep the refusal and close the doc as a known limitation (the worker recommended C unless A-rev is acceptable).

## What to answer
1. Which route gives the most Python compatibility at the least risk? Name the exact CAS key change for A-rev and what it invalidates.
2. Is the refusal (C) compatible with the goal of fixing all bugs, or does it close a path for good?
3. Give the gate cost of each route, measured or estimated.

Source doc: bugs/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__.md
