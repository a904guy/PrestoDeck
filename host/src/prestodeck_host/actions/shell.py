"""Shell command action."""

from __future__ import annotations

import asyncio
import os
from typing import Literal

from prestodeck_host.actions.base import Action, ActionContext, ActionResult
from prestodeck_host.log import get_logger

_logger = get_logger(__name__)


class ShellAction(Action):
    """Run a shell command on the host, capturing output to the log."""

    type: Literal["shell"]
    cmd: str
    cwd: str | None = None
    env: dict[str, str] | None = None
    timeout_s: float | None = None

    async def execute(self, ctx: ActionContext) -> ActionResult:
        """Run ``cmd`` via ``create_subprocess_shell`` and log its output."""
        proc = await asyncio.create_subprocess_shell(
            self.cmd,
            cwd=self.cwd,
            env=self._merged_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), self.timeout_s)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            _logger.warning("shell timed out after %ss: %s", self.timeout_s, self.cmd)
            return ActionResult(ok=False, detail="timeout")
        if out:
            _logger.info("shell stdout: %s", out.decode(errors="replace").rstrip())
        if err:
            _logger.info("shell stderr: %s", err.decode(errors="replace").rstrip())
        ok = proc.returncode == 0
        if not ok:
            _logger.warning("shell exited %s: %s", proc.returncode, self.cmd)
        return ActionResult(ok=ok, detail=f"rc={proc.returncode}")

    def _merged_env(self) -> dict[str, str] | None:
        """Merge configured env onto the host environment, or None for inherit."""
        if self.env is None:
            return None
        merged = dict(os.environ)
        merged.update(self.env)
        return merged
