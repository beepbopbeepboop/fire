/* Stub Mojo runtime header for GIMPLE code generation validation */

#ifndef __MOJO_RUNTIME_H__
#define __MOJO_RUNTIME_H__

#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <setjmp.h>

/* Mojo type aliases */
typedef int mojo_int;
typedef float mojo_float;
typedef char* mojo_string;
typedef void* mojo_any;

/* Mojo runtime helpers - stubs */
static inline int __mojo_floordiv(int a, int b) {
    int q = a / b;
    return q - (a % b != 0 && (a ^ b) < 0);
}

#endif /* __MOJO_RUNTIME_H__ */
