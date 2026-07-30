#pragma once
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Open/close a SQLite database. Returns NULL on failure. */
void *mojo_sqlite3_open(const char *path);
void  mojo_sqlite3_close(void *db);

/* Return the last error message for this db connection. */
char *mojo_sqlite3_errmsg(void *db);

/* Execute a statement that produces no result rows (INSERT, UPDATE, CREATE, ...).
   Returns SQLITE_OK (0) on success, error code on failure. */
int64_t mojo_sqlite3_exec(void *db, const char *sql);

/* Execute a query and return results as a MojoList* of MojoList* rows.
   First row contains column names as strings.
   Each subsequent row contains the column values (int64_t, double, or char*).
   Returns NULL on failure. */
void *mojo_sqlite3_query(void *db, const char *sql);

/* Same as query but returns MojoList* of MojoDict* rows (column-name keyed).
   Returns NULL on failure. */
void *mojo_sqlite3_query_dict(void *db, const char *sql);

/* Prepared statement interface */
void   *mojo_sqlite3_prepare(void *db, const char *sql);
int64_t mojo_sqlite3_step(void *stmt);
void    mojo_sqlite3_finalize(void *stmt);

/* Bind parameters (1-indexed position) */
void mojo_sqlite3_bind_int(void *stmt, int64_t idx, int64_t val);
void mojo_sqlite3_bind_double(void *stmt, int64_t idx, double val);
void mojo_sqlite3_bind_text(void *stmt, int64_t idx, const char *val);
void mojo_sqlite3_bind_null(void *stmt, int64_t idx);

/* Column metadata (0-indexed) */
int64_t mojo_sqlite3_column_count(void *stmt);
int64_t mojo_sqlite3_column_type(void *stmt, int64_t idx);
char   *mojo_sqlite3_column_name(void *stmt, int64_t idx);

/* Column value accessors (0-indexed) */
int64_t mojo_sqlite3_column_int(void *stmt, int64_t idx);
double  mojo_sqlite3_column_double(void *stmt, int64_t idx);
char   *mojo_sqlite3_column_text(void *stmt, int64_t idx);
int64_t mojo_sqlite3_column_bytes(void *stmt, int64_t idx);

/* Last inserted row id and change count */
int64_t mojo_sqlite3_last_insert_rowid(void *db);
int64_t mojo_sqlite3_changes(void *db);

#ifdef __cplusplus
}
#endif
