#include "fire_python.h"
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>

#ifndef USE_PYTHON
#define USE_PYTHON 0
#endif

#if USE_PYTHON
#include <Python.h>
#endif

static int _python_initialised = 0;

void mojo_python_init(void)
{
#if USE_PYTHON
    if (_python_initialised) return;
    Py_Initialize();
    _python_initialised = 1;
#endif
}

void mojo_python_fini(void)
{
#if USE_PYTHON
    if (!_python_initialised) return;
    Py_Finalize();
    _python_initialised = 0;
#endif
}

void *mojo_python_import(const char *name)
{
#if USE_PYTHON
    if (!_python_initialised) mojo_python_init();
    PyObject *mod = PyImport_ImportModule(name);
    return (void *)mod;
#else
    (void)name; return NULL;
#endif
}

void *mojo_python_getattr(void *obj, const char *attr)
{
#if USE_PYTHON
    PyObject *o = (PyObject *)obj;
    PyObject *result = PyObject_GetAttrString(o, attr);
    return (void *)result;
#else
    (void)obj; (void)attr; return NULL;
#endif
}

void *mojo_python_call(void *callable, void *args)
{
#if USE_PYTHON
    PyObject *fn = (PyObject *)callable;
    PyObject *a = (PyObject *)args;
    PyObject *result = PyObject_CallObject(fn, a);
    Py_DECREF(a);
    return (void *)result;
#else
    (void)callable; (void)args; return NULL;
#endif
}

void *mojo_python_tuple_new(int64_t n)
{
#if USE_PYTHON
    PyObject *t = PyTuple_New((Py_ssize_t)n);
    return (void *)t;
#else
    (void)n; return NULL;
#endif
}

void mojo_python_tuple_set(void *tuple, int64_t i, void *val)
{
#if USE_PYTHON
    PyTuple_SetItem((PyObject *)tuple, (Py_ssize_t)i, (PyObject *)val);
#else
    (void)tuple; (void)i; (void)val;
#endif
}

void *mojo_python_from_int(int64_t v)
{
#if USE_PYTHON
    return (void *)PyLong_FromLongLong(v);
#else
    (void)v; return NULL;
#endif
}

void *mojo_python_from_double(double v)
{
#if USE_PYTHON
    return (void *)PyFloat_FromDouble(v);
#else
    (void)v; return NULL;
#endif
}

void *mojo_python_from_str(const char *v)
{
#if USE_PYTHON
    return (void *)PyUnicode_FromString(v);
#else
    (void)v; return NULL;
#endif
}

int64_t mojo_python_to_int(void *obj)
{
#if USE_PYTHON
    return (int64_t)PyLong_AsLongLong((PyObject *)obj);
#else
    (void)obj; return 0;
#endif
}

double mojo_python_to_double(void *obj)
{
#if USE_PYTHON
    return PyFloat_AsDouble((PyObject *)obj);
#else
    (void)obj; return 0.0;
#endif
}

char *mojo_python_to_str(void *obj)
{
#if USE_PYTHON
    PyObject *o = (PyObject *)obj;
    PyObject *str_obj = PyObject_Str(o);
    if (!str_obj) return NULL;
    const char *utf8 = PyUnicode_AsUTF8(str_obj);
    char *result = utf8 ? strdup(utf8) : NULL;
    Py_DECREF(str_obj);
    return result;
#else
    (void)obj; return NULL;
#endif
}

char *mojo_python_exception(void)
{
#if USE_PYTHON
    if (!PyErr_Occurred()) return NULL;
    PyObject *ptype, *pvalue, *ptraceback;
    PyErr_Fetch(&ptype, &pvalue, &ptraceback);
    PyErr_NormalizeException(&ptype, &pvalue, &ptraceback);
    PyObject *str_obj = PyObject_Str(pvalue);
    const char *utf8 = str_obj ? PyUnicode_AsUTF8(str_obj) : NULL;
    char *result = utf8 ? strdup(utf8) : NULL;
    Py_XDECREF(str_obj);
    Py_XDECREF(ptype);
    Py_XDECREF(pvalue);
    Py_XDECREF(ptraceback);
    return result;
#else
    return NULL;
#endif
}

void *mojo_python_call_func(const char *module, const char *func,
                             int64_t nargs, ...)
{
#if USE_PYTHON
    if (!_python_initialised) mojo_python_init();
    PyObject *mod = PyImport_ImportModule(module);
    if (!mod) { mojo_python_exception(); return NULL; }
    PyObject *fn = PyObject_GetAttrString(mod, func);
    Py_DECREF(mod);
    if (!fn) { mojo_python_exception(); return NULL; }
    PyObject *args = PyTuple_New((Py_ssize_t)nargs);
    if (!args) { Py_DECREF(fn); return NULL; }
    va_list ap;
    va_start(ap, nargs);
    for (int64_t i = 0; i < nargs; i++)
    {
        int64_t tag = va_arg(ap, int64_t);
        void *val = va_arg(ap, void *);
        PyObject *pyval = NULL;
        switch (tag)
        {
            case 0: pyval = PyLong_FromLongLong((int64_t)(uintptr_t)val); break;
            case 1: pyval = PyFloat_FromDouble(*(double *)&val); break;
            case 2: pyval = PyUnicode_FromString((const char *)val); break;
            case 3: pyval = (PyObject *)val; Py_XINCREF(pyval); break;
            default: break;
        }
        if (pyval) PyTuple_SetItem(args, i, pyval);
    }
    va_end(ap);
    PyObject *result = PyObject_CallObject(fn, args);
    Py_DECREF(args);
    Py_DECREF(fn);
    if (!result) { mojo_python_exception(); return NULL; }
    return (void *)result;
#else
    (void)module; (void)func; (void)nargs; return NULL;
#endif
}
