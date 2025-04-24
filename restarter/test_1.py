from urllib import parse

import pytest
import random

from . import app, init_db
from .database import get_monitor_by_api_key_slug, get_user_by_user_key


@pytest.fixture(name="test_app")
def _test_app(tmpdir):
    app.config["DATABASE"] = "test.db"
    app.config["ADMIN_KEY"] = "somethingbogus"
    return app


@pytest.fixture
def min_create_payload(test_app):
    return dict(
        headers={},
        json={
            "frequency": 60,
            "name": "testmon",
            "slug": "testslug",
            "webhook": {"url": "https://foo2.com", "method": "post"},
        },
    )


@pytest.fixture
def min_user_create_payload(test_app):
    return dict(
        headers={"x-admin-key": test_app.config["ADMIN_KEY"]},
        json={
            # FIXME: This makes tests nondeterministic, fix this to instead
            # clean up the database after each test
            "email": "foo@bar.com" + str(random.randint(10, 100)),
            "password": "correct-hiorse-battery-stable",
        },
    )


@pytest.mark.asyncio
async def test_app(test_app):
    client = app.test_client()
    response = await client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_user_create(test_app, min_user_create_payload):
    await init_db()
    test_client = test_app.test_client()
    response = await test_client.post("/users", **min_user_create_payload)
    assert response.status_code == 200
    jr = await response.json

    assert jr["email"] == min_user_create_payload["json"]["email"]
    assert "argon" in jr["password"]
    assert "user_key" in jr

    mon = await get_user_by_user_key(jr["user_key"])

    assert mon is not None


@pytest.mark.asyncio
async def test_user_create_dupe_email(test_app, min_user_create_payload):
    await init_db()
    test_client = test_app.test_client()
    await test_client.post("/users", **min_user_create_payload)
    response = await test_client.post("/users", **min_user_create_payload)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_monitor_create(test_app, min_create_payload, min_user_create_payload):
    await init_db()
    test_client = test_app.test_client()
    # FIXME: Create the user. This should be a fixture.
    response = await test_client.post("/users", **min_user_create_payload)
    jr = await response.json

    user_key = jr["user_key"]
    # Create the monitor.
    min_create_payload["headers"]["x-user-key"] = user_key
    response = await test_client.post("/monitors", **min_create_payload)
    assert response.status_code == 200
    jr = await response.json
    assert parse.urlparse(jr["monitor_url"]).path == "/monitor/testslug"
    assert jr["name"] == "testmon"
    assert jr["report_if_not_called_in"] == 60
    assert "api_key" in jr

    mon = await get_monitor_by_api_key_slug(jr["api_key"], "testslug")

    assert mon is not None


@pytest.mark.asyncio
async def test_monitor_create_bogus(
    test_app, min_create_payload, min_user_create_payload
):
    await init_db()
    test_client = test_app.test_client()
    # Create the user. This should be a fixture.
    response = await test_client.post("/users", **min_user_create_payload)
    jr = await response.json

    user_key = jr["user_key"]
    # Create the monitor.
    min_create_payload["headers"]["x-user-key"] = user_key
    min_create_payload["json"]["webhook"] = {}
    response = await test_client.post("/monitors", **min_create_payload)
    assert response.status_code == 400
    jr = await response.json
    assert "errors" in jr


@pytest.mark.asyncio
async def test_monitor_update(test_app, min_create_payload, min_user_create_payload):
    await init_db()
    test_client = test_app.test_client()
    # Create the user. This should be a fixture.
    response = await test_client.post("/users", **min_user_create_payload)
    jr = await response.json

    user_key = jr["user_key"]
    # Create the monitor.
    min_create_payload["headers"]["x-user-key"] = user_key
    response = await test_client.post("/monitors", **min_create_payload)
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


@pytest.mark.asyncio
async def test_monitor_update_bad_user_key(
    test_app, min_create_payload, min_user_create_payload
):
    await init_db()
    test_client = test_app.test_client()
    # Create the user. This should be a fixture.
    response = await test_client.post("/users", **min_user_create_payload)
    jr = await response.json

    user_key = jr["user_key"]
    # Create the monitor.
    min_create_payload["headers"]["x-user-key"] = user_key
    response = await test_client.post("/monitors", **min_create_payload)
    jr = await response.json
    api_key = jr["api_key"]
    path = parse.urlparse(jr["monitor_url"]).path

    response = await test_client.post(
        path,
        headers={"x-api-key": "whatevs dude"},
    )
    assert response.status_code == 404
    # Confirm it did not update
    mon = await get_monitor_by_api_key_slug(api_key, "testslug")
    assert mon["last_check"] is None
