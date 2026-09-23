import asyncio
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class AppServerError(Exception):
    pass


class CodexClient:
    """One JSON-RPC stdio connection and one isolated Codex home per account."""

    def __init__(self, account_id: str, data_dir: Path):
        self.account_id = account_id
        self.home = data_dir / account_id
        self.process: asyncio.subprocess.Process | None = None
        self.pending: dict[int, asyncio.Future] = {}
        self.next_id = 1
        self.start_lock = asyncio.Lock()
        self.write_lock = asyncio.Lock()
        self.reader_task: asyncio.Task | None = None
        self.stderr_task: asyncio.Task | None = None
        self.login_pending: dict | None = None
        self.login_error: str | None = None
        self.on_login_success = None

    async def start(self):
        async with self.start_lock:
            if self.process and self.process.returncode is None:
                return
            self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.home.chmod(0o700)
            env = os.environ.copy()
            for key in list(env):
                if key.startswith("ACCOUNT") and ("KEY" in key or "TOKEN" in key):
                    env.pop(key, None)
            env.pop("OPENAI_API_KEY", None)
            env.pop("CODEX_API_KEY", None)
            env["CODEX_HOME"] = str(self.home)
            self.process = await asyncio.create_subprocess_exec(
                "codex", "app-server", "--stdio",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            self.reader_task = asyncio.create_task(self._read_stdout())
            self.stderr_task = asyncio.create_task(self._drain_stderr())
            await self._request_unchecked("initialize", {
                "clientInfo": {"name": "local_usage_monitor", "title": "Local Usage Monitor", "version": "1.0.0"}
            })
            await self._write({"method": "initialized", "params": {}})

    async def _write(self, message: dict):
        if not self.process or not self.process.stdin or self.process.returncode is not None:
            raise AppServerError("Codex App Server is not running")
        async with self.write_lock:
            self.process.stdin.write((json.dumps(message, separators=(",", ":")) + "\n").encode())
            await self.process.stdin.drain()

    async def _request_unchecked(self, method: str, params: dict | None = None):
        request_id = self.next_id
        self.next_id += 1
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            message = {"method": method, "id": request_id}
            if params is not None:
                message["params"] = params
            await self._write(message)
            return await asyncio.wait_for(future, timeout=30)
        except asyncio.TimeoutError as exc:
            raise AppServerError(f"Codex App Server timed out while calling {method}") from exc
        finally:
            self.pending.pop(request_id, None)

    async def request(self, method: str, params: dict | None = None):
        await self.start()
        return await self._request_unchecked(method, params)

    async def _read_stdout(self):
        try:
            while self.process and self.process.stdout:
                line = await self.process.stdout.readline()
                if not line:
                    break
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                request_id = message.get("id")
                if request_id is not None:
                    future = self.pending.get(request_id)
                    if future and not future.done():
                        if "error" in message:
                            error = message["error"]
                            detail = error.get("message", "Codex request failed") if isinstance(error, dict) else str(error)
                            future.set_exception(AppServerError(detail))
                        else:
                            future.set_result(message.get("result"))
                elif message.get("method") == "account/login/completed":
                    params = message.get("params") or {}
                    if params.get("success"):
                        self.login_pending = None
                        self.login_error = None
                        if self.on_login_success:
                            asyncio.create_task(self.on_login_success(self.account_id))
                    else:
                        self.login_error = str(params.get("error") or "Sign-in failed")
                        self.login_pending = None
        except Exception:
            logger.exception("Codex App Server reader stopped for %s", self.account_id)
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(AppServerError("Codex App Server closed its connection"))

    async def _drain_stderr(self):
        try:
            while self.process and self.process.stderr:
                if not await self.process.stderr.readline():
                    break
        except Exception:
            pass

    async def read_account(self):
        result = await self.request("account/read", {"refreshToken": False})
        return (result or {}).get("account")

    async def read_limits(self):
        return await self.request("account/rateLimits/read")

    async def read_usage(self):
        return await self.request("account/usage/read")

    async def begin_device_login(self):
        result = await self.request("account/login/start", {"type": "chatgptDeviceCode"})
        if not isinstance(result, dict) or result.get("type") != "chatgptDeviceCode":
            raise AppServerError("Codex did not return a device sign-in code")
        self.login_pending = {
            "verification_url": result.get("verificationUrl"),
            "user_code": result.get("userCode"),
            "login_id": result.get("loginId"),
        }
        self.login_error = None
        return self.login_pending

    async def stop(self):
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        for task in (self.reader_task, self.stderr_task):
            if task:
                task.cancel()
