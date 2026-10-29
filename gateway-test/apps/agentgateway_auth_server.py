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

This needs to be paired with the agentgateway gateway controller.
"""

import asyncio
import json
import logging
from typing import Annotated, cast, override

import uvicorn
from fastapi import FastAPI, Header, Request, Response
from uvicorn.protocols.http.h11_impl import H11Protocol

ALLOWED_VALUE = "allowed"
"""Authorization header value to allow the request through."""

CUSTOM_403_VALUE = "custom-403"
"""Authorization header value to trigger a 403 response from the auth server."""

CUSTOM_401_VALUE = "custom-401"
"""Authorization header value to trigger a 401 response from the auth server."""

AUTH_DOWNSTREAM_HEADER_DENIED = "x-auth-to-client-denied"
"""Header set by auth server in response to downstream client for denied requests."""

AUTH_DOWNSTREAM_HEADER_ALLOWED = "x-auth-to-client-allowed"
"""Header set by auth server in response to downstream client for allowed requests."""

AUTH_UPSTREAM_HEADER_ALLOWED = "x-auth-to-upstream-allowed"
"""Header set by auth server in request to upstream server for allowed requests."""


app = FastAPI()
logger = logging.getLogger("uvicorn.error")


class RawH11Protocol(H11Protocol):
    """Store the raw request from the wire so we can use it in a handler.

    This is based on some LLM vibes.
    """

    @override
    def connection_made(self, transport: asyncio.Transport) -> None:
        self._raw_request = bytearray()  # type: ignore
        super().connection_made(transport)

    @override
    def data_received(self, data: bytes) -> None:
        # Capture exactly what arrived before Uvicorn/h11 parses it.
        self._raw_request.extend(data)

        super().data_received(data)

        # The ASGI scope is created once h11 has parsed the request line
        # and headers. Keep a reference to the mutable bytearray so later
        # body reads are included too. This is a hack and violates the type of
        # self.scope, which is a typed dict.
        self.scope["raw_request"] = self._raw_request  # type: ignore


def clean_cookies(headers: list[str]) -> list[str]:
    """This is what Gafaelfawr currently does to strip its own cookie.

    Parameters
    ----------
    headers
        The ``Cookie`` headers of an incoming request, as a list (allowing for
        the case that the incoming request had multiple headers named
        ``Cookie``).

    Returns
    -------
    list of str
        Any remaining ``Cookie`` headers after removing auth server cookies.
    """
    output = []
    for header in headers:
        keep = []
        for cookie in header.split("; "):
            if "=" in cookie:
                name, _ = cookie.split("=", 1)
                if name != "filterme":
                    keep.append(cookie)
            else:
                keep.append(cookie)
        if keep:
            output.append("; ".join(keep))
    logger.info("output: %r", output)
    return output


def value(header: str) -> str:
    """Construct a unique value for a header name."""
    return f"{header} value"


@app.get("/ingress/auth{destination_path:path}")
async def auth(
    request: Request,
    destination_path: str,  # type: ignore
    x_auth_authorization_values: Annotated[str | None, Header()] = None,
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
    logger.info("x-auth-authorization-values: %r", x_auth_authorization_values)

    authorization: list[str]
    if x_auth_authorization_values:
        authorization = json.loads(x_auth_authorization_values)
    else:
        authorization = []
    logger.info("authorization: %r", authorization)

    if request.headers.get("x-delay-auth") == "true":
        # Agentgateway has a default timeout of 2s for an external auth request.
        # If that is exceeded, it responds 403.
        await asyncio.sleep(1.5)

    if not authorization:
        reason = "custom 401 body no auth header"
        body = f"{reason}\n{raw_request}"
        status = 401
        return Response(
            status_code=status,
            content=body,
            headers={
                AUTH_DOWNSTREAM_HEADER_DENIED: value(
                    AUTH_DOWNSTREAM_HEADER_DENIED
                ),
            },
        )
    elif len(authorization) > 1:
        # This is what ingress-nginx does. But agentgateway will only send the
        # first Authorization header if multiple are specified, so in practice,
        # we will only get one here.
        body = f"Only one authorization header allowed\n{raw_request}"
        return Response(
            status_code=400,
            content=body,
            headers={
                AUTH_DOWNSTREAM_HEADER_DENIED: value(
                    AUTH_DOWNSTREAM_HEADER_DENIED
                ),
            },
        )

    elif CUSTOM_403_VALUE in authorization:
        reason = "custom 403 body from auth server"
        body = f"{reason}\n{raw_request}"
        status = 403
        return Response(
            status_code=status,
            content=body,
            headers={
                AUTH_DOWNSTREAM_HEADER_DENIED: value(
                    AUTH_DOWNSTREAM_HEADER_DENIED
                ),
            },
        )
    elif CUSTOM_401_VALUE in authorization:
        reason = "custom 401 body from auth server"
        body = f"{reason}\n{raw_request}"
        status = 401
        return Response(
            status_code=status,
            content=body,
            headers={
                AUTH_DOWNSTREAM_HEADER_DENIED: value(
                    AUTH_DOWNSTREAM_HEADER_DENIED
                ),
            },
        )
    elif ALLOWED_VALUE in authorization:
        remaining_auth = authorization.copy()
        remaining_auth.remove(ALLOWED_VALUE)
        headers: dict[str, str] = {
            AUTH_DOWNSTREAM_HEADER_ALLOWED: value(
                AUTH_DOWNSTREAM_HEADER_ALLOWED
            ),
            AUTH_UPSTREAM_HEADER_ALLOWED: value(AUTH_UPSTREAM_HEADER_ALLOWED),
        }

        response = Response(
            status_code=200,
            content=f"custom 200 body from auth server\n{raw_request}",
            headers=headers,
        )
        for val in remaining_auth:
            response.headers.append("Authorization", val)

        cleaned_cookie_headers = []
        if "Cookie" in request.headers:
            raw_cookies = request.headers.getlist("Cookie")
            cookies = clean_cookies(raw_cookies)
            cleaned_cookie_headers.extend(
                ("x-auth-cookie-to-upstream", v) for v in cookies
            )
        if not cleaned_cookie_headers:
            response.headers["x-auth-cookie-to-upstream"] = ""
        else:
            for k, v in cleaned_cookie_headers:
                response.headers.append(k, v)

        logger.info("response headers: %r", response.headers)
        return response

    reason = "custom 401 body unauthorized"
    body = f"{reason}\n{raw_request}"
    status = 401
    return Response(
        status_code=status,
        content=body,
        headers={
            AUTH_DOWNSTREAM_HEADER_DENIED: value(
                AUTH_DOWNSTREAM_HEADER_DENIED
            ),
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
