#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "uvicorn==0.52.2",
#     "fastapi==0.141.1",
# ]
# ///
"""
An "auth server" that lets us deterministically trigger different responses.

It is intended to mimic Gafaelfawr in the simplest way possible:
https://gafaelfawr.lsst.io/

We dig into Uvicorn internals so that we can capture the raw request. FastAPI
provides no way to get the raw request, and doing it with the built-in Python
http.server webserver was even nastier than this.
"""

import asyncio
import logging
from typing import Annotated, cast

import uvicorn
from fastapi import FastAPI, Header, Request, Response
from uvicorn.protocols.http.h11_impl import H11Protocol

ALLOWED_VALUE = "allowed"

CUSTOM_403_VALUE = "custom-403"

CUSTOM_401_VALUE = "custom-401"

AUTH_DOWNSTREAM_HEADER_DENIED = "x-auth-to-client-denied"
"""Header set by auth server in response to downstream client for denied requests."""

AUTH_DOWNSTREAM_HEADER_ALLOWED = "x-auth-to-client-allowed"
"""Header set by auth server in response to downstream client for allowed requests."""

AUTH_UPSTREAM_HEADER_ALLOWED = "x-auth-to-upstream-allowed"
"""Header set by auth server in request to upstream server for allowed requests."""

AUTH_ERROR_BODY = "x-error-body"
"""Header set by auth server to pass the auth response body through to ingress-nginx.

This is only needed and used by ingress-nginx.
"""

AUTH_ERROR_STATUS = "x-error-status"
"""Header set by auth server to pass the auth response status through to ingress-nginx.

This is only needed and used by ingress-nginx.
"""
app = FastAPI()
logger = logging.getLogger("uvicorn.error")


class RawH11Protocol(H11Protocol):
    """Store the raw request from the wire so we can use it in a handler.

    This is based on some LLM vibes.
    """

    def connection_made(self, transport: asyncio.Transport) -> None:
        self._raw_request = bytearray()
        super().connection_made(transport)

    def data_received(self, data: bytes) -> None:
        # Capture exactly what arrived before Uvicorn/h11 parses it.
        self._raw_request.extend(data)

        super().data_received(data)

        # The ASGI scope is created once h11 has parsed the request line
        # and headers. Keep a reference to the mutable bytearray so later
        # body reads are included too. This is a hack and violates the type of
        # self.scope, which is a typed dict.
        self.scope["raw_request"] = self._raw_request  # type: ignore


def value(header: str) -> str:
    """Construct a unique value for a header name."""
    return f"{header} value"


@app.get("/ingress/auth{destination_path:path}")
async def auth(
    request: Request,
    destination_path: str,  # type: ignore
    authorization: Annotated[list[str] | None, Header()] = None,
) -> Response:
    """Return different auth responses.

    Also log the decoded bytes of the raw request. We want to do this at the
    lowest level to see how exactly the gateway external auth implementation
    constructs the request to the auth server, before it gets parsed by the
    various layers (Starlette, FastAPI, etc).
    """
    # Wait until the complete request body, if any, has arrived.
    _ = await request.body()

    # Get the raw request that we inject with our Uvicorn hack
    raw_bytes = cast("bytearray", request.scope["raw_request"])
    raw_request = bytes(raw_bytes).decode()
    logger.info("raw request: %r", raw_request)
    raw_request = f"raw request to auth server:\n{raw_request}"

    if authorization is None:
        reason = "custom 401 body no auth header"
        body = f"{reason}\n{raw_request}"
        status = 401
        return Response(
            status_code=status,
            content=body,
            headers={
                AUTH_DOWNSTREAM_HEADER_DENIED: value(AUTH_DOWNSTREAM_HEADER_DENIED),
                AUTH_ERROR_BODY: reason,
                AUTH_ERROR_STATUS: str(status),
            },
        )
    elif CUSTOM_403_VALUE in authorization:
        reason = "custom 403 body from auth server"
        body = f"{reason}\n{raw_request}r"
        status = 403
        return Response(
            status_code=status,
            content=body,
            headers={
                AUTH_DOWNSTREAM_HEADER_DENIED: value(AUTH_DOWNSTREAM_HEADER_DENIED),
                AUTH_ERROR_BODY: reason,
                AUTH_ERROR_STATUS: str(status),
            },
        )
    elif CUSTOM_401_VALUE in authorization:
        reason = "custom 401 body from auth server"
        body = f"{reason}\n{raw_request}r"
        status = 401
        return Response(
            status_code=status,
            content=body,
            headers={
                AUTH_DOWNSTREAM_HEADER_DENIED: value(AUTH_DOWNSTREAM_HEADER_DENIED),
                AUTH_ERROR_BODY: reason,
                AUTH_ERROR_STATUS: str(status),
            },
        )
    elif ALLOWED_VALUE in authorization:
        remaining_auth = authorization.copy()
        remaining_auth.remove(ALLOWED_VALUE)
        headers: dict[str, str] = {
            AUTH_DOWNSTREAM_HEADER_ALLOWED: value(AUTH_DOWNSTREAM_HEADER_ALLOWED),
            AUTH_UPSTREAM_HEADER_ALLOWED: value(AUTH_UPSTREAM_HEADER_ALLOWED),
        }

        response = Response(
            status_code=200,
            content=f"custom 200 body from auth server\n{raw_request}r",
            headers=headers,
        )
        for val in remaining_auth:
            response.headers.append("Authorization", val)
        return response
    else:
        body = f"custom 401 body no auth header\n{raw_request}"
        return Response(
            status_code=401,
            content=body,
            headers={
                AUTH_DOWNSTREAM_HEADER_DENIED: value(AUTH_DOWNSTREAM_HEADER_DENIED),
                AUTH_ERROR_BODY: body,
            },
        )


def main() -> None:
    """Start the patched Uvicorn server."""
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8000,
        http=RawH11Protocol,
    )
    server = uvicorn.Server(config)
    server.run()


if __name__ == "__main__":
    main()
