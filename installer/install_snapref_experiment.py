"""Install only pinned SnapRef inference files into a standalone LAKIS.

Used by the 8.1.3.1 file-patch finisher and for manual non-commercial installs.
Training dependencies, example galleries and full runtimes are not used.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import stat
import tempfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener


SOURCE_REVISION = "1f7e606621052c11486c7aa5ccf6c2c12c2c5a3a"
WEIGHT_REVISION = "e6d6a21e4d56faae4454a1cc9bfd065d87358bf2"
WEIGHT_NAME = "snapref_v2a.safetensors"
WEIGHT_SIZE = 381_821_960
WEIGHT_SHA256 = "8a22fc28d060447544eda283b36efe2dcdbad7422cbc0b8d42828d55a8a61ab4"
UPDATE_SOURCE_VERSION = "8.1.3"
MAX_TEXT_BYTES = 256 * 1024
SOURCE_FILES = {
    "__init__.py": ("comfyui_nodes/snapref/__init__.py", "9d882434211262d35a02bb3902be538134afc4d9"),
    "simple.py": ("comfyui_nodes/snapref/simple.py", "4115eabe861013c6d60e727e32675d12aa60d325"),
    "web/snapref.js": ("comfyui_nodes/snapref/web/snapref.js", "dbd3a9925c3453746c02b1baa65e4ffcb58a68d9"),
    "LICENSE": ("LICENSE", "d645695673349e3947e8e5ae42332d0ac3164cd7"),
}
WEIGHT_NOTICES = {
    "WEIGHTS_LICENSE.md": ("LICENSE.md", "ee956174133d7c2cdcf220440c7726187eaf4b50e8e48ee32194353a22164d15"),
    "WEIGHTS_NOTICE.txt": ("NOTICE.txt", "da99e3cfcb5ca56f27246580052f2aa5c587f1ac2432e7bcb0233b1e08ad45b7"),
}
WEIGHT_URL = (
    "https://huggingface.co/0ppxnhximxr/snapref-v2a/resolve/"
    + WEIGHT_REVISION + "/" + WEIGHT_NAME
)
WEIGHT_LICENSE_URL = (
    "https://huggingface.co/0ppxnhximxr/snapref-v2a/blob/"
    + WEIGHT_REVISION + "/LICENSE.md"
)
WEIGHT_NOTICE_URL = (
    "https://huggingface.co/0ppxnhximxr/snapref-v2a/blob/"
    + WEIGHT_REVISION + "/NOTICE.txt"
)
TERMS_NOTICE = (
    "SnapRef inference code uses Apache-2.0. SnapRef v2a weights use the "
    "CircleStone Labs Non-Commercial License v1.2, with non-commercial and "
    "non-production restrictions. Output permissions are separate from model "
    "operation rights, and the base model's terms also apply. Separate downloads "
    "or this acknowledgement do not grant commercial/product-integration rights. "
    "Rights to the weights come directly from CircleStone Labs under its license. "
    "Review the exact publisher terms and attribution before downloading: "
    + WEIGHT_LICENSE_URL + " ; " + WEIGHT_NOTICE_URL
    + " . Then explicitly supply --acknowledge-snapref-terms to confirm that "
    "you reviewed and accept the applicable publisher terms."
)


def check_origin(source, url):
    target = urlsplit(url)
    host = target.hostname or ""
    allowed = host == source or (source == "huggingface.co" and host.endswith(".hf.co"))
    if (source not in {"raw.githubusercontent.com", "huggingface.co"} or not allowed
            or target.scheme != "https" or target.username is not None
            or target.password is not None or target.port not in (443, None)):
        raise ValueError("SnapRef download left its official HTTPS publisher")


def publisher_stream(url, timeout):
    source = urlsplit(url).hostname
    check_origin(source, url)

    class PublisherRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            check_origin(source, newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    return build_opener(PublisherRedirect()).open(url, timeout=timeout)


def check_install_path(path):
    for item in (*reversed(path.parents), path):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError("SnapRef installation path contains a filesystem link: " + str(item))


def read_small(url):
    with publisher_stream(url, timeout=45) as response:
        data = response.read(MAX_TEXT_BYTES + 1)
    if len(data) > MAX_TEXT_BYTES:
        raise ValueError("Pinned inference text file exceeded 256 KiB: " + url)
    return data


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inference_files(existing_node=None):
    files = {}
    for pins, base_url, git_blob in (
        (SOURCE_FILES, f"https://raw.githubusercontent.com/ArcAnima/SnapRef/{SOURCE_REVISION}/", True),
        (WEIGHT_NOTICES, f"https://huggingface.co/0ppxnhximxr/snapref-v2a/raw/{WEIGHT_REVISION}/", False),
    ):
        for target, (source, expected) in pins.items():
            if existing_node is None:
                data = read_small(base_url + source)
            else:
                local = existing_node / target
                check_install_path(local)
                data = None
                if local.is_file():
                    with local.open("rb") as stream:
                        data = stream.read(MAX_TEXT_BYTES + 1)
                if data is None or len(data) > MAX_TEXT_BYTES:
                    raise ValueError("Existing SnapRef package differs; it was not overwritten: " + str(local))

            if git_blob:
                blob = b"blob " + str(len(data)).encode("ascii") + b"\0" + data
                observed = hashlib.sha1(blob).hexdigest()
            else:
                observed = hashlib.sha256(data).hexdigest()
            if observed != expected:
                if existing_node is not None:
                    raise ValueError("Existing SnapRef package differs; it was not overwritten: " + str(local))
                raise ValueError("Pinned SnapRef " + ("source" if git_blob else "notice") + " mismatch: " + source)
            files[target] = data
    return files


def download_weight(target):
    size = 0
    observed = hashlib.sha256()
    with publisher_stream(WEIGHT_URL, timeout=90) as incoming, target.open("xb") as outgoing:
        while block := incoming.read(1024 * 1024):
            size += len(block)
            if size > WEIGHT_SIZE:
                raise ValueError("SnapRef weight exceeded its published size")
            outgoing.write(block)
            observed.update(block)
    if size != WEIGHT_SIZE or observed.hexdigest() != WEIGHT_SHA256:
        raise ValueError("SnapRef weight size/SHA-256 verification failed")


def install(install_root, *, acknowledge_terms=False):
    # Fail before path changes or network access, including already-installed
    # weights. This confirmation is not a separate commercial licence grant.
    if acknowledge_terms is not True:
        raise ValueError(TERMS_NOTICE)
    return _install_pinned(install_root)


def _install_pinned(install_root, *, from_update=False):
    supplied = Path(install_root).absolute()
    check_install_path(supplied)
    root = supplied.resolve(strict=True)
    if root == Path(root.anchor):
        raise ValueError("An explicit standalone LAKIS installation is required")
    for relative in ("ComfyUI/main.py", "python_embeded/python.exe"):
        path = root / relative
        check_install_path(path)
        if not path.is_file():
            raise ValueError("Target is not a standalone LAKIS installation")
    if from_update:
        version = root / "VERSION"
        check_install_path(version)
        if not version.is_file() or version.read_text(encoding="utf-8-sig").strip() != UPDATE_SOURCE_VERSION:
            raise ValueError("SnapRef update preparation requires a LAKIS 8.1.3 installation")
    node = root / "ComfyUI/custom_nodes/snapref"
    weight = root / "ComfyUI/models/loras" / WEIGHT_NAME
    check_install_path(node)
    check_install_path(weight)
    node_existing = node.exists()
    weight_existing = weight.exists()
    if weight_existing and (not weight.is_file() or weight.stat().st_size != WEIGHT_SIZE
                            or digest(weight) != WEIGHT_SHA256):
        raise ValueError("Existing SnapRef model differs; it was not overwritten: " + str(weight))
    if node_existing and not node.is_dir():
        raise ValueError("Existing SnapRef package differs; it was not overwritten: " + str(node))
    files = inference_files(node if node_existing else None)

    # Separate same-volume staging directories allow atomic publication without
    # holding another full model copy after completion. Only these new
    # TemporaryDirectory instances are removed, including on failure.
    with ExitStack() as work:
        if not node_existing:
            node.parent.mkdir(parents=True, exist_ok=True)
            code_tmp = work.enter_context(tempfile.TemporaryDirectory(prefix=".lakis-snapref-", dir=node.parent))
            package = Path(code_tmp) / "snapref"
            for name, data in files.items():
                target = package / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        if not weight_existing:
            weight.parent.mkdir(parents=True, exist_ok=True)
            model_tmp = work.enter_context(tempfile.TemporaryDirectory(prefix=".lakis-snapref-", dir=weight.parent))
            staged_weight = Path(model_tmp) / WEIGHT_NAME
            download_weight(staged_weight)
            # Recheck the exact destination rather than replace a concurrently
            # installed or user-provided file.
            check_install_path(weight)
            if weight.exists():
                raise FileExistsError("SnapRef model appeared during download; destination preserved")
            staged_weight.rename(weight)
        if not node_existing:
            check_install_path(node)
            if node.exists():
                raise FileExistsError("SnapRef package appeared during installation; destination preserved")
            package.rename(node)
    return {
        "install_root": str(root), "node": str(node), "model": str(weight),
        "model_bytes": WEIGHT_SIZE, "model_sha256": WEIGHT_SHA256,
        "source_revision": SOURCE_REVISION, "model_revision": WEIGHT_REVISION,
        "node_files": len(files), "temporary_workspaces_retained": 0,
        "runtime_or_model_copies": 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=TERMS_NOTICE, allow_abbrev=False)
    parser.add_argument("--install-root", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--acknowledge-snapref-terms", action="store_true",
        help="Confirm review and acceptance of the pinned publisher terms; not a commercial licence.",
    )
    # Internal mode for the normal update, which discloses the publisher terms
    # before acceptance. It is not a CLI terms acknowledgement or use consent.
    mode.add_argument("--provision-for-update", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not (args.acknowledge_snapref_terms or args.provision_for_update):
        parser.error(TERMS_NOTICE)
    try:
        if args.provision_for_update:
            result = _install_pinned(args.install_root, from_update=True)
        else:
            result = install(args.install_root, acknowledge_terms=args.acknowledge_snapref_terms)
    except (OSError, ValueError) as error:
        parser.exit(1, f"SnapRef preparation failed: {error}\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
