"""Production entry point: serve the API on $PORT over IPv4 and IPv6 at once.

Hosts differ (Railway's private network is IPv6 in some environments, IPv4 in
others, and health checks may use either). uvicorn binds one address, and
binding "::" through asyncio is IPv6-only, so bind a dual-stack socket here
and hand it over; fall back to IPv4 where the container has no IPv6.
"""

from __future__ import annotations

import os
import socket

import uvicorn


def _listening_socket(port: int) -> socket.socket:
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("::", port))
    except OSError:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
    return sock


def main() -> None:
    sock = _listening_socket(int(os.environ.get("PORT", "8000")))
    uvicorn.Server(uvicorn.Config("app.main:app", fd=sock.fileno(), proxy_headers=True)).run()


if __name__ == "__main__":
    main()
