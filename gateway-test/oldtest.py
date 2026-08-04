#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "requests>=2.34.2",
#     "urllib3==2.7.0",
# ]
# ///

import os
import unittest
from typing import final, override

import requests
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
    return f"{header} value"


@final
class GatewayTest(unittest.TestCase):
    @override
    @classmethod
    def setUpClass(cls) -> None:
        address = os.environ.get("GATEWAY_ADDRESS")
        if address is None:
            raise RuntimeError(
                "GATEWAY_ADDRESS must be defined in the enviroment"
            )
        cls.address = address

        host = os.environ.get("GATEWAY_HOST")
        if host is None:
            raise RuntimeError(
                "GATEWAY_HOST must be defined in the enviroment and one of: kgateway.example.com, agentgateway.example.com"
            )
        cls.host = host

    def assertClientResponseHeader(
        self, response: requests.Response, header: str
    ) -> None:
        """Assert that a header and value exist in the response to the downstream client."""
        self.assertIn(header, response.headers)
        self.assertEqual(response.headers.get(header), header_value(header))

    def assertUpstreamRequestHeader(
        self, response: requests.Response, header: str
    ):
        """Assert that a header and value exists in the request to the upstream service."""
        # These are the headers from the request to the upstream service. They are reflected back to us in the httbin /headers response. httbin Pascal-Snake cases all the header names, so we lower them all to compare. It turns all of the header values into arrays, so we have to verify that there's only one value.
        lines = response.text.splitlines()
        expected = f"{header}: {header_value(header)}"
        assert expected in lines

    def assertNoUpstreamRequestHeader(
        self,
        response: requests.Response,
        header: str,
        value: str | None = None,
    ):
        """Assert that a header does not exist in the request to the upstream service."""
        # These are the headers from the request to the upstream service. They are reflected back to us in the httbin /headers response. httbin Pascal-Snake cases all the header names, so we lower them all to compare. It turns all of the header values into arrays, so we have to verify that there's only one value.
        lines = response.text.splitlines()
        value = value or header_value(header)
        expected = f"{header}: {value}"
        assert expected not in lines

    def test_allowed(self) -> None:
        """The auth server allows a request to go through to the backend."""
        headers = {CLIENT_AUTH_HEADER: "allowed"}
        res = self.get("/headers", headers=headers)
        self.assertTrue(res.status_code, 200)

    def test_allowed_strips_original_auth_header(self) -> None:
        """The auth server strips the original auth header before sending to backend."""
        headers = {CLIENT_AUTH_HEADER: "allowed"}
        res = self.get("/headers", headers=headers)
        self.assertNoUpstreamRequestHeader(res, CLIENT_AUTH_HEADER, "allowed")

    def test_allowed_strips_original_auth_header_multiple(self) -> None:
        """The auth server strips the original auth header before sending to backend."""
        headers = [
            (CLIENT_AUTH_HEADER, "allowed"),
            (CLIENT_AUTH_HEADER, "what"),
            (CLIENT_AUTH_HEADER, "ever"),
        ]
        res = self.get_multiple("/headers", headers=headers)
        self.assertNoUpstreamRequestHeader(res, CLIENT_AUTH_HEADER, "allowed")

    def test_multiple_auth_headers_allowed(self) -> None:
        """The auth server allows the request with multiple auth headers if one of them is good."""
        headers = [
            (CLIENT_AUTH_HEADER, "allowed"),
            (CLIENT_AUTH_HEADER, "what"),
            (CLIENT_AUTH_HEADER, "ever"),
        ]
        res = self.get_multiple("/headers", headers=headers)
        self.assertEqual(res.status_code, 200)

    def test_allowed_backend_auth_header(self) -> None:
        """The auth server can inject a header into the request to the backend."""
        headers = {CLIENT_AUTH_HEADER: "allowed"}
        res = self.get("/headers", headers=headers)
        self.assertUpstreamRequestHeader(res, AUTH_UPSTREAM_HEADER_ALLOWED)

    def test_allowed_downstream_custom_auth_header(self) -> None:
        """The auth server can inject a header into the downstream response."""
        headers = {CLIENT_AUTH_HEADER: "allowed"}
        res = self.get("/headers", headers=headers)
        self.assertClientResponseHeader(res, AUTH_DOWNSTREAM_HEADER_ALLOWED)

    def get(
        self, path: str, headers: dict[str, str] | None = None
    ) -> requests.Response:
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


_ = unittest.main()
