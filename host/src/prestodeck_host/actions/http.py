"""HTTP request action."""

from __future__ import annotations

from typing import Any, Literal

import httpx
from pydantic import ConfigDict, Field

from prestodeck_host.actions.base import Action, ActionContext, ActionResult
from prestodeck_host.log import get_logger

_logger = get_logger(__name__)


class HttpAction(Action):
    """Issue an async HTTP request. Non-2xx responses are logged, not raised.

    The JSON body uses the YAML key ``json`` but is stored as ``json_body`` to
    avoid shadowing Pydantic's ``BaseModel.json``.
    """

    model_config = ConfigDict(populate_by_name=True)

    type: Literal["http"]
    method: str = "GET"
    url: str
    headers: dict[str, str] | None = None
    json_body: dict[str, Any] | None = Field(default=None, alias="json")
    body: str | None = None
    timeout_s: float | None = 10.0

    async def execute(self, ctx: ActionContext) -> ActionResult:
        """Perform the request; return ok for 2xx, otherwise log and return not-ok."""
        kwargs: dict[str, Any] = {"headers": self.headers}
        if self.json_body is not None:
            kwargs["json"] = self.json_body
        elif self.body is not None:
            kwargs["content"] = self.body
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.request(self.method.upper(), self.url, **kwargs)
        except httpx.HTTPError as exc:
            _logger.warning("http %s %s failed: %s", self.method, self.url, exc)
            return ActionResult(ok=False, detail=str(exc))
        ok = 200 <= resp.status_code < 300
        level = _logger.info if ok else _logger.warning
        level("http %s %s -> %s", self.method.upper(), self.url, resp.status_code)
        return ActionResult(ok=ok, detail=f"status={resp.status_code}")
