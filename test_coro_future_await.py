"""test_coro_future_await.py -- real behavioral tests for the A3
stack-switch backend's Awaitable protocol: heap-allocatable Future/Event
handles with a waiter list and cross-coroutine wakeup (runtime/
mojo_coro_gen.c: __mojo_future_* / __mojo_event_* / __mojo_async_await_
future / __mojo_async_await_event_wait; MOJO_WD_FUTURE in mojo_async_sched.c).

Compiles the REAL generated C with gcc -fgimple, links this project's own
runtime, runs the executable, asserts on real stdout. Mirrors
test_coro_detached_async.py's harness.
"""
import os
import platform
import subprocess
import tempfile

os.environ['MOJO_CORO'] = 'stackswitch'

import gimple_codegen
from build_config import find_gcc, find_gxx

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(HERE, 'runtime')
GCC = find_gcc()
GXX = find_gxx()

_CORO_CTX_SRC = (os.path.join(RUNTIME_DIR, 'mojo_coro_ctx_aarch64.S')
                 if platform.machine() in ('arm64', 'aarch64')
                 else os.path.join(RUNTIME_DIR, 'mojo_coro_ctx_generic.c'))

_RUNTIME_SRCS = [
    os.path.join(RUNTIME_DIR, 'mojo_runtime.c'),
    os.path.join(RUNTIME_DIR, 'mojo_async_runtime.cpp'),
    os.path.join(RUNTIME_DIR, 'mojo_coro.c'),
    os.path.join(RUNTIME_DIR, 'mojo_coro_gen.c'),
    os.path.join(RUNTIME_DIR, 'mojo_async_sched.c'),
    _CORO_CTX_SRC,
]

_PASS = 0
_FAIL = 0


def check(name, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}  {detail}")
        _FAIL += 1


