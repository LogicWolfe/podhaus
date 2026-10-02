"""llama.cpp's router, as far as the watcher uses it. Everything the watcher
assumes about the router's management API is in this module."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REQUEST_TIMEOUT_S = 5
# The router leaves the slot report unanswered while a slot saves or restores
# its cache; past this, the read counts as a busy model rather than an error.
SLOT_READ_TIMEOUT_S = 2.0


class ModelServerError(Exception):
    """The router's reply was not what the watcher expects."""


class RouterError(ModelServerError):
    """The router answered with an error status."""

    def __init__(self, request: str, status: int, body: str) -> None:
        super().__init__(f"{request} answered {status}: {body}")
        self.status = status
        self.body = body

    def says(self, status: int, message: str) -> bool:
        """Whether this is the router's own error answer with this status and message."""
        return self.status == status and json.loads(self.body)["error"]["message"] == message


class ModelState(Enum):
    UNLOADED = "unloaded"
    LOADING = "loading"
    LOADED = "loaded"


@dataclass(frozen=True)
class ModelStatus:
    state: ModelState
    exit_code: int | None  # the last model process's exit code, when it failed

    @classmethod
    def parse(cls, status: dict) -> ModelStatus:
        # "sleeping" and "downloading" are not configured here, so ModelState
        # refuses them.
        return cls(ModelState(status["value"]), status["exit_code"] if status.get("failed") else None)


@dataclass(frozen=True)
class Slot:
    id: int
    tokens: int
    busy: bool

    @classmethod
    def parse(cls, report: dict) -> Slot:
        # Only counts and flags are read: with slot debugging on, the router's
        # report would also carry conversation text.
        tokens = report["n_prompt_tokens"] if "id_task" in report else 0  # never ran a task
        return cls(report["id"], tokens, report["is_processing"])


class ModelServer:
    def __init__(self, base_url: str, model: str, slot_read_timeout_s: float) -> None:
        self._base_url = base_url
        self._model = model
        self._slot_read_timeout_s = slot_read_timeout_s

    def status(self) -> ModelStatus:
        listing = self._request("GET", "/models")
        entries = {entry["id"]: entry for entry in listing["data"]}
        return ModelStatus.parse(entries[self._model]["status"])

    def slots(self) -> tuple[Slot, ...] | None:
        """The slot report, or None when there is none this time: the router
        did not answer in time, or answered with an error because the model
        process ended or started loading since the status read. The next
        status read says which."""
        # autoload=false: reading the slots must never be what loads the model.
        query = urlencode({"model": self._model, "autoload": "false"})
        try:
            reports = self._request("GET", f"/slots?{query}", timeout_s=self._slot_read_timeout_s)
        except (TimeoutError, RouterError):
            return None
        return tuple(Slot.parse(report) for report in reports)

    def load(self) -> None:
        """Starts a load and returns; status() reports its progress."""
        self._command("/models/load")

    def unload(self) -> bool:
        """Ends the model process, cutting any request in flight. False when
        there was no process to end: it exited on its own since the status read."""
        try:
            self._command("/models/unload")
        except RouterError as error:
            if not error.says(400, "model is not running"):
                raise
            return False
        return True

    def _command(self, path: str) -> None:
        reply = self._request("POST", path, {"model": self._model})
        if reply["success"] is not True:
            raise ModelServerError(f"POST {path} answered {reply}")

    def _request(self, method: str, path: str, body: dict | None = None,
                 timeout_s: float = REQUEST_TIMEOUT_S) -> object:
        data = None if body is None else json.dumps(body).encode()
        request = Request(self._base_url + path, data, {"Content-Type": "application/json"}, method=method)
        try:
            with urlopen(request, timeout=timeout_s) as response:
                return json.load(response)
        except HTTPError as error:
            with error:
                raise RouterError(f"{method} {path}", error.code, error.read().decode()) from error
