"""Offline rota integrity, bounded hostile input and minimized CLI outcomes."""

from __future__ import annotations

import hashlib
import io
import json
import os
import struct
import subprocess
import sys
import zipfile
import zlib
from types import SimpleNamespace

import pytest

from maru.workforce import rota, rota_integrity

CONTENT = {
    "rota.json": b'{"private_label": "SYNTHETIC_SENTINEL"}',
    "schema.json": b'{"$ref": "https://invalid.example/do-not-fetch"}',
    "rota.html": b"<script>throw 'SYNTHETIC_SENTINEL';</script>",
    "README.txt": b"Fictional copy for integrity testing only.",
}


def _manifest(content):
    return {
        "format": "maru.workforce-rota-manifest",
        "version": 1,
        "files": {
            name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            for name, raw in content.items()
        },
    }


def _package(
    tmp_path, *, content=None, manifest=None, manifest_bytes=None, entries=None
):
    content = CONTENT if content is None else content
    manifest = _manifest(content) if manifest is None else manifest
    members = list(content.items()) if entries is None else entries
    members = [
        *members,
        (
            "manifest.json",
            json.dumps(manifest).encode() if manifest_bytes is None else manifest_bytes,
        ),
    ]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in members:
            archive.writestr(name, raw)
    path = tmp_path / "private-SYNTHETIC_SENTINEL.zip"
    path.write_bytes(output.getvalue())
    return path


def _refused(path, code):
    before = path.read_bytes()
    with pytest.raises(rota_integrity.RotaIntegrityError, match=f"^{code}$"):
        rota_integrity.verify_rota_package(path)
    assert path.read_bytes() == before


def test_real_exporter_output_is_accepted_without_changing_or_extracting_it(tmp_path):
    payload = {
        "format": "maru.workforce-rota",
        "version": 1,
        "observed_at": "2030-10-26T12:00:00+00:00",
        "scope": {
            "organization_id": "00000000-0000-4000-8000-000000000001",
            "series_id": "00000000-0000-4000-8000-000000000002",
            "edition_id": "00000000-0000-4000-8000-000000000003",
            "edition_name": "Fictional convention",
            "edition_version": 1,
            "edition_lifecycle": "preparing",
            "starts_on": "2030-10-26",
            "ends_on": "2030-10-28",
            "time_zone": "Europe/Budapest",
            "profile_code": "workforce_only",
            "profile_version": 1,
        },
        "limitations": list(rota.LIMITATIONS),
        "shifts": [],
    }
    package = rota.rota_package(
        snapshot=rota.RotaSnapshot(SimpleNamespace(), payload),
        printable_html="<!doctype html><main><h1>Fictional rota</h1></main>",
    )
    path = tmp_path / "rota.zip"
    path.write_bytes(package)
    summary = rota_integrity.verify_rota_package(path)
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        assert summary.uncompressed_bytes == sum(
            i.file_size for i in archive.infolist()
        )
    assert summary.archive_bytes == len(package)
    assert summary.checked_content_members == 4
    assert path.read_bytes() == package
    assert list(tmp_path.iterdir()) == [path]
    assert rota_integrity.MAX_UNCOMPRESSED_BYTES == rota.MAX_ROTA_BYTES


def test_hash_success_does_not_imply_schema_or_html_safety(tmp_path, capsys):
    path = _package(tmp_path)
    assert rota_integrity.main([str(path)]) == 0
    result = capsys.readouterr()
    assert result.err == ""
    assert "five required files; 4 content hashes" in result.out
    assert "does not establish authenticity, schema validity" in result.out
    assert "SYNTHETIC_SENTINEL" not in result.out
    assert "invalid.example" not in result.out
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("member", sorted(rota_integrity.CONTENT_MEMBERS))
def test_each_modified_content_member_is_refused_with_unchanged_source(
    tmp_path, member
):
    original = _manifest(CONTENT)
    changed = {**CONTENT, member: CONTENT[member][::-1]}
    _refused(_package(tmp_path, content=changed, manifest=original), "content_mismatch")


@pytest.mark.parametrize("member", sorted(rota_integrity.CONTENT_MEMBERS))
def test_missing_and_extra_members_are_refused(tmp_path, member):
    missing = {k: v for k, v in CONTENT.items() if k != member}
    _refused(_package(tmp_path, content=missing), "unsupported_archive_layout")
    extra = {**CONTENT, "unexpected.txt": b"untrusted"}
    _refused(_package(tmp_path, content=extra), "unsupported_archive_layout")


