# CODEGEN_frozendict_fromkeys: `cls(dict.fromkeys(iterable, value))` emits invalid gimple call

**Status:** NEW

## Repro

```
cd ~/net/gcc-fire/gcc  # or ~/net/gcc/gcc/fire/fire
python3 ../../gcc/gcc/fire/fire/fire.py ../../gcc/gcc/fire/fire/fire.py --dump-full
# -> fire.ci
sed -i '' 's/^int main/int mojo_main/' fire.ci
gcc-mp-15 -Os -g -fgimple -ftrivial-auto-var-init=zero -I../../gcc/gcc/fire/fire/runtime -c -x c fire.ci -o fire.o
```

## Error

```
/Users/mrs/net/gcc/gcc/fire/fire/myinterpreter.py: In function 'myinterpreter_frozendict_fromkeys':
/Users/mrs/net/gcc/gcc/fire/fire/myinterpreter.py:3316:44: error: expected expression before '(' token
 3316 |             return cls(dict.fromkeys(iterable, value))
      |                                            ^
...
<<< error >>>
_t17 = mojo_dict_fromkeys (_t2, _t16, 0, <<< error >>>);
...
make: *** [fire.o] Error 1
```

The generated call `_t17 = mojo_dict_fromkeys(_t2, _t16, 0, <<< error >>>);` has an invalid argument where the value expression should be, indicating the codegen failed to lower `value` (or the whole `cls(...)` call) in `frozendict.fromkeys`.

## Location

`myinterpreter.py:3316` — `myinterpreter_frozendict_fromkeys`.
