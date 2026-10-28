#!/usr/bin/env python3
"""Decode a local LKS1G diagnostic packet."""

import argparse
import base64
import hashlib
import json
import math
import re
import sys
import zlib


MAX_RAW_BYTES = 4 * 1024 * 1024
MAX_COMPRESSED_BYTES = 1024 * 1024
MAX_BASE64URL_LENGTH = (
    (MAX_COMPRESSED_BYTES // 3) * 4
    + (0 if MAX_COMPRESSED_BYTES % 3 == 0 else MAX_COMPRESSED_BYTES % 3 + 1)
)


class DiagnosticPacketError(ValueError):
    """Raised when a diagnostic packet is malformed or invalid."""


def _extract_token(text):
    if not isinstance(text, str):
        raise DiagnosticPacketError("diagnostic input must be text")
    if len(text) > MAX_BASE64URL_LENGTH + 16384:
        raise DiagnosticPacketError("diagnostic input exceeds the text size limit")
    trimmed = text.strip()
    if trimmed.startswith("LKS") and not any(character.isspace() for character in trimmed):
        return trimmed
    candidates = [
        match.group(2).rstrip(".,;)]}")
        for match in re.finditer(r"(^|[^A-Za-z0-9_])(LKS[0-9]+[A-Za-z]+:[^\s]*)", text)
    ]
    if len(candidates) != 1:
        raise DiagnosticPacketError("expected exactly one diagnostic packet token")
    return candidates[0]


def _parse_token(token):
    header = token.split(":", 1)[0]
    if header.startswith("LKS") and header != "LKS1G":
        raise DiagnosticPacketError("unknown diagnostic packet version or codec")

    fields = token.split(":")
    if len(fields) != 4 or fields[0] != "LKS1G":
        raise DiagnosticPacketError("malformed diagnostic packet")
    length_text, expected_hash, encoded = fields[1:]
    if re.fullmatch(r"(0|[1-9][0-9]*)", length_text) is None:
        raise DiagnosticPacketError("malformed diagnostic packet length")
    if len(length_text) > len(str(MAX_RAW_BYTES)):
        raise DiagnosticPacketError("diagnostic packet exceeds the raw size limit")
    raw_length = int(length_text)
    if raw_length > MAX_RAW_BYTES:
        raise DiagnosticPacketError("diagnostic packet exceeds the raw size limit")
    if re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
        raise DiagnosticPacketError("malformed diagnostic packet hash")
    if (
        not encoded
        or len(encoded) > MAX_BASE64URL_LENGTH
        or re.fullmatch(r"[A-Za-z0-9_-]+", encoded) is None
        or len(encoded) % 4 == 1
    ):
        raise DiagnosticPacketError("malformed or oversized Base64url payload")

    padding = "=" * ((4 - len(encoded) % 4) % 4)
    try:
        compressed = base64.b64decode(
            (encoded + padding).encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, base64.binascii.Error) as error:
        raise DiagnosticPacketError("malformed Base64url payload") from error
    if (
        len(compressed) > MAX_COMPRESSED_BYTES
        or base64.urlsafe_b64encode(compressed).rstrip(b"=").decode("ascii") != encoded
    ):
        raise DiagnosticPacketError("noncanonical or oversized Base64url payload")
    return raw_length, expected_hash, compressed


def _decompress_gzip_bounded(compressed, declared_length):
    try:
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        output = bytearray()
        pending = compressed

        while True:
            max_output = declared_length - len(output) + 1
            chunk = decompressor.decompress(pending, max_output)
            output.extend(chunk)
            if len(output) > declared_length or len(output) > MAX_RAW_BYTES:
                raise DiagnosticPacketError(
                    "diagnostic packet exceeds its declared or raw size limit"
                )

            if decompressor.eof:
                if decompressor.unused_data:
                    raise DiagnosticPacketError(
                        "trailing or concatenated gzip data is not allowed"
                    )
                break

            next_pending = decompressor.unconsumed_tail
            if next_pending:
                if not chunk and next_pending == pending:
                    raise DiagnosticPacketError("invalid gzip data")
                pending = next_pending
                continue

            if chunk:
                pending = b""
                continue
            raise DiagnosticPacketError("truncated gzip data")

        return bytes(output)
    except DiagnosticPacketError:
        raise
    except zlib.error as error:
        raise DiagnosticPacketError("invalid or corrupt gzip data") from error


def _reject_json_constant(value):
    raise DiagnosticPacketError("invalid JSON constant")

def _finite_json_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise DiagnosticPacketError("invalid JSON number")
    return number


def decode_report(text):
    """Decode one diagnostic packet from a token or copied report text."""
    token = _extract_token(text)
    raw_length, expected_hash, compressed = _parse_token(token)
    if len(compressed) > MAX_COMPRESSED_BYTES:
        raise DiagnosticPacketError("diagnostic packet exceeds the compressed size limit")

    raw = _decompress_gzip_bounded(compressed, raw_length)
    if len(raw) != raw_length:
        raise DiagnosticPacketError("diagnostic packet length mismatch")
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise DiagnosticPacketError("diagnostic packet hash mismatch")

    try:
        json_text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise DiagnosticPacketError("diagnostic packet is not valid UTF-8") from error
    try:
        report = json.loads(json_text, parse_constant=_reject_json_constant,
                            parse_float=_finite_json_float)
    except (json.JSONDecodeError, DiagnosticPacketError, RecursionError) as error:
        raise DiagnosticPacketError("diagnostic packet does not contain valid JSON") from error

    if not isinstance(report, dict):
        raise DiagnosticPacketError("diagnostic report must be a JSON object")
    if type(report.get("report_schema")) is not int or report["report_schema"] != 1:
        raise DiagnosticPacketError("diagnostic report schema must be 1")
    if not isinstance(report.get("error_code"), str) or not report["error_code"]:
        raise DiagnosticPacketError("diagnostic report error_code must be a nonempty string")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", help="packet text file (default: stdin)")
    args = parser.parse_args(argv)

    try:
        if args.input:
            with open(args.input, "r", encoding="utf-8") as source:
                text = source.read(MAX_BASE64URL_LENGTH + 16385)
        else:
            text = sys.stdin.read(MAX_BASE64URL_LENGTH + 16385)
        report = decode_report(text)
    except (DiagnosticPacketError, OSError, UnicodeError) as error:
        print("error: " + str(error), file=sys.stderr)
        return 1

    output = json.dumps(report, ensure_ascii=False)
    sys.stdout.buffer.write(output.encode("utf-8", errors="backslashreplace") + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
