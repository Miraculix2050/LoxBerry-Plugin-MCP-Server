import io
import struct
import zipfile

import pytest

from mcpserver.loxone.project.models import ProjectError, ProjectLimits
from mcpserver.loxone.project.source import unpack_project


def archive(names):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for name in names:
            target.writestr(name, struct.pack("<IIII", 0xAABBCCEE, 1, 1, 0) + b"x")
    return output.getvalue()


def test_archive_fingerprint_ignores_order():
    first = unpack_project(archive(["one.LoxCC", "two.LoxCC"]))
    second = unpack_project(archive(["two.LoxCC", "one.LoxCC"]))
    assert first.fingerprint == second.fingerprint
    assert len(first.files) == 2


def test_archive_accepts_bounded_companions_without_fingerprinting_them():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        target.writestr("project.LoxCC", struct.pack("<IIII", 0xAABBCCEE, 1, 1, 0) + b"x")
        target.writestr("companion.json", b"{}")
    bundle = unpack_project(output.getvalue())
    assert tuple(member.key for member in bundle.files) == ("project.LoxCC",)


def test_archive_requires_at_least_one_project_member():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        target.writestr("companion.json", b"{}")
    with pytest.raises(ProjectError, match="without_project"):
        unpack_project(output.getvalue())


@pytest.mark.parametrize("names", [["../x.LoxCC"], ["/x.LoxCC"], ["x.zip"], ["x.LoxCC", "X.LoxCC"]])
def test_archive_rejects_unsafe_or_ambiguous_entries(names):
    with pytest.raises(ProjectError):
        unpack_project(archive(names))


def test_archive_enforces_actual_limits():
    with pytest.raises(ProjectError, match="archive_limit"):
        unpack_project(archive(["x.LoxCC"]), ProjectLimits(expanded_bytes=4))
    with pytest.raises(ProjectError, match="archive_limit"):
        unpack_project(archive(["a.LoxCC", "b.LoxCC"]), ProjectLimits(archive_entries=1))


def test_rejects_login_page():
    with pytest.raises(ProjectError, match="format_invalid"):
        unpack_project(b"<html>secret</html>")