@pytest.mark.parametrize(
    "name",
    ["../rota.json", "/rota.json", "sub/rota.json", "ROTA.JSON", "rota.json\x00evil"],
)
def test_non_fixed_member_names_never_become_files(tmp_path, name):
    entries = [(name if k == "rota.json" else k, v) for k, v in CONTENT.items()]
    # ZipFile strips a NUL from its own writer input; patch the raw name below.
    if "\x00" in name:
        path = _package(tmp_path)
        raw = path.read_bytes().replace(b"rota.json", b"rota\x00json")
        path.write_bytes(raw)
    else:
        path = _package(tmp_path, entries=entries)
    _refused(path, "invalid_members")
    assert list(tmp_path.iterdir()) == [path]


def test_duplicate_member_with_another_member_missing_is_refused(tmp_path):
    entries = [
        ("rota.json" if k == "schema.json" else k, v) for k, v in CONTENT.items()
    ]
    with pytest.warns(UserWarning, match="Duplicate name"):
        path = _package(tmp_path, entries=entries)
    _refused(path, "invalid_members")


@pytest.mark.parametrize("mode", [0o120777, 0o040755, 0o020600])
def test_symlink_directory_and_device_members_are_refused(tmp_path, mode):
    entry = zipfile.ZipInfo("rota.json")
    entry.create_system = 3
    entry.external_attr = mode << 16
    entries = [(entry if k == "rota.json" else k, v) for k, v in CONTENT.items()]
    _refused(_package(tmp_path, entries=entries), "unsupported_member")


def test_dos_directory_flag_without_a_directory_name_is_refused(tmp_path):
    entry = zipfile.ZipInfo("rota.json")
    entry.external_attr = (0o600 << 16) | 0x10
    entries = [(entry if k == "rota.json" else k, v) for k, v in CONTENT.items()]
    _refused(_package(tmp_path, entries=entries), "unsupported_member")


@pytest.mark.parametrize(
    ("field", "value"),
    [("version", True), ("version", 2), ("format", "other"), ("extra", "private")],
)
def test_manifest_root_is_closed_and_exactly_versioned(tmp_path, field, value):
    manifest = _manifest(CONTENT)
    manifest[field] = value
    _refused(_package(tmp_path, manifest=manifest), "invalid_manifest")


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        {},
        {"bytes": 1},
        {"bytes": True, "sha256": "0" * 64},
        {"bytes": -1, "sha256": "0" * 64},
        {"bytes": 1, "sha256": "A" * 64},
        {"bytes": 1, "sha256": "0" * 64, "extra": True},
    ],
)
def test_manifest_member_metadata_is_closed_bounded_and_unambiguous(tmp_path, bad):
    manifest = _manifest(CONTENT)
    manifest["files"]["rota.json"] = bad
    _refused(_package(tmp_path, manifest=manifest), "invalid_manifest")


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b"null",
        b"{",
        b"\xff",
        b'{"version":1,"version":1}',
        b'{"files":NaN}',
        b'{"files":Infinity}',
    ],
)
def test_invalid_or_duplicate_json_is_refused(tmp_path, raw):
    _refused(_package(tmp_path, manifest_bytes=raw), "invalid_manifest")


def test_duplicate_nested_key_is_refused_even_when_values_match(tmp_path):
    raw = (
        json.dumps(_manifest(CONTENT))
        .encode()
        .replace(b'"bytes":', b'"bytes":0,"bytes":', 1)
    )
    _refused(_package(tmp_path, manifest_bytes=raw), "invalid_manifest")


def test_manifest_member_inventory_must_be_exact(tmp_path):
    manifest = _manifest(CONTENT)
    manifest["files"].pop("rota.json")
    _refused(_package(tmp_path, manifest=manifest), "invalid_manifest")


@pytest.mark.parametrize(
    ("index", "value"), [(1, 1), (2, 1), (3, 4), (4, 6), (5, 4097), (6, 0), (7, 1)]
)
def test_unsupported_end_records_are_refused_before_zip_entry_construction(
    tmp_path, monkeypatch, index, value
):
    path = _package(tmp_path)
    raw = path.read_bytes()
    end = list(struct.unpack("<4s4H2LH", raw[-22:]))
    end[index] = value
    path.write_bytes(raw[:-22] + struct.pack("<4s4H2LH", *end))
    monkeypatch.setattr(
        rota_integrity, "ZipFile", lambda *_: pytest.fail("entries constructed")
    )
    _refused(path, "unsupported_archive_layout")


