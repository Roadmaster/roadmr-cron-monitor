import asyncio
import json
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
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from quart import (
    Quart,
    Response,
    current_app,
    g,
    jsonify,
    request,
    url_for,
    redirect,
    render_template,
    flash,
    session,
)
from quart_schema import (
    QuartSchema,
    RequestSchemaValidationError,
    validate_request,
    validate_headers,
)
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from alembic import command
from alembic.config import Config

from quart_wtf import QuartForm
from wtforms import StringField, PasswordField
from wtforms.validators import DataRequired, Email, EqualTo
from wtforms.widgets import PasswordInput

from . import database

app = Quart(__name__)
app.asgi_app = ProxyHeadersMiddleware(
    app.asgi_app, trusted_hosts=["172.16.0.0/12", "127.0.0.1", "66.241.112.0/20"]
)
logger = logging.getLogger(__name__)

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


class LoginForm(QuartForm):
    email = StringField(
        "Email address",
        validators=[DataRequired("Please enter your email address"), Email()],
    )

    password = PasswordField(
        "Password",
        widget=PasswordInput(hide_value=False),
        validators=[
            DataRequired("Please enter your password"),
        ],
    )


class CreateAccountForm(QuartForm):
    email = StringField(
        "Email address",
        validators=[DataRequired("Please enter your email address"), Email()],
    )

    password = PasswordField(
        "Password",
        widget=PasswordInput(hide_value=False),
        validators=[
            DataRequired("Please enter your password"),
            EqualTo("password_confirm", message="Passwords must match"),
        ],
    )

    password_confirm = PasswordField(
        "Confirm Password",
        widget=PasswordInput(hide_value=False),
        validators=[DataRequired("Please confirm your password")],
    )


# non async
async def check_things():
    jitter = random.randint(2, 15)
    app.logger.info("Checking service - jitter time %s" % jitter)
    await asyncio.sleep(jitter)
    monitors = await database.get_expired_monitors()
    print(f"{len(monitors)} expired monitors")
    # Only hit monitors if their last_hit is null. Meaning we hit them once only, unless
    # hitting them fails; then we would keep retrying.
    for m in [m for m in monitors if m["url"] and m["method"]]:
        await hit_webhook(
            m["wid"],
            m["url"],
            m["method"],
            m["headers"],
            m["form_fields"],
            m["body_payload"],
        )


async def hit_webhook(wid, url, method, headers, form_fields, body_payload):
    if headers is None:
        headers = {}
    else:
        headers = json.loads(headers)
    if form_fields is None:
        form_fields = {}
    else:
        form_fields = json.loads(form_fields)
    # TODO:  Use a shared-pool async client or something
    async with httpx.AsyncClient() as client:
        try:
            if await database.get_webhook_to_hit_by_id(wid):
                print(f"{url} has not been hit recently")

                resp = await client.request(
                    method,
                    url,
                    headers=headers,
                    data=form_fields,
                    content=body_payload,
                    follow_redirects=True,
                )
                print(resp.content)
                resp.raise_for_status()
                print(f"{url} hit successful, updating last_called time")
                await database.touch_webhook_by_id(wid)
            else:
                print(f"{url} was hit recently, skipping for now")
        except httpx.UnsupportedProtocol:
            pass


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
    user_id: int
    last_check: datetime | None
    expires_at: int  # in epoch seconds
    api_key: str


@dataclass
class UserIn:
    email: str
    password: str

    def __post_init__(self):
        if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", self.email):
            raise ValueError("weird email")


@dataclass
class User(UserIn):
    id: int
    user_key: str
    deleted_at: datetime
    created_at: datetime
    updated_at: datetime


def run() -> None:
    app.run()


@app.errorhandler(RequestSchemaValidationError)
async def handle_request_validation_error(error):
    return {
        "errors": str(error.validation_error),
    }, 400


