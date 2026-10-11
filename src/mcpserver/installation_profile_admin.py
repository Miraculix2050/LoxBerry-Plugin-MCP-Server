"""LoxBerry-authorized profile management using fresh service-owned visibility."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from mcpserver.admin_errors import AdminError
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.installation_profile import (
    BindingInput,
    ProfileError,
    ProfileStore,
    installation_identity,
    project_profile,
    visible_controls,
)
from mcpserver.loxone.endpoint import MiniserverEndpoint


def _context(config: PluginConfig) -> tuple[str, dict[str, Any]]:
    from mcpserver.event_history_admin import _monitor

    structure = asyncio.run(asyncio.wait_for(_monitor(config).visible_structure(), timeout=30))
    return installation_identity(
        MiniserverEndpoint.parse(config.loxone_endpoint).origin, structure
    ), visible_controls(structure)


def dispatch_profile(
    action: str, payload: object, config_store: AtomicConfigStore
) -> dict[str, Any]:
    if action not in {"profile_page", "profile_put", "profile_delete"} or not isinstance(
        payload, dict
    ):
        raise AdminError("Profile request is invalid")
    config = config_store.load()
    data = Path(os.getenv("LBPDATA", ""))
    if not data.is_absolute() or not config.loxone_endpoint:
        raise AdminError("Profile is unavailable", code="temporarily_unavailable")
    try:
        installation, controls = _context(config)
        store = ProfileStore(data / "installation-profile.json")
        if action == "profile_page":
            if set(payload) - {"offset", "limit"}:
                raise ProfileError("profile_request_invalid")
            offset, limit = payload.get("offset", 0), payload.get("limit", 100)
            if (
                type(offset) is not int
                or not 0 <= offset <= 256
                or type(limit) is not int
                or not 1 <= limit <= 100
            ):
                raise ProfileError("profile_request_invalid")
            result = project_profile(
                store.read(installation), installation, controls, offset=offset, limit=limit
            )
            # Bound selection data separately; exact IDs can also come from Explorer.
            sources = []
            for control in sorted(controls.values(), key=lambda item: item.uuid):
                for name, uuid in control.state_uuids:
                    sources.append(
                        {
                            "control_uuid": control.uuid,
                            "control_name": control.name,
                            "source_kind": "state",
                            "source_id": uuid,
                            "source_name": name,
                        }
                    )
                    if len(sources) > 500:
                        break
                for series in control.statistic_series:
                    if len(sources) > 500:
                        break
                    sources.append(
                        {
                            "control_uuid": control.uuid,
                            "control_name": control.name,
                            "source_kind": "statistic",
                            "source_id": series.series_id,
                            "source_name": series.title,
                        }
                    )
                if len(sources) > 500:
                    break
            result.update(
                {
                    "sources": sources[:500],
                    "sources_truncated": len(sources) > 500,
                    "installation": installation,
                }
            )
            return result
        if payload.get("confirm") is not True:
            raise ProfileError("confirmation_required")
        revision = payload.get("revision")
        if type(revision) is not int or not 0 <= revision < 2**31 - 1:
            raise ProfileError("profile_revision_invalid")
        if payload.get("installation") != installation:
            raise ProfileError("profile_installation_changed")

        def mutate(current: PluginConfig, _save: object) -> dict[str, Any]:
            if current.loxone_endpoint != config.loxone_endpoint:
                raise ProfileError("profile_installation_changed")
            if action == "profile_put":
                if set(payload) != {"installation", "revision", "confirm", "binding"}:
                    raise ProfileError("profile_request_invalid")
                binding = BindingInput.model_validate(payload["binding"])
                control = controls.get(binding.control_uuid)
                if control is None:
                    raise ProfileError("profile_source_not_visible")
                document = store.put(
                    installation,
                    revision,
                    binding,
                    control,
                    origin="local_admin",
                    actor_ref=hashlib.sha256(b"local_admin").hexdigest(),
                )
            else:
                if set(payload) != {"installation", "revision", "confirm", "binding_id"}:
                    raise ProfileError("profile_request_invalid")
                binding_id = payload["binding_id"]
                if binding_id is not None and (
                    not isinstance(binding_id, str) or not 1 <= len(binding_id) <= 64
                ):
                    raise ProfileError("profile_request_invalid")
                document = store.delete(installation, revision, binding_id)
            return project_profile(document, installation, controls)

        return config_store.transaction(mutate)
    except (ProfileError, ValidationError) as exc:
        code = exc.code if isinstance(exc, ProfileError) else "profile_binding_invalid"
        raise AdminError("Profile operation rejected", code=code) from None
    except (TimeoutError, OSError, RuntimeError) as exc:
        raise AdminError("Profile source unavailable", code="temporarily_unavailable") from exc
