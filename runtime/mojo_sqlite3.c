#include "mojo_sqlite3.h"
#include "mojo_runtime.h"
#include <sqlite3.h>
#include <stdlib.h>
#include <string.h>

void *mojo_sqlite3_open(const char *path)
{
    sqlite3 *db = NULL;
    int rc = sqlite3_open(path, &db);
    if (rc != SQLITE_OK) { if (db) sqlite3_close(db); return NULL; }
    return (void *)db;
}

void mojo_sqlite3_close(void *db)
{
    if (db) sqlite3_close((sqlite3 *)db);
}

char *mojo_sqlite3_errmsg(void *db)
{
    if (!db) return NULL;
    return strdup(sqlite3_errmsg((sqlite3 *)db));
}

int64_t mojo_sqlite3_exec(void *db, const char *sql)
{
    char *err = NULL;
    int rc = sqlite3_exec((sqlite3 *)db, sql, NULL, NULL, &err);
    if (err) sqlite3_free(err);
    return (int64_t)rc;
}

void *mojo_sqlite3_query(void *db, const char *sql)
{
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2((sqlite3 *)db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) return NULL;

    int ncol = sqlite3_column_count(stmt);
    void *rows = mojo_list_new();

    /* Emit column names as first row (must strdup — sqlite3_column_name
       returns internal pointer that becomes invalid after sqlite3_finalize). */
    void *header = mojo_list_new();
    for (int i = 0; i < ncol; i++)
    {
        const char *name = sqlite3_column_name(stmt, i);
        if (name) mojo_list_append_str(header, strdup(name));
        else      mojo_list_append_str(header, strdup("?"));
    }
    mojo_list_append_str(rows, (char *)header);

    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW)
    {
        void *row = mojo_list_new();
        for (int i = 0; i < ncol; i++)
        {
            int col_type = sqlite3_column_type(stmt, i);
            switch (col_type)
            {
                case SQLITE_INTEGER:
                    mojo_list_append_int(row, sqlite3_column_int64(stmt, i));
                    break;
                case SQLITE_FLOAT:
                    {
                        double dv = sqlite3_column_double(stmt, i);
                        int64_t iv;
                        memcpy(&iv, &dv, sizeof(iv));
                        mojo_list_append_int(row, iv);
                    }
                    break;
                case SQLITE_TEXT:
                    {
                        const char *txt = (const char *)sqlite3_column_text(stmt, i);
                        mojo_list_append_str(row, txt ? strdup(txt) : NULL);
                    }
                    break;
                case SQLITE_NULL:
                    mojo_list_append_int(row, 0);
                    break;
                case SQLITE_BLOB:
                    {
                        const void *blob = sqlite3_column_blob(stmt, i);
                        int len = sqlite3_column_bytes(stmt, i);
                        char *copy = malloc((size_t)len + 1);
                        memcpy(copy, blob, (size_t)len);
                        copy[len] = '\0';
                        mojo_list_append_str(row, copy);
                        free(copy);
                    }
                    break;
            }
        }
        mojo_list_append_str(rows, (char *)row);
    }
    sqlite3_finalize(stmt);
    return rows;
}

