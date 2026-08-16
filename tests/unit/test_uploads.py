"""Blob storage. `fsspec` on a local temp directory is the real thing here, not a
fake — it is a filesystem, not a service, and running it is cheaper than pretending.
"""

from __future__ import annotations

import pytest

from celine.assistant.settings import settings
from celine.assistant.uploads import (
    _fs_and_root,
    _sanitize,
    _subdir,
    delete_upload,
    open_upload_stream,
    store_upload,
)


@pytest.fixture
def uploads_root(tmp_path, monkeypatch) -> str:
    monkeypatch.setattr(settings, "uploads_uri", f"file://{tmp_path}")
    return str(tmp_path)


# --- filename sanitising ----------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("my report.pdf", "my_report.pdf"),
        ("../../etc/passwd", "passwd"),
        ("/absolute/path/file.txt", "file.txt"),
        ("weißwurst.txt", "weißwurst.txt"),
        ("日本語.txt", "日本語.txt"),
        ("a!@#$%^&*()b.txt", "ab.txt"),
        ("keep-these_+.txt", "keep-these_+.txt"),
        ("", "file"),
        ("!!!", "file"),
    ],
)
def test_a_filename_is_reduced_to_a_safe_basename(given, expected):
    """Directory components are stripped and anything outside
    `[alnum] _ - . +` is dropped, so a name made entirely of punctuation becomes
    `file`.

    The allowlist is `str.isalnum`, which is Unicode-aware: accented and non-Latin
    letters survive intact. Anything downstream that assumes an ASCII filename — a
    `Content-Disposition` header, say — is assuming something this does not enforce.

    @verifies REQ-0015
    """
    assert _sanitize(given) == expected


def test_a_filename_that_is_only_dots_survives_but_is_defused_by_the_id_prefix():
    """`..` is `isalnum`-clean, so sanitising keeps it whole. What stops it becoming a
    parent-directory reference is the random id `store_upload` prepends — not the
    sanitiser.

    @verifies REQ-0015
    """
    assert _sanitize("..") == ".."


# @verifies REQ-0015
def test_a_very_long_filename_is_cut_to_200_characters():
    assert len(_sanitize("a" * 500 + ".pdf")) == 200


# --- storage layout ---------------------------------------------------------


# @verifies REQ-0015
def test_user_uploads_are_filed_under_the_owner():
    assert _subdir("user", "alice", 1700000000) == "alice/1700000000"


# @verifies REQ-0015
def test_system_uploads_are_filed_under_a_reserved_directory():
    assert _subdir("system", None, 1700000000) == "_system/1700000000"


# @verifies REQ-0015
def test_a_user_upload_without_an_owner_is_refused():
    with pytest.raises(ValueError):
        _subdir("user", None, 1700000000)


def test_an_owner_id_cannot_escape_the_uploads_root():
    """The owner id is caller-controlled — a JWT claim, or with `OAUTH2_TRUST_HEADERS`
    on, a request header. Separators are stripped rather than honoured.

    @verifies REQ-0015
    """
    # The separators are dropped; the dots that remain are inert inside one component.
    assert _subdir("user", "../../escaped", 1700000000) == "....escaped/1700000000"
    assert _subdir("user", "a/b", 1700000000) == "ab/1700000000"


def test_an_email_shaped_owner_id_survives_intact():
    """`x-auth-request-email` is a common identity, and rewriting `@` or `.` would move
    every existing user's directory for no gain — neither is a separator.

    @verifies REQ-0015
    """
    assert _subdir("user", "alice@example.test", 1700000000) == (
        "alice@example.test/1700000000"
    )


@pytest.mark.parametrize("owner", ["..", ".", "/", "///", "!!!"])
def test_an_owner_id_that_sanitises_to_nothing_usable_is_refused(owner):
    """Coercing it to a placeholder would file two different callers' uploads together.

    @verifies REQ-0015
    """
    with pytest.raises(ValueError, match="not usable as a path"):
        _subdir("user", owner, 1700000000)


# --- round trip -------------------------------------------------------------


# @verifies REQ-0015
async def test_a_stored_file_can_be_read_back_and_deleted(uploads_root):
    stored = await store_upload(
        scope="user",
        owner_user_id="alice",
        filename="my notes.txt",
        content_type="text/plain",
        data=b"hello world",
    )

    assert stored.filename == "my_notes.txt"
    assert stored.size_bytes == 11
    assert stored.uri.startswith("file://")
    assert "/alice/" in stored.path

    assert b"".join(open_upload_stream(stored.path)) == b"hello world"

    await delete_upload(stored.path)
    fs, _ = _fs_and_root()
    assert not fs.exists(stored.path)


async def test_two_uploads_of_the_same_name_in_the_same_second_do_not_collide(
    uploads_root,
):
    """The timestamp only buys a directory; a random prefix on the file is what keeps
    two uploads apart.

    @verifies REQ-0015
    """
    first = await store_upload(
        scope="user", owner_user_id="alice", filename="a.txt", content_type=None, data=b"1"
    )
    second = await store_upload(
        scope="user", owner_user_id="alice", filename="a.txt", content_type=None, data=b"2"
    )

    assert first.path != second.path
    assert b"".join(open_upload_stream(first.path)) == b"1"


async def test_deleting_a_file_that_is_already_gone_is_not_an_error(uploads_root):
    """The route deletes the row first and the blob second. @verifies REQ-0015"""
    await delete_upload(f"{uploads_root}/nothing/here.txt")


# @verifies REQ-0015
def test_a_bare_path_uploads_uri_is_treated_as_a_local_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "uploads_uri", str(tmp_path))
    fs, root = _fs_and_root()
    assert root == str(tmp_path)
    assert fs.protocol in ("file", ("file", "local"))
