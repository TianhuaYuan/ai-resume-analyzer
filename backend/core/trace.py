import logging
import time

logger = logging.getLogger("trace")


class StepTimer:
    """全链路耗时收集器，每一步用 run() 包住异步操作即可"""

    def __init__(self):
        self.steps: dict[str, float] = {}

    async def run(self, name: str, coro):
        start = time.perf_counter()
        result = await coro
        self.steps[name] = (time.perf_counter() - start) * 1000
        return result

    def summary(self) -> str:
        parts = []
        for k, v in self.steps.items():
            parts.append(f"{k}={v:.0f}ms")
        return " | ".join(parts)

    def log(self):
        logger.info(self.summary())
