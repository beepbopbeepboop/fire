# bugs/hard: the hard queue

Bugs that need a careful pass, or a decision, or a stronger model than the swarm's workers. Each doc says what is
known, the question or next step, and who it is for. A doc here is not a stopping point: when it is fixed, its doc is
deleted in the same commit, as for any bug.

| doc | what it needs | for |
|---|---|---|
| `CODEGEN_frame_f_locals_and_settrace.md` | what is left of the frame model: a real `f_locals`, `sys.settrace`, running test_frame.py through its imports |
