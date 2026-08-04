#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "uvicorn==0.52.2",
#     "fastapi==0.141.1",
# ]
# ///
"""An echo server that prints the raw request in the response."""

import asyncio
import logging
from typing import cast

import uvicorn
from fastapi import FastAPI, Request, Response
from uvicorn.protocols.http.h11_impl import H11Protocol


class RawH11Protocol(H11Protocol):
    """Store the raw request from the wire so we can use it in a handler.

    This is based on some LLM vibes.
    """

    def connection_made(self, transport: asyncio.Transport) -> None:
        """Create a buffer to capture raw request bytes."""
        self._raw_request = bytearray()
        super().connection_made(transport)

    def data_received(self, data: bytes) -> None:
        """Capture exactly what arrived before Uvicorn/h11 parses it."""
        self._raw_request.extend(data)

        super().data_received(data)

        # The ASGI scope is created once h11 has parsed the request line
        # and headers. Keep a reference to the mutable bytearray so later
        # body reads are included too. This is a hack and violates the type of
        # self.scope, which is a typed dict.
        self.scope["raw_request"] = self._raw_request  # type: ignore

    def on_response_complete(self) -> None:
        """Clear our raw request bytes buffer."""
        super().on_response_complete()

        # The next request on this keep-alive connection gets a fresh buffer.
        self._raw_request = bytearray()


app = FastAPI()
logger = logging.getLogger("uvicorn.error")


@app.get("{path:path}")
async def auth(
    request: Request,
    path: str,  # type: ignore
) -> Response:
    """Return the decoded bytes of the raw request.

    We want to do this at the lowest level to see how exactly the gateway
    external auth implementation constructs the request to the upstream,
    before it gets parsed by the various layers (Starlette, FastAPI, etc).
    """
    # Wait until the complete request body, if any, has arrived.
    _ = await request.body()

    # Get the raw request that we inject with our Uvicorn hack
    raw_bytes = cast("bytearray", request.scope["raw_request"])
    raw_request = bytes(raw_bytes).decode()
    logger.info("raw request: %r", raw_request)
    raw_request = f"Raw request to the upstream:\n{raw_request}"

    return Response(
        status_code=200,
        content=raw_request,
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
