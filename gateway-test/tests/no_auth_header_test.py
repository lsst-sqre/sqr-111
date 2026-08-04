from .support import (
    AUTH_DOWNSTREAM_HEADER_DENIED,
    Client,
    assert_client_response_header,
)


def test_status(client: Client) -> None:
    """A request with no auth header returns 401."""
    res = client.get("/headers")
    assert res.status_code == 401


def test_body(client: Client) -> None:
    """A request with no auth header returns body from auth server response."""
    res = client.get("/headers")
    lines = res.text.splitlines()
    expected = "custom 401 body no auth header"
    assert expected in lines


def test_denied_sends_custom_header(client: Client) -> None:
    """A denied response contains a custom header from the auth server."""
    res = client.get("/headers")
    assert_client_response_header(res, AUTH_DOWNSTREAM_HEADER_DENIED)