def _build_and_run(mojo_src: str) -> str:
    wd = tempfile.mkdtemp(prefix='mojo_coro_future_')
    src_path = os.path.join(wd, 'prog.mojo')
    with open(src_path, 'w') as f:
        f.write(mojo_src)

    c_code = gimple_codegen.compile_to_gimple(mojo_src, do_imports=False, filename=src_path)
    if '__mojo_async_await_future' not in c_code and '__mojo_async_await_event_wait' not in c_code:
        raise RuntimeError("no Awaitable-protocol shim call in the generated C -- "
                           "this test isn't exercising the path it claims to:\n" + c_code)

    c_path = os.path.join(wd, 'prog.c')
    with open(c_path, 'w') as f:
        f.write(c_code)

    objs = []
    r = subprocess.run([GCC, '-fgimple', f'-I{RUNTIME_DIR}', '-w', '-c', '-o',
                        os.path.join(wd, 'prog.o'), c_path],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"gcc -fgimple compile failed: {r.stderr}\n---\n{c_code}")
    objs.append(os.path.join(wd, 'prog.o'))

    for i, src in enumerate(_RUNTIME_SRCS):
        is_cpp = src.endswith('.cpp')
        cc = GXX if is_cpp else GCC
        extra = ['-std=c++20'] if is_cpp else []
        o = os.path.join(wd, f'rt{i}.o')
        r = subprocess.run([cc, *extra, f'-I{RUNTIME_DIR}', '-c', '-o', o, src],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(f"compile of {src} failed: {r.stderr}")
        objs.append(o)

    exe = os.path.join(wd, 'prog.exe')
    r = subprocess.run([GXX, '-o', exe, *objs], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"link failed: {r.stderr}")
    os.chmod(exe, 0o755)
    r = subprocess.run([exe], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"program exited {r.returncode}, stderr={r.stderr}")
    return r.stdout


def test_await_resolved_future_value():
    """`await <future handle>` in a nested coroutine returns the future's
    result box. (The future is resolved before it is awaited -- v0's
    create_task has no eager scheduling, so genuine cross-coroutine wakeup
    through the scheduler is covered by runtime/test_mojo_future.c at the C
    level; see COMPILE_FAIL_asyncio_queues.md for the eager-task gap.)"""
    src = """\
import asyncio

async def consumer(fut: Int) -> Int:
    var v = await fut
    return v + 1

async def main_co() -> Int:
    var fut = create_future()
    fut.set_result(41)
    var r = await consumer(fut)
    return r

def main():
    print(asyncio.run(main_co()))
"""
    out = _build_and_run(src)
    check("await <future> returns the resolved result box",
          out == "42\n", detail=repr(out))


def test_await_event_wait_bound_method():
    """`await <event>.wait()` -- a bound-method await -- compiles and runs;
    returns once the Event is set."""
    src = """\
import asyncio

async def waiter(ev: Int) -> Int:
    await ev.wait()
    return 7

async def main_co() -> Int:
    var ev = Event()
    ev.set()
    var r = await waiter(ev)
    return r

def main():
    print(asyncio.run(main_co()))
"""
    out = _build_and_run(src)
    check("await <event>.wait() bound-method await compiles and runs",
          out == "7\n", detail=repr(out))


def test_sync_method_side_future_ops():
    """Gap 1 (bugs/COMPILE_FAIL_asyncio_queues.md): `create_future()` and
    `.set_result(v)` reached from ORDINARY (non-coroutine) struct methods
    lower onto the same A3 Future handle the async side awaits. Mirrors
    asyncio.Queue.put_nowait -> _wakeup_next -> `waiter.set_result(None)`."""
    src = """\
import asyncio

async def consumer(fut: Int) -> Int:
    var v = await fut
    return v + 5

struct Box:
    var f: Int
    fn __init__(out self):
        self.f = 0
    fn _loop(self) -> Int:
        return 0
    fn make(mut self):
        self.f = self._loop().create_future()
    fn fire(mut self):
        self.f.set_result(37)

async def main_co() -> Int:
    var b = Box()
    b.make()
    b.fire()
    var r = await consumer(b.f)
    return r

def main():
    print(asyncio.run(main_co()))
"""
    out = _build_and_run(src)
    check("sync-method create_future()/.set_result() round-trip to await",
          out == "42\n", detail=repr(out))


def test_eager_task_scheduling_concurrency():
    """Gap 3 (bugs/COMPILE_FAIL_asyncio_queues.md): `create_task` eagerly
    schedules the coroutine onto the shared scheduler ready queue, so two
    sibling tasks run concurrently and a producer wakes an already-parked
    consumer through a Future. `await <task>` drains the scheduler instead
    of privately re-driving the task."""
    src = """\
import asyncio

async def consumer(fut: Int) -> Int:
    var v = await fut
    return v + 1

async def producer(fut: Int) -> Int:
    fut.set_result(41)
    return 0

async def main_co() -> Int:
    var fut = create_future()
    var c = create_task(consumer(fut))
    var p = create_task(producer(fut))
    var rc = await c
    var rp = await p
    return rc

def main():
    print(asyncio.run(main_co()))
"""
    out = _build_and_run(src)
    check("create_task sibling concurrency + Future wakeup of a parked consumer",
          out == "42\n", detail=repr(out))


def test_deque_field_future_handle_roundtrip():
    """Gap 2 (bugs/COMPILE_FAIL_asyncio_queues.md): an unannotated
    `self._getters = deque()` field types as MojoList *; append/popleft
    round-trip an int64_t Future handle so `.set_result()` on the popped
    value reaches the awaiting coroutine. Mirrors asyncio.Queue's
    `_getters`/`_wakeup_next` shape."""
    src = """\
import asyncio
from collections import deque

struct Waiters:
    fn __init__(out self):
        self._q = deque()
    fn park(mut self, fut: Int):
        self._q.append(fut)
    fn wake_all(mut self):
        while len(self._q) > 0:
            var w = self._q.popleft()
            w.set_result(9)

async def consumer(wq: Waiters) -> Int:
    return 0

async def main_co() -> Int:
    var wq = Waiters()
    var fut = create_future()
    wq.park(fut)
    wq.wake_all()
    var v = await fut
    return v + 1

def main():
    print(asyncio.run(main_co()))
"""
    out = _build_and_run(src)
    check("deque() field + append/popleft round-trips a Future handle",
          out == "10\n", detail=repr(out))


def test_async_struct_method_queue_roundtrip():
    """Gap 4 (bugs/COMPILE_FAIL_asyncio_queues.md): `async def` METHODS on
    a compiled struct (a `self: Queue` receiver) become real A3 stack-switch
    coroutines -- a receiver slot in the start-function + a method-mangled
    trampoline (__mgco_<Struct>_<method>_start), and `await obj.method(...)`
    at the call site constructs + drives that coroutine. This is the
    asyncio.Queue put/get shape: `get` awaits a bare local Future it parked
    on `self._getters`; a sync `put_nowait` wakes it via `.set_result`."""
    src = """\
import asyncio
from collections import deque

struct Q:
    fn __init__(out self):
        self._items = deque()
        self._getters = deque()
    fn empty(self) -> Bool:
        return len(self._items) == 0
    fn put_nowait(mut self, item: Int):
        self._items.append(item)
        while len(self._getters) > 0:
            var g = self._getters.popleft()
            g.set_result(0)
    async def get(self) -> Int:
        while self.empty():
            var getter = create_future()
            self._getters.append(getter)
            await getter
        return self._items.popleft()
    async def put(self, item: Int) -> Int:
        self.put_nowait(item)
        return 0

async def main_co() -> Int:
    var q = Q()
    var r = await q.put(41)
    var v = await q.get()
    return v + 1

def main():
    print(asyncio.run(main_co()))
"""
    out = _build_and_run(src)
    check("async struct method (Queue.get/.put) compiles + awaits + runs",
          out == "42\n", detail=repr(out))


def run_all():
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
            except Exception as e:
                check(name, False, detail=f"exception: {e}")
    print(f"\nResults: {_PASS} passed, {_FAIL} failed")
    return _FAIL == 0


if __name__ == '__main__':
    import sys
    sys.exit(0 if run_all() else 1)
