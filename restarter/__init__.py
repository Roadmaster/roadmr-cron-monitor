import logging
import random
import re
import string
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from quart import Quart, Response, current_app, g, request
from quart_schema import (
    QuartSchema,
    RequestSchemaValidationError,
    validate_request,
)

app = Quart(__name__)
app.logger.setLevel(logging.INFO)
logging.basicConfig()
QuartSchema(app)

CHECK_SCHED = 10


app.config.from_prefixed_env(prefix="FLYRESTARTER")


# Unused
async def _connect_db():
    engine = await aiosqlite.connect(app.config.get("DATABASE", "restarter-data.db"))
    engine.row_factory = aiosqlite.Row
    return engine


# Unused
async def _get_db():
    if not hasattr(g, "sqlite_db"):
        g.sqlite_db = await _connect_db()
    return g.sqlite_db


@app.before_serving
async def init_db():
    app.logger.info("Initializing db")
    dbfile = app.config.get("DATABASE", "restarter-data.db")

    async with aiosqlite.connect(dbfile) as db:
        await db.set_trace_callback(app.logger.info)
        with open(Path(app.root_path) / "schema.sql", mode="r") as file_:
            await db.executescript(file_.read())
            await db.commit()
    app.logger.info("Setup complete, serving")


@dataclass
class MonitorIn:
    name: str  # Descriptive name
    slug: str  # URLifiable slug
    frequency: int  # Alert if last_check + frequency > now()

    def __post_init__(self):
        if len(self.name) > 255:
            raise ValueError("name must be 255 characters or less")
        if self.frequency < 60 or self.frequency > 2592000:
            raise ValueError("frequency must be between 60 seconds and 30 days")
        if not re.fullmatch(r"[^-][a-z0-9-]{1,32}", self.slug):
            raise ValueError("slug must be a-z0-9 max 32 chars")


@dataclass
class Monitor(MonitorIn):
    id: int
    last_check: datetime | None
    expires_at: int  # in epoch seconds
    api_key: str


async def get_expired_monitors():
    query = "SELECT * from monitor " "WHERE expires_at < strftime('%s') "

    dbfile = app.config.get("DATABASE", "restarter-data.db")
    async with aiosqlite.connect(dbfile) as db:
        await db.set_trace_callback(app.logger.info)
        db.row_factory = aiosqlite.Row
        async with db.execute(
            query,
            {},
        ) as result:
            values = await result.fetchall()
    print([dict(r) for r in values])


# non async
async def check_things():
    app.logger.info("Checking service")
    await get_expired_monitors()
    print("WAHAHOO")


# Start the scheduler
scheduler = AsyncIOScheduler()
scheduler.add_job(check_things, "interval", seconds=CHECK_SCHED)
scheduler.start()


def run() -> None:
    app.run()


@app.errorhandler(RequestSchemaValidationError)
async def handle_request_validation_error(error):
    return {
        "errors": str(error.validation_error),
    }, 400


@app.get("/")
async def root():
    return "Hi there, I'm the flyrestarter"


@app.get("/health")
async def health():
    return {"health": "good!"}


async def update_monitor(slug, apikey):
    query = (
        "UPDATE monitor SET last_check=:now, "
        "expires_at=:now_ts + frequency "
        "WHERE api_key=:apikey AND slug=:slug "
        "RETURNING id"
    )

    now_ts = datetime.now().timestamp()
    dbfile = app.config.get("DATABASE", "restarter-data.db")
    async with aiosqlite.connect(dbfile) as db:
        await db.set_trace_callback(app.logger.info)
        db.row_factory = aiosqlite.Row
        async with db.execute(
            query,
            {"now": datetime.now(), "apikey": apikey, "slug": slug, "now_ts": now_ts},
        ) as result:
            value = await result.fetchone()
            await db.commit()
        if value:
            id = value["id"]
        else:
            id = None
    return id


@app.post("/monitor/<string:monitor_slug>")
async def monitor_update(monitor_slug):
    api_key = request.headers.get("x-api-key", None)
    if not api_key:
        return Response(status=400)
    if not await update_monitor(monitor_slug, api_key):
        return Response(status=404)
    return Response("all good", status=200)


def random_monitor_key():
    N = 16
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.SystemRandom().choice(alphabet) for _ in range(N))


async def insert_monitor(name, api_key, frequency, slug):
    query = (
        "INSERT INTO monitor (name, api_key, frequency, slug, expires_at) "
        "VALUES (:na, :ak, :fr, :ms, :ea) returning id"
    )
    dbfile = app.config.get("DATABASE", "restarter-data.db")
    async with aiosqlite.connect(dbfile) as db:
        await db.set_trace_callback(app.logger.info)
        db.row_factory = aiosqlite.Row
        async with db.execute(
            query,
            {
                "na": name,
                "ak": api_key,
                "fr": frequency,
                "ms": slug,
                "ea": datetime.now().timestamp() + frequency,
            },
        ) as result:
            value = await result.fetchone()
            await db.commit()
        id = value["id"]
    return id


@app.post("/monitors")
@validate_request(MonitorIn)
async def monitor_create(data: MonitorIn):
    admin_key = request.headers.get("x-admin-key", None)
    if admin_key != current_app.config["ADMIN_KEY"]:
        return Response(status=401)
    name = data.name
    new_api_key = random_monitor_key()
    frequency = data.frequency
    slug = data.slug
    monitor_id = await insert_monitor(name, new_api_key, frequency, slug)

    monitor = Monitor(
        id=monitor_id,
        api_key=new_api_key,
        frequency=frequency,
        last_check=datetime.now(),
        expires_at=datetime.now().timestamp() + frequency,
        slug=slug,
        name=name,
    )

    return {
        "monitor_url": f"https://foo.bar/monitor/{monitor.slug}",
        "report_if_not_called_in": monitor.frequency,
        "name": monitor.name,
        "api_key": monitor.api_key,
    }
