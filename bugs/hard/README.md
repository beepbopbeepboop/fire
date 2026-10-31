# bugs/hard: the hard queue

Bugs that need a careful pass, or a decision, or a stronger model than the swarm's workers. Each doc says what is
known, the question or next step, and who it is for. A doc here is not a stopping point: when it is fixed, its doc is
deleted in the same commit, as for any bug.

| doc | what it needs | for |
|---|---|---|
| `CODEGEN_check_all_callable_return_type.md` | research: whole-program reverse-import index (CAS key change) vs local vs refusal | Sonnet 5.5 (research, then a decision) |
| `CODEGEN_frame_model_for_test_frame.md` | research: how much of a frame model compiled code can have, within the C API | Sonnet 5.5 (research, then a decision) |
| `CODEGEN_gate_test_linked_list_red_is_not_the_box_free_change.md` | `test_linked_list` JIT failure, identical on the commit before the box-free change | open |