def test_compressed_and_uncompressed_limits_are_checked_before_member_reads(
    tmp_path, monkeypatch
):
    path = _package(tmp_path)
    monkeypatch.setattr(rota_integrity, "MAX_ARCHIVE_BYTES", len(path.read_bytes()) - 1)
    _refused(path, "archive_too_large")
    monkeypatch.setattr(rota_integrity, "MAX_ARCHIVE_BYTES", 1_000_000)
    monkeypatch.setattr(rota_integrity, "MAX_UNCOMPRESSED_BYTES", 10)
    monkeypatch.setattr(
        rota_integrity, "_member_bytes", lambda *_: pytest.fail("member read")
    )
    _refused(path, "contents_too_large")


def test_manifest_limit_refuses_bounded_but_excessive_json(tmp_path):
    _refused(_package(tmp_path, manifest_bytes=b" " * 8193), "invalid_manifest")


def test_actual_compressible_overflow_is_refused_before_decompression(
    tmp_path, monkeypatch
):
    content = {**CONTENT, "rota.html": b"x" * (16_777_216 + 1)}
    path = _package(tmp_path, content=content)
    assert path.stat().st_size < 65_536
    monkeypatch.setattr(
        rota_integrity, "_member_bytes", lambda *_: pytest.fail("member read")
    )
    _refused(path, "contents_too_large")


def test_small_zip64_local_header_is_refused(tmp_path):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, raw in CONTENT.items():
            with archive.open(name, "w", force_zip64=True) as stream:
                stream.write(raw)
        archive.writestr("manifest.json", json.dumps(_manifest(CONTENT)))
    path = tmp_path / "zip64.zip"
    path.write_bytes(output.getvalue())
    _refused(path, "unsupported_member")


@pytest.mark.parametrize("kind", ["comment", "compression"])
def test_member_comments_and_unsupported_compression_are_refused(tmp_path, kind):
    entry = zipfile.ZipInfo("rota.json")
    if kind == "comment":
        entry.comment = b"SYNTHETIC_SENTINEL"
    else:
        entry.compress_type = zipfile.ZIP_BZIP2
    entries = [(entry if k == "rota.json" else k, v) for k, v in CONTENT.items()]
    _refused(_package(tmp_path, entries=entries), "unsupported_member")


def test_encrypted_member_flag_is_refused(tmp_path):
    path = _package(tmp_path)
    raw = bytearray(path.read_bytes())
    central = raw.index(b"PK\x01\x02")
    struct.pack_into("<H", raw, central + 8, 1)
    path.write_bytes(raw)
    _refused(path, "unsupported_member")


def test_bad_crc_is_refused_without_source_details(tmp_path, capsys):
    path = _package(tmp_path)
    raw = bytearray(path.read_bytes())
    central = raw.index(b"PK\x01\x02")
    struct.pack_into("<L", raw, central + 16, 0)
    path.write_bytes(raw)
    assert rota_integrity.main([str(path)]) == 1
    result = capsys.readouterr()
    assert result.out == ""
    assert "invalid_archive" in result.err
    assert "SYNTHETIC_SENTINEL" not in result.err
    assert "rota.json" not in result.err


def test_trailing_data_and_a_non_zip_file_are_refused(tmp_path):
    path = _package(tmp_path)
    path.write_bytes(path.read_bytes() + b"untrusted trailing data")
    _refused(path, "unsupported_archive_layout")
    path.write_bytes(b"not a ZIP")
    _refused(path, "invalid_archive")


def test_missing_file_has_a_fixed_non_identifying_outcome(tmp_path, capsys):
    assert rota_integrity.main([str(tmp_path / "SYNTHETIC_SENTINEL.zip")]) == 1
    result = capsys.readouterr()
    assert result.out == ""
    assert "unavailable_file" in result.err
    assert "SYNTHETIC_SENTINEL" not in result.err


