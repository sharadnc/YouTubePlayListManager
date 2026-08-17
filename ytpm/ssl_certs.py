"""
PURPOSE:
    Make HTTPS (OAuth + YouTube API) trust the OS certificate store.

INTERNAL LOGIC:
    Python 3.12 on Windows uses OpenSSL, not the Windows CA store, so corporate
    proxies and some ISP TLS inspection fail with CERTIFICATE_VERIFY_FAILED.
    truststore.inject_into_ssl() uses the platform store. Call once at process
    start, before google-auth / requests first open a socket.

EXAMPLE INVOCATION:
    from ytpm.ssl_certs import configure_ssl
    configure_ssl()
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_configured: bool = False


def configure_ssl() -> None:
    """
    PURPOSE:
        Inject the OS certificate store into the stdlib ssl module.

    INTERNAL LOGIC:
        import truststore; inject_into_ssl(). Idempotent.

    EXAMPLE INVOCATION:
        configure_ssl()
    """
    global _configured
    if _configured:
        return
    try:
        import truststore

        truststore.inject_into_ssl()
        logger.info("TLS: using OS certificate store via truststore")
    except Exception as exc:
        logger.warning("Could not inject OS CA store (%s); HTTPS may fail", exc)
    _configured = True
