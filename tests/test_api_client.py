import json

import httpx
import pytest
import respx

from productbot.api_client import ApiError, SiteApiClient

B = "https://shop.test"


@pytest.fixture
async def client(site):
    c = SiteApiClient(site)
    yield c
    await c.aclose()


@respx.mock
async def test_login_sends_body_and_bearer(client):
    login = respx.post(f"{B}/api/auth.php").respond(json={"success": True, "token": "T1"})
    up = respx.post(f"{B}/api/admin/upload.php").respond(json={"success": True, "path": "assets/a.jpg"})
    assert await client.upload_image(b"x", "a.jpg", "image/jpeg") == "assets/a.jpg"
    assert json.loads(login.calls[0].request.content) == {"action": "login", "username": "bot", "password": "pw"}
    assert up.calls[0].request.headers["authorization"] == "Bearer T1"


@respx.mock
async def test_relogin_on_401(client):
    respx.post(f"{B}/api/auth.php").mock(side_effect=[
        httpx.Response(200, json={"token": "OLD"}), httpx.Response(200, json={"token": "NEW"})])
    create = respx.post(f"{B}/api/admin/products.php").mock(side_effect=[
        httpx.Response(401, json={"error": "Invalid or expired token"}),
        httpx.Response(200, json={"success": True, "product_id": 7})])
    res = await client.create_product({"name": "x"})
    assert res.id == "7"
    assert create.calls[1].request.headers["authorization"] == "Bearer NEW"


@respx.mock
async def test_login_failure(client):
    respx.post(f"{B}/api/auth.php").respond(401, json={"error": "Invalid credentials"})
    with pytest.raises(ApiError, match="Invalid credentials"):
        await client.create_product({})


@respx.mock
async def test_create_error_message(client):
    respx.post(f"{B}/api/auth.php").respond(json={"token": "T"})
    respx.post(f"{B}/api/admin/products.php").respond(400, json={"error": "Field 'price' is required"})
    with pytest.raises(ApiError, match="price"):
        await client.create_product({})


@respx.mock
async def test_fetch_options_excludes(client, site):
    respx.post(f"{B}/api/auth.php").respond(json={"token": "T"})
    respx.get(f"{B}/api/products.php").respond(json=[
        {"id": "all", "name": "Todos"}, {"id": "feminino", "name": "Feminino"}])
    spec = next(f for f in site.fields if f.key == "category").options_from
    assert await client.fetch_options(spec) == [("feminino", "Feminino")]


@respx.mock
async def test_network_error_message(client):
    respx.post(f"{B}/api/auth.php").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(ApiError, match="rede"):
        await client.login()
