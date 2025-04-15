from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.sql import text
import sqlalchemy as sa
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


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


async def get_expired_monitors():
    query = "SELECT * from monitor " "WHERE expires_at < strftime('%s') "
    statement = text(query)
    when = datetime.timestamp(datetime.utcnow())
    statement = sa.select(t_monitors).where(t_monitors.c.expires_at < when)
    async with get_engine().connect() as conn:
        result = await conn.execute(statement)
        print(result.fetchall())
    await get_engine().dispose()
