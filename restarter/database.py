import logging
from datetime import datetime, UTC
import json

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.exc import IntegrityError, NoResultFound  # noqa
from sqlalchemy.sql import text


logger = logging.getLogger(__name__)

meta = sa.MetaData()


engine = None


def get_engine():
    from . import app

    global engine

    if not engine:
        dbfile = app.config.get("DATABASE")
        engine = create_async_engine(f"sqlite+aiosqlite:///{dbfile}", echo=False)
    return engine


def utcnow():
    return datetime.now(UTC)


t_users = sa.Table(
    "user",
    meta,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("email", sa.Text, nullable=False, unique=True),
    sa.Column("password", sa.Text, nullable=False),
    sa.Column("user_key", sa.Text, nullable=False),
    sa.Column("deleted_at", sa.DateTime),
    sa.Column("created_at", sa.DateTime, default=datetime.now),
    sa.Column(
        "updated_at", sa.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    ),
)
t_monitors = sa.Table(
    "monitor",
    meta,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id"), nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("slug", sa.Text, nullable=False, unique=True),
    sa.Column("frequency", sa.Integer, nullable=False),
    sa.Column("expires_at", sa.Integer, nullable=False),
    sa.Column("api_key", sa.Text, nullable=False),
    sa.Column("last_check", sa.DateTime, nullable=True),
)

t_webhooks = sa.Table(
    "webhook",
    meta,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("monitor_id", sa.Integer, sa.ForeignKey("monitor.id"), nullable=False),
    sa.Column("url", sa.Text, nullable=False),
    sa.Column("method", sa.Text, nullable=False),
    sa.Column("headers", sa.Text, nullable=True),
    sa.Column("form_fields", sa.Text, nullable=True),
    sa.Column("body_payload", sa.Text, nullable=True),
    sa.Column("created_at", sa.DateTime, default=datetime.utcnow),
    sa.Column(
        "updated_at", sa.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    ),
    sa.Column(
        "last_called", sa.Integer
    ),  # timestamp of last time we called this webhook
)

sa.Index("idx_apikey_slug", t_monitors.c.api_key, t_monitors.c.slug)
sa.Index("idx_expires_at", t_monitors.c.expires_at)


async def get_monitor_by_api_key_slug(api_key, slug):
    query = "SELECT * from monitor " "WHERE api_key=:ap AND slug=:sl"
    statement = text(query)
    async with get_engine().connect() as conn:
        result = await conn.execute(statement, {"ap": api_key, "sl": slug})
        r = result.mappings().fetchone()
    return r


async def get_monitors_by_user_id(uid):
    query = "SELECT * from monitor LEFT JOIN webhook on monitor.id=webhook.monitor_id WHERE user_id=:uid"
    statement = text(query)
    async with get_engine().connect() as conn:
        result = await conn.execute(statement, {"uid": uid})
        r = result.mappings().fetchall()
    print(r)
    return r


async def get_user_by_user_key(user_key):
    query = "SELECT * from user WHERE user_key=:uk"
    statement = text(query)
    async with get_engine().connect() as conn:
        result = await conn.execute(statement, {"uk": user_key})
        r = result.mappings().fetchone()
    return r


async def get_user_by_user_id(user_id):
    query = "SELECT * from user WHERE id=:ui"
    statement = text(query)
    async with get_engine().connect() as conn:
        result = await conn.execute(statement, {"ui": user_id})
        r = result.mappings().fetchone()
    return r


async def get_user_by_email(email):
    query = "SELECT * from user WHERE email=:em"
    statement = text(query)
    async with get_engine().connect() as conn:
        result = await conn.execute(statement, {"em": email})
        r = result.mappings().one()
    return r


async def get_expired_monitors():
    when = datetime.timestamp(datetime.now(UTC))
    query = (
        "SELECT monitor.id as mid,webhook.id as wid,webhook.url,"
        "webhook.method,webhook.headers, "
        "webhook.form_fields, webhook.body_payload "
        "FROM monitor LEFT JOIN webhook ON  monitor.id=webhook.monitor_id "
        "WHERE expires_at < :when"
    )
    statement = text(query)
    # statement = sa.select(t_monitors).where(t_monitors.c.expires_at < when)
    async with get_engine().connect() as conn:
        result = await conn.execute(statement, {"when": when})
        expimon = result.mappings().fetchall()
        # result.mappings().fetchall() returns a traditional list of dicts

    await get_engine().dispose()
    return expimon


