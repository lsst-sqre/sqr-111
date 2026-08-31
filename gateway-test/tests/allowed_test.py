from .support import (
    CLIENT_AUTH_HEADER,
    Client,
    assert_not_upstream_request_header,
)


def test_allowed(client: Client) -> None:
    """The auth server allows a request to go through to the backend."""
    headers = {CLIENT_AUTH_HEADER: "allowed"}
    res = client.get("/headers", headers=headers)
    assert res.status_code == 200


def test_allowed_strips_original_auth_header(client: Client) -> None:
    """The auth server strips the original auth header before sending to backend."""
    headers = {CLIENT_AUTH_HEADER: "allowed"}
    res = client.get("/headers", headers=headers)
    assert_not_upstream_request_header(res, CLIENT_AUTH_HEADER, "allowed")
