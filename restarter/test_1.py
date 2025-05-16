from urllib import parse

import pytest
import pytest_asyncio

from . import app, database
from .database import get_monitor_by_key, get_user_by_user_key, text


@pytest.fixture(name="test_app")
def _test_app(tmpdir):
    app.config["DATABASE"] = "test.db"
    app.config["ADMIN_KEY"] = "somethingbogus"
    app.config["SECRET_KEY"] = "sometasdihjasdhingbogus"
    return app


# Available to all tests, wraps each test execution, create/teardown the db
@pytest_asyncio.fixture(autouse=True)
async def db(test_app):

    eng = database.get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(database.meta.create_all)

    yield db

    async with eng.begin() as conn:
        await conn.run_sync(database.meta.drop_all)


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
            "email": "foo@bar.com",
            "password": "correct-hiorse-battery-stable",
        },
    )


@pytest.fixture(autouse=True)
def test_user_key():
    return "A" * 32


@pytest.fixture(autouse=True)
def test_user_key_two():
    return "Z" * 32


@pytest_asyncio.fixture
async def sample_user(db, test_user_key):
    await database.insert_user("foo@bar.com", "correct-hoarse", test_user_key)


@pytest_asyncio.fixture
async def sample_user_two(db, test_user_key_two):
    await database.insert_user("foo2@bar.com", "incorrect-hoarse", test_user_key_two)


@pytest.mark.asyncio
async def test_app(test_app):
    client = app.test_client()
    response = await client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_user_create(test_app, min_user_create_payload):
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
    test_client = test_app.test_client()
    await test_client.post("/users", **min_user_create_payload)
    response = await test_client.post("/users", **min_user_create_payload)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_monitor_create(test_app, min_create_payload, sample_user, test_user_key):
    test_client = test_app.test_client()
    # Create the monitor.
    min_create_payload["headers"]["x-user-key"] = test_user_key
    response = await test_client.post("/monitors", **min_create_payload)
    assert response.status_code == 200
    jr = await response.json
    monitor_key = parse.urlparse(jr["monitor_url"]).path.split("/")[-1]
    assert monitor_key.startswith("M")
    assert jr["name"] == "testmon"
    assert jr["report_if_not_called_in"] == 60

    mon = await get_monitor_by_key(monitor_key[1:])  # chop off the M

    assert mon is not None


@pytest.mark.asyncio
async def test_monitor_create_dupe_slug_same_user(
    test_app, min_create_payload, sample_user, test_user_key
):
    test_client = test_app.test_client()
    # Create the monitor.
    min_create_payload["headers"]["x-user-key"] = test_user_key
    response = await test_client.post("/monitors", **min_create_payload)
    response = await test_client.post("/monitors", **min_create_payload)
    assert response.status_code == 400
    assert "Monitor with this slug already exists" in (await response.json)["error"]


@pytest.mark.asyncio
async def test_monitor_create_dupe_slug_other_user(
    test_app,
    min_create_payload,
    sample_user,
    sample_user_two,
    test_user_key,
    test_user_key_two,
):
    test_client = test_app.test_client()
    # Create the monitor for user one
    min_create_payload["headers"]["x-user-key"] = test_user_key
    response = await test_client.post("/monitors", **min_create_payload)
    min_create_payload["headers"]["x-user-key"] = test_user_key_two
    response = await test_client.post("/monitors", **min_create_payload)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_monitor_create_bogus(test_app, min_create_payload, test_user_key):
    test_client = test_app.test_client()
    # Create the monitor.
    min_create_payload["headers"]["x-user-key"] = test_user_key
    min_create_payload["json"]["webhook"] = {}
    response = await test_client.post("/monitors", **min_create_payload)
    assert response.status_code == 400
    jr = await response.json
    assert "errors" in jr


@pytest.mark.asyncio
async def test_monitor_update(test_app, min_create_payload, sample_user, test_user_key):
    test_client = test_app.test_client()
    # Create the monitor.
    min_create_payload["headers"]["x-user-key"] = test_user_key
    response = await test_client.post("/monitors", **min_create_payload)
    assert response.status_code == 200
    jr = await response.json
    path = parse.urlparse(jr["monitor_url"]).path

    response = await test_client.post(
        path,
    )
    assert response.status_code == 200
    jr = await response.json
    assert jr == "Update successful"

    # Confirm it updated
    # split the path, grab only the last component, chop off the leading M
    key = path.split("/")[-1][1:]

    mon = await get_monitor_by_key(key)
    assert mon["last_check"] is not None  # because on creation it is none


@pytest.mark.asyncio
async def test_monitor_delete(test_app, min_create_payload, sample_user, test_user_key):
    test_client = test_app.test_client()
    # Create the monitor.
    min_create_payload["headers"]["x-user-key"] = test_user_key
    response = await test_client.post("/monitors", **min_create_payload)
    assert response.status_code == 200
    jr = await response.json
    path = parse.urlparse(jr["monitor_url"]).path

    dr = await test_client.delete(
        path,
        headers={"x-user-key": test_user_key},
    )

    assert dr.status_code == 200

    # Ensure dbs are empty

    async with database.get_engine().begin() as conn:
        result = await conn.execute(text("SELECT * FROM monitor"))
        assert len(result.fetchall()) == 0
        result = await conn.execute(text("SELECT * FROM webhook"))
        assert len(result.fetchall()) == 0
