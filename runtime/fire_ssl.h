#pragma once
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* SSL context — opaque handle. Create once, reuse for multiple connections. */
void *mojo_ssl_context_new(void);
void  mojo_ssl_context_free(void *ctx);

/* SSL connection — wraps a connected socket fd. */
void *mojo_ssl_new(void *ctx, int64_t fd);
void  mojo_ssl_free(void *ssl);
int64_t mojo_ssl_connect(void *ssl);
int64_t mojo_ssl_accept(void *ssl);

/* Read/write — returns bytes read/written, or negative on error. */
int64_t mojo_ssl_read(void *ssl, char *buf, int64_t size);
int64_t mojo_ssl_write(void *ssl, const char *buf, int64_t len);

/* Return the last error string. Caller must free. */
char *mojo_ssl_error(void *ssl);

/* Version string. Caller must free. */
char *mojo_ssl_version(void);

/* Certificate verification. */
int64_t mojo_ssl_set_verify_none(void *ssl);
int64_t mojo_ssl_set_verify_peer(void *ssl);

/* Hostname verification. Returns 0 on success. */
int64_t mojo_ssl_set_hostname(void *ssl, const char *name);

#ifdef __cplusplus
}
#endif
