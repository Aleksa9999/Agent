"""Reads the two skill files out of an uploaded .zip without unpacking it to disk."""

import io
import zipfile
from dataclasses import dataclass

MAX_ARCHIVE_BYTES = 256 * 1024
MAX_FILE_BYTES = 200 * 1024
MAX_MEMBERS = 50
SKILL_FILE = "SKILL.md"
TEST_FILE = "test.yaml"


@dataclass(frozen=True)
class BundleResult:
    skill_md: str = ""
    test_yaml: str = ""
    error: str | None = None  # not_zip, too_many_files, too_big, missing_skill, missing_test, ...


def _fail(code: str) -> BundleResult:
    return BundleResult(error=code)


def read_bundle(data: bytes) -> BundleResult:
    """Only the names SKILL.md and test.yaml are read; paths inside the archive are never used."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return _fail("not_zip")
    with archive:
        members = [
            m
            for m in archive.infolist()
            if not m.is_dir()
            and not m.filename.startswith("__MACOSX/")
            and not m.filename.rsplit("/", 1)[-1].startswith("._")
        ]
        if len(members) > MAX_MEMBERS:
            return _fail("too_many_files")
        found: dict[str, list[zipfile.ZipInfo]] = {SKILL_FILE: [], TEST_FILE: []}
        for member in members:
            name = member.filename.rsplit("/", 1)[-1]
            if name in found:
                found[name].append(member)
        if len(found[SKILL_FILE]) > 1 or len(found[TEST_FILE]) > 1:
            return _fail("ambiguous")
        if not found[SKILL_FILE]:
            return _fail("missing_skill")
        if not found[TEST_FILE]:
            return _fail("missing_test")
        texts = []
        for name in (SKILL_FILE, TEST_FILE):
            with archive.open(found[name][0]) as handle:
                raw = handle.read(MAX_FILE_BYTES + 1)  # a lying size header cannot bypass this
            if len(raw) > MAX_FILE_BYTES:
                return _fail("too_big")
            try:
                texts.append(raw.decode("utf-8"))
            except UnicodeDecodeError:
                return _fail("not_text")
    return BundleResult(skill_md=texts[0], test_yaml=texts[1])
