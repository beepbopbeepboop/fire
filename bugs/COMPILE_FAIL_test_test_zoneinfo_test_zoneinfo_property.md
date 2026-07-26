# COMPILE_FAIL: Lib/test/test_zoneinfo/test_zoneinfo_property.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/test_zoneinfo_property.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_CZoneInfoCacheTest_assertIs", referenced from:
      _CZoneInfoCacheTest_test_cache in test_zoneinfo_property.o
  "_CZoneInfoCacheTest_assertIsNot", referenced from:
      _CZoneInfoCacheTest_test_no_cache in test_zoneinfo_property.o
  "_CZoneInfoCacheTest_klass", referenced from:
      _CZoneInfoCacheTest_test_cache in test_zoneinfo_property.o
      _CZoneInfoCacheTest_test_cache in test_zoneinfo_property.o
  "_CZoneInfoPickleTest_addCleanup", referenced from:
      _CZoneInfoPickleTest_setUp in test_zoneinfo_property.o
  "_CZoneInfoPickleTest_assertEqual", referenced from:
      _CZoneInfoPickleTest_test_pickle_unpickle_no_cache in test_zoneinfo_property.o
      _CZoneInfoPickleTest_test_pickle_unpickle_cache_multiple_rounds in test_zoneinfo_property.o
      _CZoneInfoPickleTest_test_pickle_unpickle_cache_multiple_rounds in test_zoneinfo_property.o
      _CZoneInfoPickleTest_test_pickle_unpickle_no_cache_multiple_rounds in test_zoneinfo_property.o
      _CZoneInfoPickleTest_test_pickle_unpickle_no_cache_multiple_rounds in test_zoneinfo_property.o
  "_CZoneInfoPickleTest_assertIs", referenced from:
      _CZoneInfoPickleTest_test_pickle_unpickle_cache in test_zoneinfo_property.o
      _CZoneInfoPickleTest_test_pickle_unpickle_cache_multiple_rounds in test_zoneinfo_property.o
      _CZoneInfoPickleTest_test_pickle_unpickle_cache_multiple_rounds in test_zoneinfo_property.o
      _CZoneInfoPickleTest_test_pickle_unpickle_cache_multiple_rounds in test_zoneinfo_property.o
  "_CZoneInfoPickleTest_assertIsNot", referenced from:
      _CZoneInfoPickleTest_test_pickle_unpickle_no_cache in test_zoneinfo_property.o
      _CZoneInfoPickleTest_test_pickle_unpickle_no_cache_multiple_rounds in test_zoneinfo_property.o
      _CZoneInfoPickleTest_test_pickle_unpickle_no_cache_multiple_rounds in test_zoneinfo_property.o
      _CZoneInfoPickleTest_test_pickle_unpickle_no_cache_multiple_rounds in test_zoneinfo_property.o
      _CZoneInfoPickleTest_test_pickle_unpickle_no_cache_multiple_rounds in test_zoneinfo_property.o
      _CZoneInfoPickleTest_test_pickle_unpickle_no_cache_multiple_rounds in test_zoneinfo_property.o
      _CZoneInfoPickleTest_test_pickle_unpickle_no_cache_multiple_rounds in test_zoneinfo_property.o
      ...
  "_CZoneInfoPickleTest_klass", referenced from:
      _CZoneInfoPickleTest_test_pickle_unpickle_cache in test_zoneinfo_property.o
      _CZoneInfoPickleTest_test_pickle_unpickle_cache_multiple_rounds in test_zoneinfo_property.o
      _CZoneInfoPickleTest_test_pickle_unpickle_no_cache_multiple_rounds in test_zoneinfo_property.o
  "_CZoneInfoTest_assertEqual", referenced from:
      _CZoneInfoTest_test_str in test_zoneinfo_property.o
      _CZoneInfoTest_test_key in test_zoneinfo_property.o
      _CZoneInfoTest_test_utc in test_zoneinfo_property.o
      _CZoneInfoTest_test_utc in test_zoneinfo_property.o
      _CZoneInfoTest_test_utc in test_zoneinfo_property.o
  "_CZoneInfoTest_klass", referenced from:
      _CZoneInfoTest_test_str in test_zoneinfo_property.o
      _CZoneInfoTest_test_key in test_zoneinfo_property.o
      _CZoneInfoTest_test_utc in test_zoneinfo_property.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 15.55s
