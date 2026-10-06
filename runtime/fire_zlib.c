#include "fire_zlib.h"
#include "fire_runtime.h"
#include <zlib.h>
#include <stdlib.h>
#include <string.h>

static void *_result_list(const void *data, int64_t len)
{
    void *lst = mojo_list_new();
    mojo_list_append_int(lst, len);
    char *copy = malloc((size_t)len);
    if (copy) { memcpy(copy, data, (size_t)len); }
    mojo_list_append_str(lst, copy);
    free(copy);
    return lst;
}

void *mojo_zlib_compress(const char *data, int64_t len, int64_t level)
{
    uLongf dest_len = compressBound((uLong)len);
    char *dest = (char *)malloc(dest_len);
    if (!dest) return NULL;
    int rc = compress2((Bytef *)dest, &dest_len, (const Bytef *)data, (uLong)len, (int)level);
    if (rc != Z_OK) { free(dest); return NULL; }
    void *result = _result_list(dest, (int64_t)dest_len);
    free(dest);
    return result;
}

void *mojo_zlib_decompress(const char *data, int64_t len)
{
    /* Guess decompressed size: 4x input is a reasonable starting point */
    uLongf dest_len = (uLongf)len * 4 + 1024;
    char *dest = (char *)malloc(dest_len);
    if (!dest) return NULL;
    int rc = uncompress((Bytef *)dest, &dest_len, (const Bytef *)data, (uLong)len);
    if (rc == Z_OK) {
        void *result = _result_list(dest, (int64_t)dest_len);
        free(dest);
        return result;
    }
    /* If buffer too small, try with a larger buffer */
    if (rc == Z_BUF_ERROR) {
        dest_len = dest_len * 4;
        char *bigger = (char *)realloc(dest, dest_len);
        if (!bigger) { free(dest); return NULL; }
        rc = uncompress((Bytef *)bigger, &dest_len, (const Bytef *)data, (uLong)len);
        if (rc == Z_OK) {
            void *result = _result_list(bigger, (int64_t)dest_len);
            free(bigger);
            return result;
        }
    }
    free(dest);
    return NULL;
}

void *mojo_zlib_gzip_compress(const char *data, int64_t len, int64_t level)
{
    uLongf dest_len = compressBound((uLong)len) + 32;
    char *dest = (char *)malloc(dest_len);
    if (!dest) return NULL;
    /* Write gzip header manually */
    z_stream strm;
    memset(&strm, 0, sizeof(strm));
    int rc = deflateInit2(&strm, (int)level, Z_DEFLATED, 15 + 16, 8, Z_DEFAULT_STRATEGY);
    if (rc != Z_OK) { free(dest); return NULL; }
    strm.next_in = (Bytef *)data;
    strm.avail_in = (uInt)len;
    strm.next_out = (Bytef *)dest;
    strm.avail_out = (uInt)dest_len;
    rc = deflate(&strm, Z_FINISH);
    if (rc != Z_STREAM_END) { deflateEnd(&strm); free(dest); return NULL; }
    int64_t out_len = (int64_t)strm.total_out;
    deflateEnd(&strm);
    void *result = _result_list(dest, out_len);
    free(dest);
    return result;
}

void *mojo_zlib_gzip_decompress(const char *data, int64_t len)
{
    z_stream strm;
    memset(&strm, 0, sizeof(strm));
    int rc = inflateInit2(&strm, 15 + 16);
    if (rc != Z_OK) return NULL;
    uLongf dest_len = (uLongf)len * 4 + 1024;
    char *dest = (char *)malloc(dest_len);
    if (!dest) { inflateEnd(&strm); return NULL; }
    strm.next_in = (Bytef *)data;
    strm.avail_in = (uInt)len;
    strm.next_out = (Bytef *)dest;
    strm.avail_out = (uInt)dest_len;
    rc = inflate(&strm, Z_FINISH);
    if (rc == Z_STREAM_END || rc == Z_OK) {
        int64_t out_len = (int64_t)strm.total_out;
        inflateEnd(&strm);
        void *result = _result_list(dest, out_len);
        free(dest);
        return result;
    }
    inflateEnd(&strm);
    free(dest);
    return NULL;
}

int64_t mojo_zlib_crc32(int64_t crc, const char *data, int64_t len)
{
    return (int64_t)crc32((uLong)crc, (const Bytef *)data, (uInt)len);
}

int64_t mojo_zlib_adler32(int64_t adler, const char *data, int64_t len)
{
    return (int64_t)adler32((uLong)adler, (const Bytef *)data, (uInt)len);
}
