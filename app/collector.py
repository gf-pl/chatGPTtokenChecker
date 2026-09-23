import asyncio
import logging
import shutil
import time
from pathlib import Path

from .codex_client import AppServerError, CodexClient
from .database import create_account, delete_account, list_accounts, save_snapshot, snapshots

logger = logging.getLogger(__name__)


class Monitor:
    def __init__(self, data_dir: Path, refresh_interval: int):
        self.data_dir = data_dir
        self.refresh_interval = refresh_interval
        self.clients: dict[str, CodexClient] = {}
        self.auth: dict[str, dict] = {}
        self.errors: dict[str, str | None] = {}
        self.sync_lock: dict[str, asyncio.Lock] = {}
        self.registry_lock = asyncio.Lock()
        self.task: asyncio.Task | None = None

    def _register(self, account_id: str):
        client = CodexClient(account_id, self.data_dir)
        client.on_login_success = self.sync
        self.clients[account_id] = client
        self.sync_lock[account_id] = asyncio.Lock()

    async def start(self):
        for account in list_accounts():
            self._register(account["id"])
        self.task = asyncio.create_task(self._loop())

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        await asyncio.gather(*(client.stop() for client in self.clients.values()))

    async def add_account(self, name: str) -> dict[str, str]:
        async with self.registry_lock:
            account = create_account(name)
            self._register(account["id"])
            return account

    async def remove_account(self, account_id: str) -> bool:
        async with self.registry_lock:
            lock = self.sync_lock.get(account_id)
            if lock is None:
                return False
            async with lock:
                client = self.clients[account_id]
                await client.stop()
                # Remove credentials and readings with the card. IDs come only from our database.
                if client.home.exists():
                    shutil.rmtree(client.home)
                delete_account(account_id)
                self.clients.pop(account_id, None)
                self.sync_lock.pop(account_id, None)
                self.auth.pop(account_id, None)
                self.errors.pop(account_id, None)
                return True

    async def _loop(self):
        while True:
            await asyncio.gather(*(self.sync(account_id) for account_id in list(self.clients)))
            await asyncio.sleep(self.refresh_interval)

    async def sync(self, account_id: str):
        lock = self.sync_lock.get(account_id)
        if lock is None:
            return None
        async with lock:
            client = self.clients.get(account_id)
            if client is None:
                return None
            try:
                account = await client.read_account()
                if not account or account.get("type") != "chatgpt":
                    self.auth[account_id] = {"connected": False}
                    self.errors[account_id] = client.login_error
                    return None
                self.auth[account_id] = {
                    "connected": True,
                    "email": account.get("email"),
                    "plan_type": account.get("planType"),
                }
                limits = await client.read_limits()
                if not isinstance(limits, dict):
                    raise AppServerError("Codex returned no rate-limit data")
                try:
                    usage = await client.read_usage()
                except AppServerError:
                    usage = None
                save_snapshot(account_id, int(time.time()), account.get("planType"), account.get("email"), limits, usage)
                self.errors[account_id] = None
                return limits
            except Exception as exc:
                logger.warning("Sync failed for %s: %s", account_id, exc)
                self.errors[account_id] = str(exc)
                return None

    def dashboard(self):
        result = []
        for account in list_accounts():
            account_id = account["id"]
            client = self.clients.get(account_id)
            if client is None:
                continue
            history = snapshots(account_id)
            result.append({
                **account,
                "auth": self.auth.get(account_id, {"connected": False}),
                "login_pending": client.login_pending,
                "error": self.errors.get(account_id) or client.login_error,
                "latest": history[0] if history else None,
                "history": history,
            })
        return {"accounts": result, "refresh_interval": self.refresh_interval, "server_time": int(time.time())}
