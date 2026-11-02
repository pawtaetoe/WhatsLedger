import asyncio
import logging
from datetime import UTC, datetime

from whatsledger.contracts.transport import Transport
from whatsledger.handlers.bill import GroupBills
from whatsledger.handlers.bills import UpcomingBills

LOG = logging.getLogger(__name__)
# seconds between checks for bills to remind about and bills ready to close
CHECK_SECONDS = 15


# check for due reminders and bills to close every 15 seconds while the app runs
async def reminder_loop(bills: UpcomingBills, group: GroupBills, transport: Transport) -> None:
    while True:
        try:
            sent = await bills.send_due(transport, datetime.now(UTC))
            nudged = await group.nudge(transport, datetime.now(UTC))
            if sent or nudged:
                LOG.info("sent %d bill reminders and %d close nudges", sent, nudged)
        except Exception as error:
            LOG.warning("reminders failed with %s", type(error).__name__)
        await asyncio.sleep(CHECK_SECONDS)
