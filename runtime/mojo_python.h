#pragma once
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Initialise and finalise the CPython interpreter.
   Must be called before any other mojo_python_* function.
   Safe to call multiple times (subsequent calls are no-ops). */
void mojo_python_init(void);
void mojo_python_fini(void);

/* Import a Python module by name. Returns NULL on failure. */
void *mojo_python_import(const char *name);

/* Get an attribute from a Python object. Returns NULL on failure. */
void *mojo_python_getattr(void *obj, const char *attr);

/* Call a callable Python object with positional args tuple.
   `args` must be a PyTuple* created via mojo_python_tuple_new.
   Returns NULL on failure. */
void *mojo_python_call(void *callable, void *args);

/* Create a new empty tuple with `n` slots. */
void *mojo_python_tuple_new(int64_t n);

/* Set the i-th element of a tuple to `val`. `val` must be a PyObject*.
   The tuple steals a reference to `val`. */
void mojo_python_tuple_set(void *tuple, int64_t i, void *val);

/* Convert our native types to Python objects.
   Returns NULL on failure. */
void *mojo_python_from_int(int64_t v);
void *mojo_python_from_double(double v);
void *mojo_python_from_str(const char *v);

/* Convert Python objects to our native types. */
int64_t   mojo_python_to_int(void *obj);
double    mojo_python_to_double(void *obj);
char *    mojo_python_to_str(void *obj);

/* Convenience: import module, getattr, pack args, call, return result.
   `nargs` is the number of positional args; they follow as (int64_t, void*)
   pairs where the int64_t is a type tag (0=int, 1=double, 2=str, 3=obj)
   and the void* is the value (cast to void* for scalars, or a PyObject*).
   Returns NULL on failure (use mojo_python_exception to get details). */
void *mojo_python_call_func(const char *module, const char *func,
                             int64_t nargs, ...);

/* Retrieve the current Python exception info.
   Returns a string like "ZeroDivisionError: division by zero",
   or NULL if no exception is set. The returned string must be freed. */
char *mojo_python_exception(void);

#ifdef __cplusplus
}
#endif
