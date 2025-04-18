import logging
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.sql import text

logger = logging.getLogger(__name__)
logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)

meta = sa.MetaData()

t_monitors = sa.Table(
    "monitor",
    meta,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("slug", sa.Text, nullable=False),
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
)

sa.Index("idx_apikey_slug", t_monitors.c.api_key, t_monitors.c.slug)
sa.Index("idx_expires_at", t_monitors.c.expires_at)


def get_engine():
    from . import app

    dbfile = app.config.get("DATABASE")
    engine = create_async_engine(f"sqlite+aiosqlite:///{dbfile}", echo=True)
    return engine


async def get_monitor_by_api_key_slug(api_key, slug):
    query = "SELECT * from monitor " "WHERE api_key=:ap AND slug=:sl"
    statement = text(query)
    async with get_engine().connect() as conn:
        result = await conn.execute(statement, {"ap": api_key, "sl": slug})
        r = result.mappings().fetchone()
    return r


async def get_expired_monitors():
    query = "SELECT * from monitor " "WHERE expires_at < strftime('%s') "
    statement = text(query)
    when = datetime.timestamp(datetime.utcnow())
    statement = sa.select(t_monitors).where(t_monitors.c.expires_at < when)
    async with get_engine().connect() as conn:
        result = await conn.execute(statement)
        print([{"name": r.name, "exp": r.expires_at} for r in result.fetchall()])
        # result.mappings().fetchall() returns a traditional list of dicts

    await get_engine().dispose()


async def update_monitor(slug, apikey):
    query = (
        "UPDATE monitor SET last_check=:now, "
        "expires_at=:now_ts + frequency "
        "WHERE api_key=:apikey AND slug=:slug "
        "RETURNING id"
    )
    statement = text(query)

    now_ts = datetime.now().timestamp()
    async with get_engine().begin() as conn:
        result = await conn.execute(
            statement,
            {"now": datetime.now(), "apikey": apikey, "slug": slug, "now_ts": now_ts},
        )

        value = result.fetchone()
        if value:
            id = value.id
        else:
            id = None
        return id


async def insert_monitor(name, api_key, frequency, slug):
    query = (
        "INSERT INTO monitor (name, api_key, frequency, slug, expires_at) "
        "VALUES (:na, :ak, :fr, :ms, :ea) returning id"
    )
    statement = text(query)
    async with get_engine().begin() as conn:
        result = await conn.execute(
            statement,
            {
                "na": name,
                "ak": api_key,
                "fr": frequency,
                "ms": slug,
                "ea": datetime.now().timestamp() + frequency,
            },
        )
        the_id = result.fetchone().id
    await get_engine().dispose()
    return the_id


async def insert_webhook(monitor_id, url, method, headers, form_fields, body_payload):
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
