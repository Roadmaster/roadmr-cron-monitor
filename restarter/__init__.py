import asyncio
import logging
import os
import random
import re
import string
import time
from dataclasses import dataclass
from datetime import datetime

import aiosqlite
import apscheduler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from quart import Quart, Response, current_app, g, jsonify, request, url_for
from quart_schema import QuartSchema, RequestSchemaValidationError, validate_request

from alembic import command
from alembic.config import Config

from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware


from . import database

app = Quart(__name__)
app.asgi_app = ProxyHeadersMiddleware(
    app.asgi_app, trusted_hosts=["172.16.0.0/12", "127.0.0.1"]
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

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


# non async
async def check_things():
    app.logger.info("Checking service")
    await database.get_expired_monitors()


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
    print("SQLA TEST")

    await database.get_expired_monitors()
    app.logger.info("Setup complete, serving")
    if os.environ.get("PRINT_LOGGING_TREE"):
        try:
            import logging_tree

            logging_tree.printout()
        except ModuleNotFoundError:
            pass


@dataclass(kw_only=True)
class WebhookIn:
    url: str
    method: str
    headers: dict | None = None
    form_fields: dict | None = None
    body_payload: str | None = None

    def __post_init__(self):
        if self.method.upper() not in ["POST", "GET"]:
            raise ValueError("method must be post or get")


@dataclass
class Webhook(WebhookIn):
    id: int
    created_at: datetime
    updated_at: datetime


@dataclass
class MonitorIn:
    name: str  # Descriptive name
    slug: str  # URLifiable slug
    frequency: int  # Alert if last_check + frequency > now()
    webhook: WebhookIn

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


@app.post("/monitor/<string:monitor_slug>")
async def monitor_update(monitor_slug):
    api_key = request.headers.get("x-api-key", None)
    if not api_key:
        return Response(status=400)
    if not await database.update_monitor(monitor_slug, api_key):
        return Response(status=404)
    response = jsonify("Update successful")
    response.status = 200
    return response


def random_monitor_key():
    N = 16
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.SystemRandom().choice(alphabet) for _ in range(N))


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
    webhook = data.webhook
    monitor_id = await database.insert_monitor(name, new_api_key, frequency, slug)
    webhook_id = await database.insert_webhook(
        monitor_id,
        webhook.url,
        webhook.method,
        webhook.headers,
        webhook.form_fields,
        webhook.body_payload,
    )

    monitor = Monitor(
        id=monitor_id,
        api_key=new_api_key,
        frequency=frequency,
        last_check=datetime.now(),
        expires_at=datetime.now().timestamp() + frequency,
        slug=slug,
        name=name,
        webhook=data.webhook,
    )
    print(monitor)

    return {
        "monitor_url": url_for(
            "monitor_update", monitor_slug=monitor.slug, _external=True
        ),
        "report_if_not_called_in": monitor.frequency,
        "name": monitor.name,
        "api_key": monitor.api_key,
        "webhook": {
            "url": webhook.url,
            "method": webhook.method,
            "headers": webhook.headers,
            "form_fields": webhook.form_fields,
            "body_payload": webhook.body_payload,
        },
    }
