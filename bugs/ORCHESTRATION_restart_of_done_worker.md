# ORCHESTRATION_restart_of_done_worker

## Summary
`sync` restarted a worker whose round had finished with exit code 0 and verdict DONE, logging
`previous instance stopped (process dead ...)`. A DONE round should not be restarted; it should be judged on its output.

## Evidence
- `bug-codegen-class-rebind-late-binding-r31`: CONTROL-STATUS DONE, exitcode 0, and the next round's task text
  says the previous instance "stopped (process dead (sync --restart-dead))".
- `fix-gate-formal-host-import-shapes-r2-r2-r2-r99`: DONE with no commit, and it was continued as `-r100`
  (chain of 197 rounds, see the import-shapes doc).

## Repro
Let a worker finish with DONE, then run `sync --restart-dead` while its process has exited: it is restarted.

## Status
Open. Not started. The restart rule should look at the exit code and the verdict, not only whether the pid is alive.

## Done when
`sync --restart-dead` never restarts a task whose verdict is DONE with exit code 0, with a test. Then delete this doc
in the same commit.
