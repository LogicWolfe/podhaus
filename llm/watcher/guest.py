from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class GuestMemory:
    total_mib: int
    free_mib: int
    available_mib: int

    @property
    def used_mib(self) -> int:
        """Includes the file cache, which Windows gets back only once it is dropped."""
        return self.total_mib - self.free_mib


class Guest:
    """The WSL guest's memory, and the model file's share of its file cache."""

    def __init__(self, meminfo: Path, model_file: Path) -> None:
        # Checked now, not at the first cache drop: a bad mount then fails the
        # deploy, rather than ending the watcher each time the model loads or
        # unloads, which loses that yield's record.
        if not model_file.is_file():
            raise FileNotFoundError(model_file)
        self._meminfo = meminfo
        self._model_file = model_file

    def memory(self) -> GuestMemory:
        fields = dict(line.split(":", 1) for line in self._meminfo.read_text().splitlines())

        def mib(name: str) -> int:
            return int(fields[name].split()[0]) // 1024

        return GuestMemory(mib("MemTotal"), mib("MemFree"), mib("MemAvailable"))

    def drop_model_file_cache(self) -> None:
        """Drops the guest's cache of just the model file, apart from the pages
        a running model process maps, and needs no privilege."""
        descriptor = os.open(self._model_file, os.O_RDONLY)
        try:
            os.posix_fadvise(descriptor, 0, 0, os.POSIX_FADV_DONTNEED)
        finally:
            os.close(descriptor)
