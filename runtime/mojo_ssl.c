#include "mojo_ssl.h"
#include <openssl/ssl.h>
#include <openssl/err.h>
#include <openssl/crypto.h>
#include <stdlib.h>
#include <string.h>

static int _ssl_initialised = 0;

static void _ssl_ensure_init(void)
{
    if (_ssl_initialised) return;
    SSL_load_error_strings();
    OpenSSL_add_all_algorithms();
    _ssl_initialised = 1;
}

void *mojo_ssl_context_new(void)
{
    _ssl_ensure_init();
    SSL_CTX *ctx = SSL_CTX_new(TLS_client_method());
    return (void *)ctx;
}

void mojo_ssl_context_free(void *ctx)
{
    if (ctx) SSL_CTX_free((SSL_CTX *)ctx);
}

void *mojo_ssl_new(void *ctx, int64_t fd)
{
    SSL *ssl = SSL_new((SSL_CTX *)ctx);
    if (!ssl) return NULL;
    SSL_set_fd(ssl, (int)fd);
    return (void *)ssl;
}

void mojo_ssl_free(void *ssl)
{
    if (ssl) SSL_free((SSL *)ssl);
}

int64_t mojo_ssl_connect(void *ssl)
{
    int rc = SSL_connect((SSL *)ssl);
    return (int64_t)rc;
}

int64_t mojo_ssl_accept(void *ssl)
{
    int rc = SSL_accept((SSL *)ssl);
    return (int64_t)rc;
}

int64_t mojo_ssl_read(void *ssl, char *buf, int64_t size)
{
    int rc = SSL_read((SSL *)ssl, buf, (int)size);
    return (int64_t)rc;
}

int64_t mojo_ssl_write(void *ssl, const char *buf, int64_t len)
{
    int rc = SSL_write((SSL *)ssl, buf, (int)len);
    return (int64_t)rc;
}

char *mojo_ssl_error(void *ssl)
{
    unsigned long err = ERR_get_error();
    if (err == 0 && ssl)
    {
        int ssl_err = SSL_get_error((SSL *)ssl, 0);
        switch (ssl_err)
        {
            case SSL_ERROR_NONE: return strdup("none");
            case SSL_ERROR_WANT_READ: return strdup("want read");
            case SSL_ERROR_WANT_WRITE: return strdup("want write");
            case SSL_ERROR_ZERO_RETURN: return strdup("connection closed");
            default: break;
        }
    }
    char buf[256];
    ERR_error_string_n(err, buf, sizeof(buf));
    return strdup(buf);
}

char *mojo_ssl_version(void)
{
    return strdup(OpenSSL_version(OPENSSL_VERSION));
}

int64_t mojo_ssl_set_verify_none(void *ssl)
{
    SSL_set_verify((SSL *)ssl, SSL_VERIFY_NONE, NULL);
    return 0;
}

int64_t mojo_ssl_set_verify_peer(void *ssl)
{
    SSL_set_verify((SSL *)ssl, SSL_VERIFY_PEER, NULL);
    return 0;
}

int64_t mojo_ssl_set_hostname(void *ssl, const char *name)
{
    return (int64_t)SSL_set_tlsext_host_name((SSL *)ssl, name);
}
