import logging
import asyncio
import random
import re
import string
import time
from dataclasses import dataclass
from datetime import datetime

import apscheduler
import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from quart import Quart, Response, current_app, g, jsonify, request
from quart_schema import QuartSchema, RequestSchemaValidationError, validate_request
from alembic.config import Config
from alembic import command

app = Quart(__name__)
app.logger.setLevel(logging.INFO)

QuartSchema(app)

CHECK_SCHED = 10


app.config.from_prefixed_env(prefix="FLYRESTARTER")


def adapt_datetime_iso(val):
    """Adapt datetime.datetime to timezone-naive ISO 8601 date."""
    return val.isoformat()


def convert_datetime(val):
    """Convert ISO 8601 datetime to datetime.datetime object."""
    return datetime.fromisoformat(val.decode())


aiosqlite.register_adapter(datetime, adapt_datetime_iso)
aiosqlite.register_converter("datetime", convert_datetime)


# @app.before_request
def logging_before():
    # Store the start time for the request
    g.start_time = time.perf_counter()


# @app.after_request
def logging_after(response):
    # Get total time in milliseconds
    total_time = time.perf_counter() - g.start_time
    time_in_ms = int(total_time * 1000)
    # Log the time taken for the endpoint
    current_app.logger.info(
        "%s ms %s %s %s", time_in_ms, request.method, request.path, dict(request.args)
    )
    return response


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


# non async
async def check_things():
    app.logger.info("Checking service")
    await get_expired_monitors()


async def run_migrations(db_path):
    acfg = Config("alembic.ini")
    acfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    await asyncio.to_thread(command.upgrade, acfg, "head")


scheduler = AsyncIOScheduler()
scheduler.add_job(check_things, "interval", seconds=CHECK_SCHED)


async def init_db():
    dbfile = app.config.get("DATABASE", "restarter-data.db")
    await run_migrations(dbfile)


@app.before_serving
async def before_serving():
    app.logger.info("Initializing db")
    await init_db()
    # Start the scheduler
    app.logger.info("Starting scheduler")
    try:
        scheduler.start()
    except apscheduler.schedulers.SchedulerAlreadyRunningError:
        pass
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
        db.row_factory = aiosqlite.Row
        async with db.execute(
            query,
            {},
        ) as result:
            values = await result.fetchall()
    app.logger.info([dict(r) for r in values])


async def get_monitor_by_api_key_slug(api_key, slug):
    query = "SELECT * from monitor " "WHERE api_key=:ap AND slug=:sl"

    dbfile = app.config.get("DATABASE", "restarter-data.db")
    async with aiosqlite.connect(dbfile) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            query,
            {"ap": api_key, "sl": slug},
        ) as result:
            r = await result.fetchone()
    return dict(r)


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
        # await db.set_trace_callback(app.logger.info)
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
    response = jsonify("Update successful")
    response.status = 200
    return response


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
