/* mojo_coro_ctx_aarch64.S -- Layer 3 (SEAM B) for AArch64.

   The boost.context / libaco "fcontext" three-function primitive, written
   from the AAPCS64 spec (not copied): callee-saved state is x19-x28, the
   frame pointer x29, the link register x30, and the low 64 bits of the
   SIMD registers v8-v15 (d8-d15), plus the stack pointer. That is the
   entire machine state a context switch must preserve.

   Saved-context block layout (160 bytes, at the target's saved SP):
       0x00  d8  d9        0x40  x19 x20      0x80  x27 x28
       0x10  d10 d11       0x50  x21 x22      0x90  x29 x30
       0x20  d12 d13       0x60  x23 x24
       0x30  d14 d15       0x70  x25 x26
   The x30 slot (0x98) holds the address to resume at.

   Darwin/Mach-O conventions: leading underscore on C symbols, @PAGE/@PAGEOFF
   for the trampoline address, .subsections_via_symbols at the end.
*/
#if defined(__aarch64__) || defined(__arm64__)

    .section __TEXT,__text,regular,pure_instructions
    .p2align 2

/* ----------------------------------------------------------------------
   mojo_xfer_t mojo_jump_fctx(to=x0, data=x1)  ->  x0=from, x1=data
   -------------------------------------------------------------------- */
    .globl _mojo_jump_fctx
_mojo_jump_fctx:
    sub  sp, sp, #0xA0
    stp  d8,  d9,  [sp, #0x00]
    stp  d10, d11, [sp, #0x10]
    stp  d12, d13, [sp, #0x20]
    stp  d14, d15, [sp, #0x30]
    stp  x19, x20, [sp, #0x40]
    stp  x21, x22, [sp, #0x50]
    stp  x23, x24, [sp, #0x60]
    stp  x25, x26, [sp, #0x70]
    stp  x27, x28, [sp, #0x80]
    stp  x29, x30, [sp, #0x90]

    mov  x2, sp                 /* from = our saved-context pointer */
    mov  sp, x0                 /* switch to target stack           */

    ldp  d8,  d9,  [sp, #0x00]
    ldp  d10, d11, [sp, #0x10]
    ldp  d12, d13, [sp, #0x20]
    ldp  d14, d15, [sp, #0x30]
    ldp  x19, x20, [sp, #0x40]
    ldp  x21, x22, [sp, #0x50]
    ldp  x23, x24, [sp, #0x60]
    ldp  x25, x26, [sp, #0x70]
    ldp  x27, x28, [sp, #0x80]
    ldp  x29, x30, [sp, #0x90]
    add  sp, sp, #0xA0

    mov  x0, x2                 /* x0 = from ; x1 = data (unchanged) */
    ret                         /* -> target's resume address (x30) */

/* ----------------------------------------------------------------------
   mojo_xfer_t mojo_ontop_fctx(to=x0, data=x1, fn=x2)
   Switch to `to`, then run fn({from,data}) ON to's STACK; `to` resumes
   with fn's returned xfer.
   -------------------------------------------------------------------- */
    .globl _mojo_ontop_fctx
_mojo_ontop_fctx:
    sub  sp, sp, #0xA0
    stp  d8,  d9,  [sp, #0x00]
    stp  d10, d11, [sp, #0x10]
    stp  d12, d13, [sp, #0x20]
    stp  d14, d15, [sp, #0x30]
    stp  x19, x20, [sp, #0x40]
    stp  x21, x22, [sp, #0x50]
    stp  x23, x24, [sp, #0x60]
    stp  x25, x26, [sp, #0x70]
    stp  x27, x28, [sp, #0x80]
    stp  x29, x30, [sp, #0x90]

    mov  x3, sp                 /* from */
    mov  sp, x0                 /* switch to target stack */

    ldp  d8,  d9,  [sp, #0x00]
    ldp  d10, d11, [sp, #0x10]
    ldp  d12, d13, [sp, #0x20]
    ldp  d14, d15, [sp, #0x30]
    ldp  x19, x20, [sp, #0x40]
    ldp  x21, x22, [sp, #0x50]
    ldp  x23, x24, [sp, #0x60]
    ldp  x25, x26, [sp, #0x70]
    ldp  x27, x28, [sp, #0x80]
    ldp  x29, x30, [sp, #0x90] /* x30 = target resume address */
    add  sp, sp, #0xA0

    mov  x0, x3                 /* fn arg0 = from ; x1 = data */
    str  x30, [sp, #-16]!       /* stash target resume addr (16 = align) */
    blr  x2                     /* fn({from,data}) -> {x0,x1} */
    ldr  x30, [sp], #16
    ret                         /* -> target resume addr, x0:x1 = fn result */

/* ----------------------------------------------------------------------
   mojo_fctx_t mojo_make_fctx(stack_top=x0, size=x1, entry=x2)
   -------------------------------------------------------------------- */
    .globl _mojo_make_fctx
_mojo_make_fctx:
    and  x0, x0, #0xFFFFFFFFFFFFFFF0   /* align stack_top down to 16 */
    sub  x0, x0, #0xA0                 /* reserve the saved-context block */

    str  x2, [x0, #0x40]              /* x19 slot <- entry fn */
    str  xzr, [x0, #0x90]            /* x29 slot <- 0 (end frame chain) */

    adrp x3, _mojo_fctx_trampoline@PAGE
    add  x3, x3, _mojo_fctx_trampoline@PAGEOFF
    str  x3, [x0, #0x98]            /* x30 slot <- trampoline */
    ret

/* Entered (via the `ret` in jump/ontop) the first time a fresh context
   is switched to. x0 = from, x1 = data, x19 = entry fn. */
    .p2align 2
_mojo_fctx_trampoline:
    mov  x29, #0                     /* frame-chain terminator */
    blr  x19                         /* entry({from, data}) -- never returns */
    brk  #0x1

    .subsections_via_symbols
#endif /* __aarch64__ */
