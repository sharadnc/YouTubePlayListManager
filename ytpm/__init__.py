"""
PURPOSE:
    YouTube Playlist Manager (YTPM) package root.

INTERNAL LOGIC:
    Exposes package version for CLI/GUI banners.

EXAMPLE INVOCATION:
    import ytpm
    print(ytpm.__version__)
"""

__version__: str = "1.0.0"

from ytpm.ssl_certs import configure_ssl

configure_ssl()
