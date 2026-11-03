"""显存、GPU 利用率、功耗与温度状态。"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

_nvml_ready: bool | None = None   # None=未尝试，True/False=结果
_nvml_handle = None


@dataclass
class VramInfo:
    total_mb: int = 0
    used_mb: int = 0
    free_mb: int = 0
    name: str = ""
    available: bool = False
    util_pct: int = -1          # GPU 利用率 %，-1 表示读不到
    power_w: float = 0.0        # 实时功耗 W，0 表示读不到
    power_limit_w: float = 0.0  # 功耗上限 W
    temp_c: int = -1            # 核心温度 ℃，-1 表示读不到
    temp_slowdown_c: int = -1   # 降频温度阈值 ℃

    @property
    def summary(self) -> str:
        if not self.available:
            return "GPU 状态不可用"
        extra = []
        if self.util_pct >= 0:
            extra.append(f"{self.util_pct}%")
        if self.power_w > 0:
            extra.append(f"{self.power_w:.0f}W")
        if self.temp_c >= 0:
            extra.append(f"{self.temp_c}℃")
        tail = ("  " + " · ".join(extra)) if extra else ""
        return f"{self.name}  {self.used_mb}/{self.total_mb} MB 已用（可用 {self.free_mb} MB）{tail}"


def _handle():
    """NVML 只初始化一次，避免高频轮询时反复 init。"""
    global _nvml_ready, _nvml_handle
    if _nvml_ready is False:
        return None
    if _nvml_handle is not None:
        return _nvml_handle
    try:
        import pynvml

        pynvml.nvmlInit()
        _nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        _nvml_ready = True
        return _nvml_handle
    except Exception:
        _nvml_ready = False
        return None


def query_vram() -> VramInfo:
    h = _handle()
    if h is not None:
        try:
            import pynvml

            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            name = pynvml.nvmlDeviceGetName(h)
            if isinstance(name, bytes):
                name = name.decode("utf-8", "ignore")

            util = -1
            try:
                util = int(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
            except Exception:
                pass

            power, limit = 0.0, 0.0
            try:
                power = float(pynvml.nvmlDeviceGetPowerUsage(h)) / 1000.0
            except Exception:
                pass
            try:
                limit = float(pynvml.nvmlDeviceGetEnforcedPowerLimit(h)) / 1000.0
            except Exception:
                pass

            temp, slow = -1, -1
            try:
                temp = int(
                    pynvml.nvmlDeviceGetTemperature(h, getattr(pynvml, "NVML_TEMPERATURE_GPU", 0))
                )
            except Exception:
                pass
            try:
                slow = int(
                    pynvml.nvmlDeviceGetTemperatureThreshold(
                        h, getattr(pynvml, "NVML_TEMPERATURE_THRESHOLD_SLOWDOWN", 0)
                    )
                )
            except Exception:
                pass

            return VramInfo(
                total_mb=int(mem.total / 1024 / 1024),
                used_mb=int(mem.used / 1024 / 1024),
                free_mb=int(mem.free / 1024 / 1024),
                name=str(name).replace("NVIDIA GeForce ", ""),
                available=True,
                util_pct=util,
                power_w=power,
                power_limit_w=limit,
                temp_c=temp,
                temp_slowdown_c=slow,
            )
        except Exception:
            pass

    try:  # 兜底：解析 nvidia-smi
        out = subprocess.check_output(
            ["nvidia-smi",
             "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,power.draw,power.limit,temperature.gpu",
             "--format=csv,noheader,nounits"],
            text=True, timeout=3, creationflags=0x08000000,
        ).strip().splitlines()[0]
        parts = [x.strip() for x in out.split(",")]
        name, total, used, free = parts[0], parts[1], parts[2], parts[3]

        def num(v: str, default=0.0) -> float:
            try:
                return float(v)
            except Exception:
                return default

        return VramInfo(
            int(float(total)), int(float(used)), int(float(free)),
            name.replace("NVIDIA GeForce ", ""), True,
            util_pct=int(num(parts[4], -1)) if len(parts) > 4 else -1,
            power_w=num(parts[5], 0.0) if len(parts) > 5 else 0.0,
            power_limit_w=num(parts[6], 0.0) if len(parts) > 6 else 0.0,
            temp_c=int(num(parts[7], -1)) if len(parts) > 7 else -1,
        )
    except Exception:
        return VramInfo()


def cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False
