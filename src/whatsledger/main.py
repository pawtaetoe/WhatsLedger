import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from whatsledger.channels import twilio, whatsapp
from whatsledger.channels.simulator import dev_router
from whatsledger.channels.twilio import twilio_router
from whatsledger.channels.whatsapp import whatsapp_router
from whatsledger.contracts.transport import Transport
from whatsledger.handlers.router import bills, group, pay_rails, settle
from whatsledger.jobs.reminders import reminder_loop
from whatsledger.settings import settings
from whatsledger.web.claim import claim_page, claim_router
from whatsledger.web.dashboard import dashboard_page, dashboard_router
from whatsledger.web.edit import edit_page, edit_router
from whatsledger.web.plan import plan_router

# show our own info logs next to the uvicorn ones
logging.basicConfig(level=logging.INFO)
TWILIO = settings.whatsapp_provider == "twilio"


# bill reminders run beside the webhook for as long as the app is up
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    transport: Transport = twilio.transport if TWILIO else whatsapp.channel.transport
    task = asyncio.create_task(reminder_loop(bills, group, transport))
    yield
    task.cancel()


app = FastAPI(title="WhatsLedger", lifespan=lifespan)
sender: Transport = twilio.transport if TWILIO else whatsapp.channel.transport
claim_page.attach(group, sender)
dashboard_page.attach(settle, pay_rails, sender)
edit_page.attach(group, sender)
app.include_router(twilio_router if TWILIO else whatsapp_router)
app.include_router(claim_router)
app.include_router(dashboard_router)
app.include_router(edit_router)
app.include_router(plan_router)
# htmx is served from here so the pages still work when a cdn is blocked
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), "static")
if settings.env == "dev":
    app.include_router(dev_router)


# liveness probe
@app.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}
