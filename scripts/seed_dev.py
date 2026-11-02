import argparse
import asyncio
import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from whatsledger.db import models
from whatsledger.db.models import LedgerEntry, LedgerKind, LedgerSource, LedgerStatus, User
from whatsledger.db.session import SessionFactory
from whatsledger.handlers.currency import currency_for, timezone_for
from whatsledger.handlers.router import LOCALES
from whatsledger.plans.frameworks import PRESETS
from whatsledger.plans.store import save_plan
from whatsledger.settings import settings

# fixed namespace so each seeded row always gets the same id
NAMESPACE = uuid.UUID("5b1e4d3c-9a7f-4e2b-8c61-0d2f6a9e4b17")
# days ago, local hour, cents, category, vendor, note, voided
ROWS = [
    (0, 8, 180, "Dining", None, "coffee", False),
    (0, 13, 1250, "Dining", None, "chicken rice and drink", False),
    (1, 9, 1420, "Transport", "Grab", "ride to office", False),
    (1, 19, 8240, "Groceries", "FairPrice", "groceries", False),
    (2, 12, 960, "Dining", None, "lunch", False),
    (3, 14, 9900, "Shopping", None, "shoes", True),
    (3, 20, 4500, "Dining", None, "dinner with friends", False),
    (4, 18, 1599, "Bills", "Netflix", "subscription", False),
    (5, 15, 12900, "Shopping", "Uniqlo", "jacket", False),
    (6, 21, 2400, "Entertainment", None, "movie", False),
    (7, 10, 3500, "Health", None, "clinic visit", False),
    (8, 8, 210, "Transport", None, "train", False),
    (9, 13, 1100, "Dining", None, "lunch", False),
    (10, 19, 6380, "Groceries", None, "groceries", False),
    (12, 20, 18000, "Travel", None, "hotel deposit", False),
    (13, 12, 850, "Dining", None, "bubble tea and snack", False)
]
# the same, with the currency it was paid in, a trip to Italy and Malaysia
FOREIGN = [
    (2, 13, 1500, "Dining", None, "carbonara", False, "EUR"),
    (2, 20, 2100, "Dining", "Cam CODINO", "dinner", False, "EUR"),
    (5, 11, 6000, "Travel", "Trenitalia", "train to Florence", False, "EUR"),
    (6, 16, 4500, "Shopping", None, "leather wallet", False, "EUR"),
    (8, 12, 3200, "Dining", None, "nasi lemak lunch", False, "MYR"),
    (8, 21, 14500, "Travel", "Grab", "ride to KLIA", False, "MYR"),
    (11, 15, 8900, "Entertainment", None, "concert ticket", False, "USD")
]
# the month before, so questions and plans have a usual month to compare against
OLDER = [
    (16, 13, 1050, "Dining", None, "lunch", False),
    (18, 19, 7420, "Groceries", "FairPrice", "groceries", False),
    (20, 9, 1380, "Transport", "Grab", "ride to office", False),
    (22, 20, 3900, "Dining", None, "dinner", False),
    (25, 15, 5600, "Shopping", None, "gift", False),
    (27, 12, 890, "Dining", None, "laksa", False),
    (30, 18, 1599, "Bills", "Netflix", "subscription", False),
    (33, 19, 6900, "Groceries", None, "groceries", False),
    (37, 13, 1200, "Dining", None, "lunch", False),
    (41, 21, 2600, "Entertainment", None, "movie", False),
    (45, 10, 1420, "Transport", "Grab", "ride to office", False),
    (50, 19, 7100, "Groceries", "FairPrice", "groceries", False),
    (55, 13, 980, "Dining", None, "lunch", False),
    (62, 12, 4200, "Dining", None, "dinner with friends", False)
]
# new rows go on the end so earlier seed ids stay the same
ENTRIES = [(*row, None) for row in ROWS] + FOREIGN + [(*row, None) for row in OLDER]
# the plan seeded with the take home pay given, monthly 50/30/20
PLAN = "503020"
# the demo accounts, bob pays with a singapore number, alice is his friend in malaysia
# these are made up, pass --bob and --alice to use real numbers
BOB = "6591234567"
ALICE = "60123456789"
# label, cents, every, days from today, category
PLANNED = [
    ("rent", 180000, "month", 3, "Bills"),
    ("phone", 4800, "month", 2, "Bills"),
    ("gym", 2500, "week", 1, "Health"),
    ("mom's birthday present", 15000, "once", 20, "Shopping"),
    ("insurance", 120000, "year", 40, "Bills")
]
# planned rows get ids after the expense rows
PLANNED_FROM = 1000


# stable id for one seeded row of one user
def seed_id(wa_user_id: str, index: int) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{wa_user_id}:{index}")


# local time for a row, pulled back to the last half hour when it would be in the future
def when(days_ago: int, hour: int, zone: ZoneInfo, now: datetime) -> datetime:
    moment = datetime.combine(now.date() - timedelta(days=days_ago), time(hour), zone)
    return min(moment, now - timedelta(minutes=30))