def test_real_cli_initializes_no_django_and_uses_no_network_or_output_files(tmp_path):
    path = _package(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    code = """
import os, sys
write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
def deny(event, args):
    if event.startswith('socket.') or event in ('os.mkdir', 'subprocess.Popen'):
        raise AssertionError(event)
    if event == 'import' and str(args[0]).split('.')[0] in {'django', 'psycopg'}:
        raise AssertionError('server initialization')
    if event == 'open' and args[2] & write_flags:
        raise AssertionError('file write')
assert 'django' not in sys.modules and 'psycopg' not in sys.modules
sys.addaudithook(deny)
from maru.workforce.rota_integrity import main
raise SystemExit(main(sys.argv[1:]))
"""
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "DJANGO_SETTINGS_MODULE": "must_not_initialize",
    }
    result = subprocess.run(  # noqa: S603 - fixed interpreter/script and owned fixture
        [sys.executable, "-c", code, str(path)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Integrity matches the supplied manifest only" in result.stdout
    assert result.stderr == ""
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def _prefix_sized_package(tmp_path, member, suffix, compression):
    members = {
        **CONTENT,
        "manifest.json": json.dumps(_manifest(CONTENT)).encode(),
    }
    prefix = members[member]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, raw in members.items():
            archive.writestr(name, raw + suffix if name == member else raw)
    raw = bytearray(output.getvalue())
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        local = archive.getinfo(member).header_offset
    central = struct.unpack_from("<L", raw, len(raw) - 6)[0]
    while True:
        name_size, extra_size, comment_size = struct.unpack_from(
            "<3H", raw, central + 28
        )
        name = raw[central + 46 : central + 46 + name_size].decode()
        if name == member:
            break
        central += 46 + name_size + extra_size + comment_size
    for offset, crc_offset, size_offset in [(local, 14, 22), (central, 16, 24)]:
        struct.pack_into("<L", raw, offset + crc_offset, zlib.crc32(prefix))
        struct.pack_into("<L", raw, offset + size_offset, len(prefix))
    path = tmp_path / "misleading-size.zip"
    path.write_bytes(raw)
    return path


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
@pytest.mark.parametrize("member", sorted(rota_integrity.CONTENT_MEMBERS))
def test_complete_content_never_accepts_a_matching_declared_prefix(
    tmp_path, member, compression
):
    path = _prefix_sized_package(tmp_path, member, b"concealed bytes", compression)
    _refused(path, "content_mismatch")


def test_actual_inflation_limit_does_not_trust_declared_small_size(tmp_path):
    path = _prefix_sized_package(
        tmp_path, "rota.html", b"x" * 16_777_217, zipfile.ZIP_DEFLATED
    )
    assert path.stat().st_size < 65_536
    _refused(path, "contents_too_large")


def test_complete_manifest_limit_does_not_trust_a_declared_json_prefix(tmp_path):
    path = _prefix_sized_package(
        tmp_path, "manifest.json", b" " * 8193, zipfile.ZIP_DEFLATED
    )
    _refused(path, "invalid_manifest")


def test_zip64_locator_cannot_override_a_small_ordinary_directory(
    tmp_path, monkeypatch
):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        members = {**CONTENT, "manifest.json": json.dumps(_manifest(CONTENT)).encode()}
        for name, raw in members.items():
            entry = zipfile.ZipInfo(name)
            entry.extra = struct.pack("<2H", 0xCAFE, 900) + b"x" * 900
            archive.writestr(entry, raw)
    raw = output.getvalue()
    end = list(struct.unpack("<4s4H2LH", raw[-22:]))
    directory_size, directory_offset = end[5:7]
    assert directory_size > 4096
    zip64 = struct.pack(
        "<4sQ2H2L4Q",
        b"PK\x06\x06",
        44,
        45,
        45,
        0,
        0,
        5,
        5,
        directory_size,
        directory_offset,
    )
    locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, len(raw) - 22, 1)
    end[5:7] = [100, len(raw) - 22 + len(zip64) + len(locator) - 100]
    path = tmp_path / "zip64-directory-override.zip"
    path.write_bytes(raw[:-22] + zip64 + locator + struct.pack("<4s4H2LH", *end))
    with zipfile.ZipFile(path) as archive:
        assert len(archive.infolist()) == 5
    monkeypatch.setattr(
        rota_integrity, "ZipFile", lambda *_: pytest.fail("entries constructed")
    )
    _refused(path, "unsupported_archive_layout")


def test_nonregular_input_is_opened_nonblocking_before_descriptor_validation(
    tmp_path, monkeypatch
):
    nonblock = getattr(os, "O_NONBLOCK", 0x10000000)
    monkeypatch.setattr(os, "O_NONBLOCK", nonblock, raising=False)
    original = os.open
    flags_seen = []

    def observe(path, flags):
        flags_seen.append(flags)
        return original(path, flags & ~nonblock)

    monkeypatch.setattr(os, "open", observe)
    with pytest.raises(rota_integrity.RotaIntegrityError, match=r"^unavailable_file$"):
        rota_integrity.verify_rota_package(tmp_path)
    assert len(flags_seen) == 1
    assert flags_seen[0] & nonblock


def test_real_nonregular_input_never_waits_for_a_fifo_writer(tmp_path):
    path = tmp_path / "private-SYNTHETIC_SENTINEL"
    if os.name == "posix":
        os.mkfifo(path)
    else:
        path.mkdir()
    result = subprocess.run(  # noqa: S603 - fixed interpreter and owned nonregular input
        [sys.executable, "-B", "-m", "maru.workforce.rota_integrity", str(path)],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 1
    assert "unavailable_file" in result.stderr
    assert "SYNTHETIC_SENTINEL" not in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["private-SYNTHETIC_SENTINEL.zip", "private-edition-SYNTHETIC_SENTINEL.zip"],
        ["--private-SYNTHETIC_SENTINEL", "private-edition.zip"],
    ],
)
def test_argument_errors_use_fixed_text_without_echoing_rejected_values(
    arguments, capsys
):
    with pytest.raises(SystemExit) as error:
        rota_integrity.main(arguments)
    assert error.value.code == 2
    result = capsys.readouterr()
    assert result.out == ""
    assert (
        result.err == "Rota integrity command failed: invalid_arguments. Use --help.\n"
    )


