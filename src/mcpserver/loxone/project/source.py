"""Bounded in-memory archive handling for the fixed project resource."""

import hashlib
import io
import struct
import zipfile
from pathlib import PurePosixPath

from .models import DEFAULT_LIMITS, ProjectBundle, ProjectError, ProjectFile, ProjectLimits


def unpack_project(data: bytes, limits: ProjectLimits = DEFAULT_LIMITS) -> ProjectBundle:
    if not data or len(data) > limits.download_bytes:
        raise ProjectError("project_download_limit")
    members: list[ProjectFile] = []
    try:
        if data.startswith(b"PK"):
            # Bound central-directory entry allocation before ZipFile constructs it.
            end = data.rfind(b"PK\x05\x06", max(0, len(data) - 65557))
            if end < 0 or len(data) < end + 22:
                raise ProjectError("project_archive_invalid")
            disk, directory_disk, disk_count, count = struct.unpack_from("<HHHH", data, end + 4)
            if (
                disk
                or directory_disk
                or disk_count != count
                or not 0 < count <= limits.archive_entries
            ):
                raise ProjectError("project_archive_limit")
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) != count:
                    raise ProjectError("project_archive_invalid")
                names: set[str] = set()
                total = 0
                for entry in entries:
                    name = entry.filename
                    path = PurePosixPath(name)
                    if (
                        entry.is_dir()
                        or entry.flag_bits & 1
                        or "\\" in name
                        or path.is_absolute()
                        or ".." in path.parts
                        or ":" in name
                        or name.casefold() in names
                        or not name.lower().endswith(".loxcc")
                        or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                    ):
                        raise ProjectError("project_archive_unsupported")
                    names.add(name.casefold())
                    total += entry.file_size
                    if total > limits.expanded_bytes:
                        raise ProjectError("project_archive_limit")
                    with archive.open(entry) as source:
                        body = source.read(min(entry.file_size, limits.expanded_bytes) + 1)
                    if len(body) != entry.file_size or not body.startswith(b"\xee\xcc\xbb\xaa"):
                        raise ProjectError("project_archive_invalid")
                    members.append(ProjectFile(name, body))
        else:
            if not data.startswith(b"\xee\xcc\xbb\xaa"):
                raise ProjectError("project_format_invalid")
            members.append(ProjectFile("sps.LoxCC", data))
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as exc:
        if isinstance(exc, ProjectError):
            raise
        raise ProjectError("project_archive_invalid") from None
    members.sort(key=lambda member: member.key)
    digest = hashlib.sha256()
    for member in members:
        key = member.key.encode("utf-8")
        digest.update(len(key).to_bytes(4, "big"))
        digest.update(key)
        digest.update(hashlib.sha256(member.content).digest())
    return ProjectBundle(digest.hexdigest(), tuple(members), len(data))
