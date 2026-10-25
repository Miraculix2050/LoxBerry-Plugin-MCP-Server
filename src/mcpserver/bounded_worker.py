"""Offload work while retaining the caller's existing admission until it stops."""

import asyncio
from collections.abc import Callable
from contextlib import suppress
from typing import Any


async def run_admitted_worker[T](function: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Repeated cancellation (for example shutdown after a timeout) must not
        # release the caller's admission while its thread is still running.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        with suppress(Exception):
            task.result()
        raise