async def update_monitor(slug, apikey):
    query = (
        "UPDATE monitor SET last_check=:now, "
        "expires_at=:now_ts + frequency "
        "WHERE api_key=:apikey AND slug=:slug "
        "RETURNING monitor.id"
    )
    statement = text(query)

    now_ts = datetime.now(UTC).timestamp()
    async with get_engine().begin() as conn:
        result = await conn.execute(
            statement,
            {
                "now": datetime.now(UTC),
                "apikey": apikey,
                "slug": slug,
                "now_ts": now_ts,
            },
        )

        value = result.fetchone()
        if value:
            # Reset last_called for all my webhooks
            id = value.id
            wh_query = "UPDATE webhook SET last_called=NULL WHERE monitor_id=:id"
            wh_statement = text(wh_query)
            await conn.execute(wh_statement, {"id": id})

        else:
            id = None

        return id


async def insert_monitor(user_id, name, api_key, frequency, slug):
    query = (
        "INSERT INTO monitor (user_id, name, api_key, frequency, slug, expires_at) "
        "VALUES (:ui, :na, :ak, :fr, :ms, :ea) returning id"
    )
    statement = text(query)
    async with get_engine().begin() as conn:
        try:
            result = await conn.execute(
                statement,
                {
                    "ui": user_id,
                    "na": name,
                    "ak": api_key,
                    "fr": frequency,
                    "ms": slug,
                    "ea": datetime.now(UTC).timestamp() + frequency,
                },
            )
        except IntegrityError:
            return None
        the_id = result.fetchone().id
    await get_engine().dispose()
    return the_id


async def insert_webhook(monitor_id, url, method, headers, form_fields, body_payload):
    # headers, form_fields, body_payload must be json-encoded
    headers = json.dumps(headers)
    form_fields = json.dumps(form_fields)
    body_payload = json.dumps(body_payload)
    query = (
        "INSERT INTO webhook (monitor_id, url, method, headers, "
        "form_fields, body_payload) "
        "VALUES (:mi, :url, :me, :he, :fo, :bo) returning id"
    )
    statement = text(query)
    async with get_engine().begin() as conn:
        result = await conn.execute(
            statement,
            {
                "mi": monitor_id,
                "url": url,
                "me": method,
                "he": headers,
                "fo": form_fields,
                "bo": body_payload,
            },
        )
        the_id = result.fetchone().id
    await get_engine().dispose()
    return the_id


async def get_webhook_to_hit_by_id(wh_id):
    query = "SELECT * from webhook WHERE id=:wh_id AND last_called IS NULL"
    statement = text(query)
    async with get_engine().connect() as conn:
        result = await conn.execute(statement, {"wh_id": wh_id})
        r = result.mappings().fetchone()
    await get_engine().dispose()
    return r


async def touch_webhook_by_id(wid):
    now_ts = datetime.now(UTC).timestamp()
    query = "UPDATE webhook SET last_called=:now_ts " "WHERE id=:wid "
    statement = text(query)

    async with get_engine().begin() as conn:
        await conn.execute(
            statement,
            {"now_ts": now_ts, "wid": wid},
        )
    await get_engine().dispose()


async def delete_monitor_and_webhooks_by_slug_user_key(slug, user_key):
    print(slug, user_key)
    async with get_engine().begin() as conn:
        query = (
            "DELETE FROM webhook WHERE monitor_id in "
            "(SELECT monitor.id FROM user left join monitor on user.id=monitor.user_id "
            "WHERE slug=:slug AND user_key=:user_key)"
        )
        statement = text(query)
        await conn.execute(statement, {"slug": slug, "user_key": user_key})
        query = (
            "DELETE FROM monitor WHERE id in "
            "(SELECT monitor.id FROM user left join monitor on user.id=monitor.user_id "
            "WHERE slug=:slug AND user_key=:user_key) RETURNING id"
        )
        statement = text(query)
        result = await conn.execute(statement, {"slug": slug, "user_key": user_key})
        value = result.fetchone()
        if value:
            return value.id
        else:
            return None
    await get_engine().dispose()


async def insert_user(email, password_crypted, user_key):
    query = (
        "INSERT INTO user (email, password, user_key) "
        "VALUES (:em, :pw, :uk) returning *"
    )
    statement = text(query)
    async with get_engine().begin() as conn:
        try:
            result = await conn.execute(
                statement,
                {"em": email, "pw": password_crypted, "uk": user_key},
            )
        except IntegrityError:
            return None

        the_user = result.mappings().fetchone()
    await get_engine().dispose()
    return the_user
