from __future__ import annotations

from dataclasses import dataclass
import subprocess
from typing import Protocol


@dataclass(frozen=True)
class GpuReading:
    util_percent: int
    memory_used_mib: int
    memory_total_mib: int
    power_watts: float
    temperature_celsius: int


class GpuReader(Protocol):
    def read(self) -> GpuReading: ...


class NvidiaSmi:
    """Reads the whole GPU through nvidia-smi, which the NVIDIA container
    runtime puts in the container. The only part of the watcher that touches
    hardware; the tests replace it."""

    QUERY = "utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu"

    def read(self) -> GpuReading:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={self.QUERY}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return self.parse(result.stdout)

    @staticmethod
    def parse(output: str) -> GpuReading:
        # One line per GPU; this machine has one, and a second would make
        # "whole-GPU utilisation" ambiguous.
        (line,) = output.strip().splitlines()
        util, used, total, power, temperature = (field.strip() for field in line.split(","))
        return GpuReading(int(util), int(used), int(total), float(power), int(temperature))
