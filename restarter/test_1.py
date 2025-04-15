from urllib import parse

import pytest

from . import app, init_db
from .database import get_monitor_by_api_key_slug


@pytest.fixture(name="test_app")
def _test_app(tmpdir):
    app.config["DATABASE"] = "test.db"
    app.config["ADMIN_KEY"] = "somethingbogus"
    return app


@pytest.mark.asyncio
async def test_app(test_app):
    client = app.test_client()
    response = await client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_monitor_create(test_app):
    await init_db()
    test_client = test_app.test_client()
    response = await test_client.post(
        "/monitors",
        headers={"x-admin-key": test_app.config["ADMIN_KEY"]},
        json={"frequency": 60, "name": "testmon", "slug": "testslug"},
    )
    assert response.status_code == 200
    jr = await response.json
    assert parse.urlparse(jr["monitor_url"]).path == "/monitor/testslug"
    assert jr["name"] == "testmon"
    assert jr["report_if_not_called_in"] == 60
    assert "api_key" in jr

    mon = await get_monitor_by_api_key_slug(jr["api_key"], "testslug")

    assert mon is not None


@pytest.mark.asyncio
async def test_monitor_update(test_app):
    await init_db()
    test_client = test_app.test_client()
    response = await test_client.post(
        "/monitors",
        headers={"x-admin-key": test_app.config["ADMIN_KEY"]},
        json={"frequency": 60, "name": "testmon", "slug": "testslug"},
    )
    jr = await response.json
    api_key = jr["api_key"]
    path = parse.urlparse(jr["monitor_url"]).path

    response = await test_client.post(
        path,
        headers={"x-api-key": api_key},
    )
    assert response.status_code == 200
    jr = await response.json
    assert jr == "Update successful"

    # Confirm it updated
    mon = await get_monitor_by_api_key_slug(api_key, "testslug")
    assert mon["last_check"] is not None  # because on creation it is none
