from .support import CLIENT_AUTH_HEADER, Client


def test_custom_denied_status(client: Client) -> None:
    """The auth server can set the client response status code when denied."""
    headers = {CLIENT_AUTH_HEADER: "custom-403"}
    res = client.get("/headers", headers=headers)
    assert res.status_code == 403


def test_custom_denied_body(client: Client) -> None:
    """The auth server can pass a custom body through a denied response."""
    headers = {CLIENT_AUTH_HEADER: "custom-403"}
    res = client.get("/headers", headers=headers)
    lines = res.text.splitlines()
    expected = "custom 403 body from auth server"
    assert expected in lines
