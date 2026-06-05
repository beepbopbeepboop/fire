/* reflect.h — the plain-C-ABI reflection table every Mojo dylib exports.
 *
 * MODULE_CACHE_DESIGN.md stage 4. This is the unified import interface: the
 * compiler's own `import` path reads this table, and so can ANY language that
 * speaks the C ABI (dlopen + dlsym("__mojo_reflect") + walk the array + call by
 * addr). No headers, no mangling beyond what `signature` states.
 */
#ifndef MOJO_REFLECT_H
#define MOJO_REFLECT_H
#include <stdint.h>

#define MOJO_REFLECT_MAGIC   0x4D4F4A4Fu  /* 'MOJO' */
#define MOJO_REFLECT_VERSION 1u

/* Symbol kinds. */
enum {
    MOJO_SYM_FUNCTION = 0,
    MOJO_SYM_METHOD   = 1,
    MOJO_SYM_GLOBAL   = 2,
    MOJO_SYM_TYPE     = 3   /* reserved: type/layout descriptors (stage 4+) */
};

typedef struct {
    const char *name;       /* lookup key, e.g. "mathlib_add"                 */
    const char *signature;  /* C signature, e.g. "int64_t mathlib_add (...)"  */
    void       *addr;       /* address of the symbol — directly callable      */
    int32_t     kind;       /* one of MOJO_SYM_*                               */
} MojoReflectSym;

typedef struct {
    uint32_t magic;         /* MOJO_REFLECT_MAGIC                             */
    uint32_t version;       /* MOJO_REFLECT_VERSION                          */
    uint32_t n_syms;
    uint32_t reserved;
    const MojoReflectSym *syms;
} MojoReflectTable;

/* Every Mojo dylib exports exactly one of these. */
extern const MojoReflectTable __mojo_reflect;

#endif /* MOJO_REFLECT_H */