# add the seed rows for one user, rows already there are left alone
async def seed(wa_user_id: str, reset: bool, pay: int, name: str | None = None) -> None:
    locale = LOCALES[settings.locale]
    ids = [seed_id(wa_user_id, index) for index in range(len(ENTRIES))]
    plan_ids = [seed_id(wa_user_id, PLANNED_FROM + index) for index in range(len(PLANNED))]
    async with SessionFactory() as session:
        if reset:
            await session.execute(delete(LedgerEntry).where(LedgerEntry.id.in_(ids)))
            planned_rows = models.PlannedSpend.id.in_(plan_ids)
            await session.execute(delete(models.PlannedSpend).where(planned_rows))
        await session.execute(
            insert(User)
            .values(
                wa_user_id=wa_user_id, currency=currency_for(wa_user_id, locale.currency),
                timezone=timezone_for(wa_user_id, locale.timezone)
            )
            .on_conflict_do_nothing(index_elements=["wa_user_id"])
        )
        query = select(User).where(User.wa_user_id == wa_user_id)
        user = (await session.execute(query)).scalar_one()
        # a name set here wins over the whatsapp profile name in bills and messages
        if name:
            user.display_name = name
        zone = ZoneInfo(user.timezone)
        now = datetime.now(zone)
        values = [
            {
                "id": ids[index],
                "user_id": user.id,
                "kind": LedgerKind.EXPENSE,
                "amount_cents": cents,
                "currency": currency or user.currency,
                "category": category,
                "vendor": vendor,
                "note": note,
                "source": LedgerSource.TEXT,
                "status": LedgerStatus.POSTED,
                "occurred_at": when(days_ago, hour, zone, now),
                "voided_at": now if voided else None
            }
            for index, (days_ago, hour, cents, category, vendor, note, voided, currency)
            in enumerate(ENTRIES)
        ]
        added = await session.execute(
            insert(LedgerEntry)
            .values(values)
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(LedgerEntry.id)
        )
        count = len(added.all())
        planned = [
            {
                "id": plan_ids[index], "user_id": user.id, "label": label, "amount_cents": cents,
                "currency": user.currency, "category": category, "every": every,
                "due_on": now.date() + timedelta(days=ahead)
            }
            for index, (label, cents, every, ahead, category) in enumerate(PLANNED)
        ]
        await session.execute(
            insert(models.PlannedSpend)
            .values(planned)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        if pay:
            await save_plan(session, user.id, PRESETS[PLAN], "monthly", pay * 100)
        await session.commit()
    print(f"added {count} of {len(ENTRIES)} seed entries in {user.currency}, {user.timezone}")
    if pay:
        print(f"plan set to 50/30/20 monthly on {user.currency} {pay:,} take-home pay")
    if count == 0:
        print("already seeded, run with --reset to replace them with fresh dates")


# both demo accounts, bob with history and a plan, alice with just her name
async def demo(reset: bool, pay: int, bob: str, alice: str) -> None:
    await seed(bob, reset, pay, "Bob")
    await name_only(alice, "Alice")


# make or rename one user without any history
async def name_only(wa_user_id: str, name: str) -> None:
    locale = LOCALES[settings.locale]
    async with SessionFactory() as session:
        await session.execute(
            insert(User)
            .values(
                wa_user_id=wa_user_id, currency=currency_for(wa_user_id, locale.currency),
                timezone=timezone_for(wa_user_id, locale.timezone)
            )
            .on_conflict_do_nothing(index_elements=["wa_user_id"])
        )
        user = (await session.execute(
            select(User).where(User.wa_user_id == wa_user_id)
        )).scalar_one()
        user.display_name = name
        await session.commit()
    print(f"{name} is {wa_user_id}, {user.currency}, {user.timezone}")


# parse arguments and refuse to run outside dev
def main() -> int:
    parser = argparse.ArgumentParser(description="seed two weeks of spending for one user")
    parser.add_argument(
        "wa_user_id", nargs="?", help="whatsapp id, digits only, for example 6591234567"
    )
    parser.add_argument("--name", help="name the bot uses for this person, like Bob")
    parser.add_argument(
        "--demo", action="store_true", help="seed bob with history and a plan, and name alice"
    )
    parser.add_argument("--bob", default=BOB, help="bob's whatsapp id for --demo")
    parser.add_argument("--alice", default=ALICE, help="alice's whatsapp id for --demo")
    parser.add_argument("--reset", action="store_true", help="delete earlier seed rows first")
    parser.add_argument(
        "--pay", type=int, default=4500, help="monthly take-home pay for the plan, 0 for no plan"
    )
    args = parser.parse_args()
    if settings.env != "dev":
        print("seed_dev only runs when ENV=dev")
        return 1
    if args.demo:
        if not (args.bob.isdigit() and args.alice.isdigit()):
            print("give whatsapp ids, digits only, no plus sign or spaces")
            return 1
        asyncio.run(demo(args.reset, args.pay, args.bob, args.alice))
        return 0
    if not args.wa_user_id or not args.wa_user_id.isdigit():
        print("give a whatsapp id, digits only, no plus sign or spaces")
        return 1
    asyncio.run(seed(args.wa_user_id, args.reset, args.pay, args.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
