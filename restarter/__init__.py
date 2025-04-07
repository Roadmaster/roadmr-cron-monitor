from dataclasses import dataclass
from datetime import datetime

from quart import Quart, request, Response, current_app
from quart_schema import (
    QuartSchema,
    validate_request,
    validate_response,
    RequestSchemaValidationError,
)


from apscheduler.schedulers.asyncio import AsyncIOScheduler


app = Quart(__name__)
QuartSchema(app)

CHECK_SCHED = 10

URL_TO_CHECK = "https://ubunty.fly.dev/health"


app.config.from_prefixed_env(prefix="FLYRESTARTER")


@dataclass
class MonitorIn:
    last_check: datetime | None
    frequency: int  # Alert if last_check + frequency > now()
    api_key: str


@dataclass
class Monitor(MonitorIn):
    id: int


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


@app.post("/monitor/<string:monitor_id>")
async def monitor_update():
    api_key = request.headers.get("x-api-key", None)


@app.post("/monitors")
@validate_request(MonitorIn)
@validate_response(Monitor)
async def monitor_create(data: MonitorIn) -> Monitor:
    admin_key = request.headers.get("x-admin-key", None)
    if admin_key != current_app.config["ADMIN_KEY"]:
        return Response(status=401)
    return Monitor(
        id=1, api_key=data.api_key, frequency=data.frequency, last_check=data.last_check
    )
