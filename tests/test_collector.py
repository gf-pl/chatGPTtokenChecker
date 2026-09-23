import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import database
from app.collector import Monitor


class FakeClient:
    login_error = None
    login_pending = None

    def __init__(self, email):
        self.email = email

    async def read_account(self):
        return {"type": "chatgpt", "email": self.email, "planType": "plus"}

    async def read_limits(self):
        return {
            "rateLimitsByLimitId": {"codex": {
                "primary": {"usedPercent": 13, "windowDurationMins": 300, "resetsAt": 2000000000},
                "secondary": {"usedPercent": 40, "windowDurationMins": 10080, "resetsAt": 2000100000},
                "credits": {"balance": 904},
            }},
            "rateLimitResetCredits": {"availableCount": 1, "credits": [{"title": "Full reset", "expiresAt": 2000200000}]},
        }

    async def read_usage(self):
        return {"summary": {"lifetimeTokens": 123}}


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(database, "DB_PATH", Path(self.tempdir.name) / "usage.db")
        self.path_patch.start()
        (Path(self.tempdir.name) / "account1").mkdir()
        (Path(self.tempdir.name) / "account2").mkdir()
        database.initialize()

    def tearDown(self):
        self.path_patch.stop()
        self.tempdir.cleanup()

    def test_migration_runs_only_once_and_keeps_existing_cards(self):
        database.initialize()
        self.assertEqual(["Account 1", "Account 2"], [item["name"] for item in database.list_accounts()])

    def test_n_accounts_have_independent_readings(self):
        monitor = Monitor(Path(self.tempdir.name), 300)

        async def run():
            new = [await monitor.add_account(f"Extra {number}") for number in range(3)]
            for account in database.list_accounts():
                if account["id"] not in monitor.clients:
                    monitor._register(account["id"])
                monitor.clients[account["id"]] = FakeClient(f"{account['name']}@example.test")
            await asyncio.gather(*(monitor.sync(account["id"]) for account in database.list_accounts()))
            return new

        added = asyncio.run(run())
        cards = monitor.dashboard()["accounts"]
        self.assertEqual(5, len(cards))
        self.assertEqual(5, len({card["auth"]["email"] for card in cards}))
        self.assertEqual([1] * 5, [len(card["history"]) for card in cards])
        self.assertEqual(1, cards[-1]["latest"]["limits"]["rateLimitResetCredits"]["availableCount"])
        self.assertTrue(added[0]["id"].startswith("account-"))

    def test_removal_deletes_history_and_credentials(self):
        monitor = Monitor(Path(self.tempdir.name), 300)

        async def run():
            account = await monitor.add_account("Temporary")
            client = monitor.clients[account["id"]]
            client.home.mkdir()
            (client.home / "auth.json").write_text("credential")
            database.save_snapshot(account["id"], 100, "plus", None, {"rateLimits": {}}, None)
            self.assertTrue(await monitor.remove_account(account["id"]))
            self.assertFalse(await monitor.remove_account(account["id"]))
            return account, client.home

        account, home = asyncio.run(run())
        self.assertFalse(home.exists())
        self.assertFalse(database.account_exists(account["id"]))
        self.assertEqual([], database.snapshots(account["id"]))
        self.assertEqual(["Account 1", "Account 2"], [item["name"] for item in database.list_accounts()])


if __name__ == "__main__":
    unittest.main()