@pytest.mark.parametrize(
    "extra", ["private-edition-SYNTHETIC_SENTINEL.zip", "--SYNTHETIC_SENTINEL"]
)
def test_real_cli_argument_failures_never_print_a_path_or_unknown_option(
    tmp_path, extra
):
    path = _package(tmp_path)
    before = path.read_bytes()
    result = subprocess.run(  # noqa: S603 - fixed interpreter and synthetic arguments
        [sys.executable, "-B", "-m", "maru.workforce.rota_integrity", str(path), extra],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert (
        result.stderr
        == "Rota integrity command failed: invalid_arguments. Use --help.\n"
    )
    assert path.read_bytes() == before


@pytest.mark.parametrize("ending", ["extra", "truncated"])
def test_deflate_must_reach_its_complete_end_without_trailing_compressed_bytes(
    tmp_path, ending
):
    path = _package(tmp_path)
    raw = bytearray(path.read_bytes())
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entry = archive.getinfo("manifest.json")
    directory = struct.unpack_from("<L", raw, len(raw) - 6)[0]
    central = directory
    while True:
        names, extras, comments = struct.unpack_from("<3H", raw, central + 28)
        if raw[central + 46 : central + 46 + names] == b"manifest.json":
            break
        central += 46 + names + extras + comments
    if ending == "extra":
        raw[directory:directory] = b"x"
        delta = 1
    else:
        del raw[directory - 1 : directory]
        delta = -1
    struct.pack_into("<L", raw, entry.header_offset + 18, entry.compress_size + delta)
    struct.pack_into("<L", raw, central + delta + 20, entry.compress_size + delta)
    struct.pack_into("<L", raw, len(raw) - 6, directory + delta)
    path.write_bytes(raw)
    _refused(path, "invalid_archive")


def test_matching_false_crc_in_both_headers_is_not_accepted(tmp_path):
    path = _package(tmp_path)
    raw = bytearray(path.read_bytes())
    struct.pack_into("<L", raw, 14, 0)
    central = raw.index(b"PK\x01\x02")
    struct.pack_into("<L", raw, central + 16, 0)
    path.write_bytes(raw)
    _refused(path, "invalid_archive")


@pytest.mark.parametrize("local_only", [False, True])
def test_zip64_extra_fields_are_refused_even_with_ordinary_extract_version(
    tmp_path, local_only
):
    entry = zipfile.ZipInfo("rota.json")
    entry.extra = struct.pack("<2H2Q", 0xCAFE if local_only else 1, 16, 100, 100)
    entries = [
        (entry if name == "rota.json" else name, raw) for name, raw in CONTENT.items()
    ]
    path = _package(tmp_path, entries=entries)
    if local_only:
        raw = bytearray(path.read_bytes())
        struct.pack_into("<H", raw, 30 + len("rota.json"), 1)
        path.write_bytes(raw)
    _refused(path, "unsupported_member")


def test_complete_measured_contents_can_equal_the_unchanged_limit(tmp_path):
    content = {**CONTENT, "rota.html": b""}
    for _ in range(3):
        other = sum(len(raw) for name, raw in content.items() if name != "rota.html")
        manifest_size = len(json.dumps(_manifest(content)).encode())
        content["rota.html"] = b"x" * (16_777_216 - other - manifest_size)
    path = _package(tmp_path, content=content)
    summary = rota_integrity.verify_rota_package(path)
    assert summary.uncompressed_bytes == 16_777_216
