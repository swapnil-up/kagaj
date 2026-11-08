"""Passive observation of Nepal's public-sector web infrastructure.

The package measures hostname, hosting, DNS, TLS and HTTP behaviour of
``.gov.np`` sites using only ordinary public requests. It never scans ports,
probes for vulnerabilities, or bypasses robots.txt.
"""

from . import paths

__all__ = ["paths"]
