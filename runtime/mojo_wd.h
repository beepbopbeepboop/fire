/* mojo_wd.h -- wait-descriptor encoding for A3 stack-switch `async def`.

   An async coroutine that suspends at `await` yields exactly one int64_t
   (via __mojo_coro_yield, same as a generator's yield) describing what
   it's waiting for. A coroutine awaiting ANOTHER compiled async coroutine
   just forwards its inner wait-descriptor upward unchanged (the same
   pattern gimple_gen_coro.py already uses for generator `yield from`)
   until it reaches mojo_async_sched.c, the only thing that interprets it.

   Encoding: kind in the top byte, payload in the low 56 bits (ample for
   both an absolute CLOCK_MONOTONIC nanosecond timestamp and a fd). */
#ifndef MOJO_WD_H
#define MOJO_WD_H

#include <stdint.h>

#define MOJO_WD_READY  0   /* not currently emitted; reserved              */
#define MOJO_WD_SLEEP  1   /* payload = absolute wake time, CLOCK_MONOTONIC ns */
#define MOJO_WD_READ   2   /* payload = fd, wake when readable              */
#define MOJO_WD_WRITE  3   /* payload = fd, wake when writable              */

#define MOJO_WD_MASK   ((int64_t)0x00FFFFFFFFFFFFFFLL)

static inline int64_t mojo_wd_make(int64_t kind, int64_t payload)
{
    return (kind << 56) | (payload & MOJO_WD_MASK);
}
#define MOJO_WD_KIND(w)    (((int64_t)(w) >> 56) & 0xFF)
#define MOJO_WD_PAYLOAD(w) ((int64_t)(w) & MOJO_WD_MASK)

#endif /* MOJO_WD_H */
