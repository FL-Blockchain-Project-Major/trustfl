#!/usr/bin/env python3
"""Authenticated envelope encryption for PostgreSQL backup archives.

The key file contains exactly one 256-bit key, encoded as 64 hexadecimal
characters or URL-safe base64.  A key identifier is metadata only; rotation is
performed by retaining the old key for old archives and selecting it during a
restore.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"TRUSTFL-AESGCM-v1\n"


def load_key(path: str) -> bytes:
    raw = Path(path).read_text(encoding="utf-8").strip()
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        try:
            key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except Exception as exc:
            raise ValueError("backup key must be hex or URL-safe base64") from exc
    if len(key) != 32:
        raise ValueError("backup key must contain exactly 32 bytes")
    return key


def encrypt(input_path: str, output_path: str, key_file: str, key_id: str) -> None:
    plaintext = Path(input_path).read_bytes()
    header = {"algorithm": "AES-256-GCM", "key_id": key_id, "version": 1}
    aad = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    nonce = os.urandom(12)
    ciphertext = AESGCM(load_key(key_file)).encrypt(nonce, plaintext, aad)
    Path(output_path).write_bytes(MAGIC + aad + b"\n" + nonce + ciphertext)


def decrypt(input_path: str, output_path: str, key_file: str) -> None:
    blob = Path(input_path).read_bytes()
    if not blob.startswith(MAGIC):
        raise ValueError("unsupported or unauthenticated backup envelope")
    rest = blob[len(MAGIC) :]
    aad, separator, encrypted = rest.partition(b"\n")
    if not separator or len(encrypted) < 12 + 16:
        raise ValueError("malformed backup envelope")
    header = json.loads(aad)
    if header.get("algorithm") != "AES-256-GCM" or header.get("version") != 1:
        raise ValueError("unexpected backup envelope metadata")
    plaintext = AESGCM(load_key(key_file)).decrypt(encrypted[:12], encrypted[12:], aad)
    Path(output_path).write_bytes(plaintext)


def inspect(input_path: str) -> None:
    blob = Path(input_path).read_bytes()
    if not blob.startswith(MAGIC):
        raise ValueError("unsupported or unauthenticated backup envelope")
    aad, separator, _ = blob[len(MAGIC) :].partition(b"\n")
    if not separator:
        raise ValueError("malformed backup envelope")
    print(json.dumps(json.loads(aad), sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("encrypt", "decrypt"):
        cmd = sub.add_parser(name)
        cmd.add_argument("input")
        cmd.add_argument("output")
        cmd.add_argument("--key-file", required=True)
        if name == "encrypt":
            cmd.add_argument("--key-id", required=True)
    inspect_cmd = sub.add_parser("inspect")
    inspect_cmd.add_argument("input")
    args = parser.parse_args()
    if args.command == "encrypt":
        encrypt(args.input, args.output, args.key_file, args.key_id)
    elif args.command == "decrypt":
        decrypt(args.input, args.output, args.key_file)
    else:
        inspect(args.input)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"backup crypto error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