void *mojo_sqlite3_query_dict(void *db, const char *sql)
{
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2((sqlite3 *)db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) return NULL;

    int ncol = sqlite3_column_count(stmt);
    void *rows = mojo_list_new();

    /* Collect column names (strdup — sqlite3_column_name returns internal ptr) */
    char **col_names = (char **)malloc(sizeof(char *) * (size_t)ncol);
    for (int i = 0; i < ncol; i++)
    {
        const char *name = sqlite3_column_name(stmt, i);
        col_names[i] = name ? strdup(name) : strdup("?");
    }

    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW)
    {
        void *dict = mojo_dict_new();
        for (int i = 0; i < ncol; i++)
        {
            int col_type = sqlite3_column_type(stmt, i);
            switch (col_type)
            {
                case SQLITE_INTEGER:
                    mojo_dict_set_int(dict, col_names[i],
                                      (int64_t)sqlite3_column_int64(stmt, i));
                    break;
                case SQLITE_FLOAT:
                    mojo_dict_set_double(dict, col_names[i],
                                         sqlite3_column_double(stmt, i));
                    break;
                case SQLITE_TEXT:
                    {
                        const char *txt = (const char *)sqlite3_column_text(stmt, i);
                        mojo_dict_set_str(dict, col_names[i], txt ? strdup(txt) : NULL);
                    }
                    break;
                case SQLITE_NULL:
                    mojo_dict_set_int(dict, col_names[i], 0);
                    break;
                case SQLITE_BLOB:
                    {
                        const void *blob = sqlite3_column_blob(stmt, i);
                        int len = sqlite3_column_bytes(stmt, i);
                        char *copy = malloc((size_t)len + 1);
                        memcpy(copy, blob, (size_t)len);
                        copy[len] = '\0';
                        mojo_dict_set_str(dict, col_names[i], copy);
                        free(copy);
                    }
                    break;
            }
        }
        /* Store dict pointer as int64_t */
        mojo_list_append_int(rows, (int64_t)(int64_t *)dict);
    }

    for (int i = 0; i < ncol; i++) free(col_names[i]);
    free(col_names);
    sqlite3_finalize(stmt);
    return rows;
}

void *mojo_sqlite3_prepare(void *db, const char *sql)
{
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2((sqlite3 *)db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) return NULL;
    return (void *)stmt;
}

int64_t mojo_sqlite3_step(void *stmt)
{
    return (int64_t)sqlite3_step((sqlite3_stmt *)stmt);
}

void mojo_sqlite3_finalize(void *stmt)
{
    sqlite3_finalize((sqlite3_stmt *)stmt);
}

void mojo_sqlite3_bind_int(void *stmt, int64_t idx, int64_t val)
{
    sqlite3_bind_int64((sqlite3_stmt *)stmt, (int)idx, (sqlite3_int64)val);
}

void mojo_sqlite3_bind_double(void *stmt, int64_t idx, double val)
{
    sqlite3_bind_double((sqlite3_stmt *)stmt, (int)idx, val);
}

void mojo_sqlite3_bind_text(void *stmt, int64_t idx, const char *val)
{
    sqlite3_bind_text((sqlite3_stmt *)stmt, (int)idx, val, -1, SQLITE_TRANSIENT);
}

void mojo_sqlite3_bind_null(void *stmt, int64_t idx)
{
    sqlite3_bind_null((sqlite3_stmt *)stmt, (int)idx);
}

int64_t mojo_sqlite3_column_count(void *stmt)
{
    return (int64_t)sqlite3_column_count((sqlite3_stmt *)stmt);
}

int64_t mojo_sqlite3_column_type(void *stmt, int64_t idx)
{
    return (int64_t)sqlite3_column_type((sqlite3_stmt *)stmt, (int)idx);
}

char *mojo_sqlite3_column_name(void *stmt, int64_t idx)
{
    return strdup(sqlite3_column_name((sqlite3_stmt *)stmt, (int)idx));
}

int64_t mojo_sqlite3_column_int(void *stmt, int64_t idx)
{
    return (int64_t)sqlite3_column_int64((sqlite3_stmt *)stmt, (int)idx);
}

double mojo_sqlite3_column_double(void *stmt, int64_t idx)
{
    return sqlite3_column_double((sqlite3_stmt *)stmt, (int)idx);
}

char *mojo_sqlite3_column_text(void *stmt, int64_t idx)
{
    const char *txt = (const char *)sqlite3_column_text((sqlite3_stmt *)stmt, (int)idx);
    return txt ? strdup(txt) : NULL;
}

int64_t mojo_sqlite3_column_bytes(void *stmt, int64_t idx)
{
    return (int64_t)sqlite3_column_bytes((sqlite3_stmt *)stmt, (int)idx);
}

int64_t mojo_sqlite3_last_insert_rowid(void *db)
{
    return (int64_t)sqlite3_last_insert_rowid((sqlite3 *)db);
}

int64_t mojo_sqlite3_changes(void *db)
{
    return (int64_t)sqlite3_changes((sqlite3 *)db);
}
