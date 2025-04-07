import logging
import random
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
    validate_response,
)

app = Quart(__name__)
app.logger.setLevel(logging.INFO)
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
        with open(Path(app.root_path) / "schema.sql", mode="r") as file_:
            await db.executescript(file_.read())
            await db.commit()
    app.logger.info("Setup complete, serving")


@dataclass
class MonitorIn:
    name: str
    frequency: int  # Alert if last_check + frequency > now()


@dataclass
class Monitor(MonitorIn):
    id: int
    last_check: datetime | None
    api_key: str


# non async
def check_things():
    app.logger.info("Checking service")
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


@app.post("/monitor/<string:monitor_id>")
async def monitor_update():
    api_key = request.headers.get("x-api-key", None)


def random_monitor_key():
    N = 16
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.SystemRandom().choice(alphabet) for _ in range(N))


async def insert_monitor(name, api_key, frequency):
    query = (
        "INSERT INTO monitor (name, api_key, frequency) "
        "VALUES (:na, :ak, :fr) returning id"
    )
    dbfile = app.config.get("DATABASE", "restarter-data.db")
    async with aiosqlite.connect(dbfile) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            query,
            {"na": name, "ak": api_key, "fr": frequency},
        ) as result:
            value = await result.fetchone()
            await db.commit()
        id = value["id"]
    return id


@app.post("/monitors")
@validate_request(MonitorIn)
@validate_response(Monitor)
async def monitor_create(data: MonitorIn) -> Monitor:
    admin_key = request.headers.get("x-admin-key", None)
    if admin_key != current_app.config["ADMIN_KEY"]:
        return Response(status=401)
    name = data.name
    new_api_key = random_monitor_key()
    frequency = data.frequency
    print(await insert_monitor(name, new_api_key, frequency))

    return Monitor(
        id=1,
        api_key=new_api_key,
        frequency=frequency,
        last_check=datetime.now(),
        name=name,
    )
