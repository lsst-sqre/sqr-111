from typing import final

import requests

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
    response: requests.Response, header: str
) -> None:
    """Assert that a header exists in the response to the downstream client."""
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
    lines = response.text.splitlines()
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
