import base64
import json

import httpx
import pytest
import respx

from productbot.whatsapp import LIST_GROUPS_TIMEOUT, EvolutionClient, WhatsAppError

B = "https://evo.test"


@pytest.fixture
async def wa(app_config):
    c = EvolutionClient(app_config.whatsapp)
    yield c
    await c.aclose()


def test_config_strips_trailing_slash(app_config):
    assert app_config.whatsapp.base_url == B
    assert app_config.whatsapp.instance == "loja"


@respx.mock
async def test_send_image(wa):
    route = respx.post(f"{B}/message/sendMedia/loja").respond(201, json={"key": {}})
    await wa.send_image("120363@g.us", b"\x89PNG", "image/png", "p.png", "legenda")
    req = route.calls[0].request
    assert req.headers["apikey"] == "K"
    body = json.loads(req.content)
    assert body == {"number": "120363@g.us", "mediatype": "image", "mimetype": "image/png",
                    "fileName": "p.png", "media": base64.b64encode(b"\x89PNG").decode(), "caption": "legenda"}


@respx.mock
async def test_send_image_without_caption(wa):
    route = respx.post(f"{B}/message/sendMedia/loja").respond(201, json={})
    await wa.send_image("g@g.us", b"x", "image/jpeg", "p.jpg")
    assert "caption" not in json.loads(route.calls[0].request.content)


@respx.mock
async def test_send_text(wa):
    route = respx.post(f"{B}/message/sendText/loja").respond(201, json={})
    await wa.send_text("g@g.us", "olá")
    assert json.loads(route.calls[0].request.content) == {"number": "g@g.us", "text": "olá"}


@respx.mock
async def test_list_groups(wa):
    route = respx.get(f"{B}/group/fetchAllGroups/loja").respond(
        json=[{"id": "1@g.us", "subject": "Clientes"}, {"id": "2@g.us"}, {"nope": 1}])
    assert await wa.list_groups() == [("1@g.us", "Clientes"), ("2@g.us", "")]
    assert route.calls[0].request.url.params["getParticipants"] == "false"
    assert route.calls[0].request.extensions["timeout"]["read"] == LIST_GROUPS_TIMEOUT


@respx.mock
@pytest.mark.parametrize("body, expected", [
    ({"message": "Instance not connected"}, "WhatsApp: Instance not connected"),
    ({"response": {"message": ["a", "b"]}}, "WhatsApp: a; b"),
    (None, "WhatsApp: HTTP 500"),
])
async def test_http_error(wa, body, expected):
    route = respx.post(f"{B}/message/sendText/loja")
    route.respond(500, json=body) if body else route.respond(500, text="boom")
    with pytest.raises(WhatsAppError) as e:
        await wa.send_text("g@g.us", "x")
    assert str(e.value) == expected


@respx.mock
async def test_timeout_has_specific_message(wa):
    route = respx.post(f"{B}/message/sendText/loja").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(WhatsAppError, match="não respondeu a tempo"):
        await wa.send_text("g@g.us", "x")
    assert route.call_count == 1


@respx.mock
async def test_network_error_no_retry(wa):
    route = respx.post(f"{B}/message/sendText/loja").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(WhatsAppError, match="gateway"):
        await wa.send_text("g@g.us", "x")
    assert route.call_count == 1
