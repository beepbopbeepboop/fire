# COMPILE_FAIL: Doc/tools/extensions/audit_events.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/audit_events.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_AuditEvent_set_source_info", referenced from:
      _AuditEvent_run in audit_events.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 10.55s
