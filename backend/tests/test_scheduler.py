import asyncio
import unittest
from unittest.mock import patch

from backend.app.core.config import AppConfig
from backend.app.core.scheduler import scheduler_loop


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_waits_until_next_planned_start(self) -> None:
        config = AppConfig(schedule_minutes=1, app_time_zone="Asia/Shanghai")
        sleeps: list[float] = []

        async def fake_to_thread(func, *args, **kwargs):
            return None

        async def fake_sleep(delay: float):
            sleeps.append(delay)
            raise asyncio.CancelledError

        monotonic_values = iter([100.0, 100.0, 100.0, 110.0, 110.0, 110.0])

        with (
            patch("backend.app.core.scheduler.asyncio.to_thread", side_effect=fake_to_thread),
            patch("backend.app.core.scheduler.asyncio.sleep", side_effect=fake_sleep),
            patch("backend.app.core.scheduler.time.monotonic", side_effect=lambda: next(monotonic_values)),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await scheduler_loop(config)

        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 50.0)


if __name__ == "__main__":
    unittest.main()
