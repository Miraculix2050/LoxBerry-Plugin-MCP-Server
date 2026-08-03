"""Interactive, secret-safe Phase-0 test against an explicitly named Gen. 1 target."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from collections.abc import Iterable
from uuid import uuid4

from mcpserver.loxone.cache import UserStateCache
from mcpserver.loxone.client import LoxoneClient, LoxoneToken, MiniserverEndpoint
from mcpserver.loxone.models import Control, Freshness


def _read_password(*, from_stdin: bool) -> str:
    password = (
        sys.stdin.readline().rstrip("\r\n")
        if from_stdin
        else getpass.getpass("Dedicated Loxone test-user password: ")
    )
    if not password:
        raise RuntimeError("Dedicated Loxone test-user password is empty")
    return password


def _control_uuids(controls: Iterable[Control]) -> set[str]:
    result: set[str] = set()
    for control in controls:
        result.add(control.uuid)
        result.update(_control_uuids(control.subcontrols))
    return result


def _state_uuids(controls: Iterable[Control]) -> set[str]:
    result: set[str] = set()
    for control in controls:
        result.update(uuid for _name, uuid in control.state_uuids)
        result.update(_state_uuids(control.subcontrols))
    return result


async def _observe_once(
    client: LoxoneClient,
    token_subject: str,
    token: LoxoneToken,
    cache: UserStateCache,
    visible_states: set[str],
    timeout: float,
) -> str:
    session = await client.open_session(token)
    cache.begin_connection(token_subject)
    try:
        async with asyncio.timeout(timeout):
            async for events in session.state_events():
                cache.apply(token_subject, events, allowed_uuids=visible_states)
                matching = next(
                    (event.uuid for event in events if event.uuid in visible_states), None
                )
                if matching is not None:
                    return matching
    finally:
        await session.close()
        cache.disconnect(token_subject)
    raise RuntimeError("No user-visible state event was received")


async def _observe_snapshot_and_delta(
    client: LoxoneClient,
    token_subject: str,
    token: LoxoneToken,
    cache: UserStateCache,
    visible_states: set[str],
    timeout: float,
) -> str:
    session = await client.open_session(token)
    cache.begin_connection(token_subject)
    initial: dict[str, object] = {}
    try:
        async with asyncio.timeout(timeout):
            async for events in session.state_events():
                cache.apply(token_subject, events, allowed_uuids=visible_states)
                for event in events:
                    if event.uuid not in visible_states:
                        continue
                    if event.uuid in initial and initial[event.uuid] != event.value:
                        return event.uuid
                    initial[event.uuid] = event.value
    finally:
        await session.close()
        cache.disconnect(token_subject)
    raise RuntimeError("No changed user-visible state delta was received")


async def _run(args: argparse.Namespace) -> None:
    password = _read_password(from_stdin=args.password_stdin)
    endpoint = MiniserverEndpoint.parse_gen1(args.endpoint)
    client = LoxoneClient(endpoint, client_uuid=uuid4(), client_name="LoxBerry MCP Phase-0 Test")
    token = None
    primary_error: BaseException | None = None
    try:
        probe = await asyncio.wait_for(client.probe(), timeout=args.operation_timeout)
        if probe.firmware != args.expected_firmware:
            raise RuntimeError("Miniserver firmware does not match the expected target")
        print("LOXONE_PROBE=pass", flush=True)
        token = await asyncio.wait_for(
            client.acquire_token(args.username, password), timeout=args.operation_timeout
        )
        password = ""
        print("LOXONE_TOKEN_ACQUISITION=pass", flush=True)

        session = await asyncio.wait_for(client.open_session(token), timeout=args.operation_timeout)
        try:
            structure = await asyncio.wait_for(
                session.load_structure(), timeout=args.operation_timeout
            )
        finally:
            await asyncio.wait_for(session.close(), timeout=args.operation_timeout)
        print("LOXONE_STRUCTURE_FETCH=pass", flush=True)

        controls = _control_uuids(structure.controls)
        if args.visible_control not in controls:
            raise RuntimeError("Expected visible control is absent from the restricted structure")
        if args.hidden_control in controls:
            raise RuntimeError("Expected hidden control leaked into the restricted structure")
        visible_states = _state_uuids(structure.controls)
        if not visible_states:
            raise RuntimeError("Restricted structure does not contain a state UUID")
        print("LOXONE_RESTRICTED_STRUCTURE=pass", flush=True)

        subject = f"{probe.serial}:{args.username}"
        cache = UserStateCache()
        print(
            "Operate one visible test control through its normal UI now; waiting for a delta.",
            flush=True,
        )
        observed = await _observe_snapshot_and_delta(
            client, subject, token, cache, visible_states, args.observe_seconds
        )
        if cache.get(subject, observed).freshness is not Freshness.STALE:
            raise RuntimeError("Disconnected state was not marked stale")
        observed = await _observe_once(
            client, subject, token, cache, visible_states, args.observe_seconds
        )
        if cache.get(subject, observed).freshness is not Freshness.STALE:
            raise RuntimeError("Reconnected state was not marked stale after the second close")

        print(f"LOXONE_FIRMWARE={probe.firmware}")
        print("LOXONE_WEBSOCKET_SNAPSHOT=pass", flush=True)
        print("LOXONE_WEBSOCKET_RECONNECT=pass", flush=True)
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        password = ""
        if token is not None:
            try:
                await asyncio.wait_for(client.kill_token(token), timeout=args.operation_timeout)
            except Exception:
                print("LOXONE_TOKEN_REVOCATION=fail", flush=True)
                if primary_error is None:
                    raise
            else:
                print("LOXONE_TOKEN_REVOCATION=pass", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the interactive Gen. 1 Phase-0 test without putting secrets on argv."
    )
    parser.add_argument("--endpoint", required=True, help="Canonical private HTTP origin")
    parser.add_argument("--username", required=True, help="Dedicated restricted Loxone user")
    parser.add_argument("--visible-control", required=True, help="Control UUID visible to the user")
    parser.add_argument("--hidden-control", required=True, help="Control UUID hidden from the user")
    parser.add_argument("--expected-firmware", default="17.1.7.27")
    parser.add_argument("--observe-seconds", type=float, default=60.0)
    parser.add_argument("--operation-timeout", type=float, default=20.0)
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read one password line from redirected stdin; never from argv or environment",
    )
    args = parser.parse_args()
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
