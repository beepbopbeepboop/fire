#pragma once
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Compression levels */
#define MOJO_ZLIB_DEFAULT_COMPRESSION (-1)
#define MOJO_ZLIB_BEST_SPEED   1
#define MOJO_ZLIB_BEST_COMPRESSION 9

/* Returned MojoList* elements for compressed/decompressed output:
 *   [0] = int64_t (length of compressed data)
 *   [1] = char *  (the compressed/decompressed bytes as a string)
 *   or NULL on failure. */

/* Compress a buffer. Returns MojoList*[len, data] or NULL. */
void *mojo_zlib_compress(const char *data, int64_t len, int64_t level);

/* Decompress a buffer. Returns MojoList*[len, data] or NULL. */
void *mojo_zlib_decompress(const char *data, int64_t len);

/* Compress to gzip format. Returns MojoList*[len, data] or NULL. */
void *mojo_zlib_gzip_compress(const char *data, int64_t len, int64_t level);

/* Decompress from gzip format. Returns MojoList*[len, data] or NULL. */
void *mojo_zlib_gzip_decompress(const char *data, int64_t len);

/* CRC-32 checksum */
int64_t mojo_zlib_crc32(int64_t crc, const char *data, int64_t len);

/* Adler-32 checksum */
int64_t mojo_zlib_adler32(int64_t adler, const char *data, int64_t len);

#ifdef __cplusplus
}
#endif
