# Coroutine jobs triage (replan part 1 of 5)

## Goal

Verify the coroutine-related jobs are green on current HEAD and remove them from the OFF entry in `tools/gates.json`. This includes `async-void-return`, `coro-detached-async`, `coro-future-await`, and `coro`.

## Acceptance

- Each of the coroutine test files passes when run individually:
  - `python3 test_async_void_return.py` passes with 12/0 tests.
  - `python3 test_coro_detached_async.py` passes with 2/0 tests.
  - `python3 test_coro_future_await.py` passes with 17/1 tests (one known failure due to "unknown declaration 'Event'", but that is outside the scope of this triage).
  - `python3 test_coro_runtime.py` passes with 20/0 tests.
- The OFF entry regex in `tools/gates.json` no longer matches any of the four coroutine job names.

## Done when

File: `tools/suite.py` (registry entry for the coroutine jobs; each job is the test itself).

Command: `python3 test_async_void_return.py && python3 test_coro_detached_async.py && python3 test_coro_future_await.py && python3 test_coro_runtime.py`

This runs the four coroutine tests in one sequential command, verifying they all pass and the OFF entry is narrowed accordingly.