from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter
from typing import final

import requests

# Yeah this is private, but we need it for sending multiple of the same header
from urllib3._collections import HTTPHeaderDict

CLIENT_AUTH_HEADER = "authorization"
"""Downstream client request header that the auth server checks to authorize."""

AUTH_DOWNSTREAM_HEADER_DENIED = "x-auth-to-client-denied"
"""Header set by auth server in response to downstream client for denied requests."""

AUTH_DOWNSTREAM_HEADER_ALLOWED = "x-auth-to-client-allowed"
"""Header set by auth server in response to downstream client for allowed requests."""

AUTH_UPSTREAM_HEADER_ALLOWED = "x-auth-to-upstream-allowed"
"""Header set by auth server in request to upstream server for allowed requests."""


def header_value(header: str) -> str:
    """Make a unique value for the given header."""
    return f"{header} value"


def assert_client_response_header(
    response: requests.Response, header: str, value: str | None = None
) -> None:
    """Assert that a header exists in the response to the downstream client."""
    value = value or header_value(header)
    assert header, response.headers
    assert response.headers.get(header) == header_value(header)


def assert_upstream_request_header(
    response: requests.Response, header: str, value: str | None = None
):
    """Assert that a header exists in the request to the upstream service."""
    # These are the headers from the request to the upstream service. They are
    # reflected back to us in the echo-server response, which includes the raw
    # HTTP request in its response.
    value = value or header_value(header)
    lines = [line.lower() for line in response.text.splitlines()]
    expected = f"{header}: {value}"
    assert expected in lines, f"{expected} NOT found in {lines}"


def assert_not_upstream_request_header(
    response: requests.Response, header: str, value: str | None = None
):
    """Assert that a header is NOT in the request to the upstream service."""
    # These are the headers from the request to the upstream service. They are
    # reflected back to us in the echo-server response, which includes the raw
    # HTTP request in its response.
    value = value or header_value(header)
    lines = response.text.splitlines()
    expected = f"{header}: {value}"
    assert expected not in lines, f"{expected} FOUND in {lines}"


@final
class Client:
    """A tool for making requests via different Gateways in a KIND cluster."""

    def __init__(self, address: str, host: str) -> None:
        self.address = address
        self.host = host

    def get(
        self, path: str, headers: dict[str, str] | None = None
    ) -> requests.Response:
        """Make a get request via the configured gateway/ingress."""
        headers = headers or {}
        headers = headers | {"host": self.host}
        url = f"http://{self.address}{path}"
        return requests.get(url, headers=headers)

    def get_multiple(
        self, path: str, headers: list[tuple[str, str]] | None = None
    ) -> requests.Response:
        """Send a request where the same header can appear multiple times.

        This will add separate lines in the request for each header, rather
        than collapsing into one line with a comma-separated value.
        """
        url = f"http://{self.address}{path}"
        request = requests.Request("GET", url)
        prepared = request.prepare()
        headers = headers or []
        header_dict = HTTPHeaderDict(prepared.headers)
        header_dict.add("host", self.host)
        for header, value in headers:
            header_dict.add(header, value)
        prepared.headers = header_dict
        with requests.Session() as session:
            return session.send(prepared)


@dataclass
class Timer:
    """A container for holding an elapsed time."""

    elapsed: float = 0.0


@contextmanager
def timed() -> Generator[Timer]:
    """Time a section of code.

    Yields a Timer object that has the elapsed time at the end of the block.
    """
    timer = Timer()
    start = perf_counter()
    try:
        yield timer
    finally:
        timer.elapsed = perf_counter() - start
