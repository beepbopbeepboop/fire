# COMPILE_FAIL: Lib/multiprocessing/queues.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/queues.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_JoinableQueue__jointhread", referenced from:
      _JoinableQueue_join_thread in queues.o
      _JoinableQueue__terminate_broken in queues.o
  "_JoinableQueue__poll", referenced from:
      _JoinableQueue_get in queues.o
      _JoinableQueue_get in queues.o
      _JoinableQueue_empty in queues.o
  "_JoinableQueue__recv_bytes", referenced from:
      _JoinableQueue_get in queues.o
      _JoinableQueue_get in queues.o
  "_Queue__jointhread", referenced from:
      _Queue_join_thread in queues.o
      _Queue__terminate_broken in queues.o
  "_Queue__poll", referenced from:
      _Queue_get in queues.o
      _Queue_get in queues.o
      _Queue_empty in queues.o
  "_Queue__recv_bytes", referenced from:
      _Queue_get in queues.o
      _Queue_get in queues.o
  "_SimpleQueue__poll", referenced from:
      _SimpleQueue_empty in queues.o
  "_debug", referenced from:
      _Queue__after_fork in queues.o
      _Queue_join_thread in queues.o
      _Queue_cancel_join_thread in queues.o
      _Queue__terminate_broken in queues.o
      _Queue__start_thread in queues.o
      _Queue__start_thread in queues.o
      _Queue__start_thread in queues.o
      ...
  "_info", referenced from:
      _Queue__feed in queues.o
  "_is_exiting", referenced from:
      _Queue__feed in queues.o
      _Queue__feed in queues.o
  "_object", referenced from:
      __toplevel in queues.o
  "_register_after_fork", referenced from:
      _Queue___init__ in queues.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 11.62s
