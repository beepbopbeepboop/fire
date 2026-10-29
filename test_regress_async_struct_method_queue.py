"""Regression pin for bugs/RUNTIME_async_struct_method_queue_segfaults.md.
The case: async def method on a compiled struct (self receiver) segfaults
at runtime (SIGSEGV -11). Confirms failure before fix; must pass after.
"""
from test_coro_future_await import _build_and_run

def test_regress_async_struct_method_queue_segfault():
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
    assert out == "42\n", f"Expected '42\\n', got {out!r}"