@app.get("/")
async def root():
    if session.get("logged_in", False):
        user = await database.get_user_by_user_id(session["user_id"])
        if not user:
            user_key = None
        else:
            user_key = user["user_key"]
    else:
        user_key = None

    return await render_template("index.html", user_key=user_key)


@app.route("/register", methods=["GET", "POST"])
async def register():
    form = await CreateAccountForm.create_form()
    if await form.validate_on_submit():
        email = form.email.data
        password = passwordify(form.password.data)
        new_user_key = random_monitor_key(key_length=32)
        user = await database.insert_user(
            email=email, password_crypted=password, user_key=new_user_key
        )
        if user:
            session["logged_in"] = True
            session["user_id"] = user.id
            session["email"] = email
            await flash("User created and logged in", "success")

            return redirect("/")
        else:
            await flash("CRA CRA CRASH", "error")
            form.email.errors.append("Email already registered")

    return await render_template("register.html", form=form)


@app.route("/login", methods=["GET", "POST"])
async def login():
    form = await LoginForm.create_form()
    if await form.validate_on_submit():
        # Check password
        from argon2 import PasswordHasher
        import argon2

        ph = PasswordHasher(memory_cost=16384)

        try:
            user = await database.get_user_by_email(form.email.data)
            ph.verify(user["password"], form.password.data)
            session["user_id"] = user.id
            session["logged_in"] = True
            session["email"] = form.email.data
            await flash("User logged in", "success")

            return redirect("/")
        except (
            argon2.exceptions.VerifyMismatchError,
            database.NoResultFound,
        ):
            await flash("Login/password mismatch.")

    return await render_template("login.html", form=form)


@app.route("/logout", methods=["GET", "POST"])
async def logout():
    session.pop("logged_in", None)
    session.pop("user_id", None)
    await flash("Logged out", "success")  # could be error or info
    return redirect("/")


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


@app.delete("/monitor/<string:monitor_slug>")
async def monitor_delete(monitor_slug):
    admin_key = request.headers.get("x-admin-key", None)
    if not admin_key:
        return Response(status=400)
    if not await database.delete_monitor_and_webhooks_by_slug_admin_key(
        monitor_slug, admin_key
    ):
        return Response(status=404)
    response = jsonify("Delete successful")
    response.status = 200
    return response


def random_monitor_key(key_length=16):
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.SystemRandom().choice(alphabet) for _ in range(key_length))


def passwordify(pwd):
    from argon2 import PasswordHasher

    ph = PasswordHasher(memory_cost=16384)

    return ph.hash(pwd)


@dataclass
class Headers:
    x_user_key: str


@app.post("/monitors")
@validate_headers(Headers)
@validate_request(MonitorIn)
async def monitor_create(data: MonitorIn, headers: Headers):
    user_key = headers.x_user_key
    user = await database.get_user_by_user_key(user_key)
    if not user:
        return Response(status=401)
    user_id = user["id"]
    name = data.name
    new_api_key = random_monitor_key()
    frequency = data.frequency
    slug = data.slug
    webhook = data.webhook
    monitor_id = await database.insert_monitor(
        user_id, name, new_api_key, frequency, slug
    )
    if not monitor_id:
        return ({"error": "Monitor with this slug already exists"}, 400)
    await database.insert_webhook(
        monitor_id,
        webhook.url,
        webhook.method,
        webhook.headers,
        webhook.form_fields,
        webhook.body_payload,
    )

    monitor = Monitor(
        user_id=user_id,
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


@app.post("/users")
@validate_request(UserIn)
async def user_create(data: UserIn):
    admin_key = request.headers.get("x-admin-key", None)
    if admin_key != current_app.config["ADMIN_KEY"]:
        return Response(status=401)
    email = data.email
    password = passwordify(data.password)
    new_user_key = random_monitor_key(key_length=32)
    user = await database.insert_user(
        email=email, password_crypted=password, user_key=new_user_key
    )
    if not user:
        return ({"error": "Email already used"}, 400)
    u = User(**user)  # Create user record directo from the database
    return u
