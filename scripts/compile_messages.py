#!/usr/bin/env python
"""Compile every locale/*/LC_MESSAGES/django.po into django.mo (pure Python).

Django's own ``manage.py compilemessages`` needs the GNU gettext tools, which
are awkward to install on Windows. This script does the same job with only the
Python standard library:

    python scripts/compile_messages.py

Run it after editing a .po file. Entries marked "fuzzy" are skipped, exactly
like msgfmt does.
"""
import ast
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def parse_po(path):
    """Return {msgid: msgstr}; plurals use NUL-joined keys/values like .mo files."""
    messages = {}
    state = None
    msgid = msgid_plural = ""
    msgstrs = {}
    fuzzy = False
    pending_fuzzy = False

    def flush():
        nonlocal msgid, msgid_plural, msgstrs, fuzzy
        if state is None or fuzzy:
            msgid, msgid_plural, msgstrs, fuzzy = "", "", {}, False
            return
        if msgid_plural:
            key = msgid + "\0" + msgid_plural
            value = "\0".join(msgstrs[i] for i in sorted(msgstrs))
            if any(msgstrs.values()):
                messages[key] = value
        elif msgstrs.get(0) or msgid == "":
            messages[msgid] = msgstrs.get(0, "")
        msgid, msgid_plural, msgstrs, fuzzy = "", "", {}, False

    current = None
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if line.startswith("#,") and "fuzzy" in line:
                pending_fuzzy = True
            continue
        if line.startswith("msgid_plural"):
            current = "msgid_plural"
            msgid_plural = ast.literal_eval(line[len("msgid_plural"):].strip())
        elif line.startswith("msgid"):
            flush()
            state = "id"
            fuzzy, pending_fuzzy = pending_fuzzy, False
            current = "msgid"
            msgid = ast.literal_eval(line[len("msgid"):].strip())
        elif line.startswith("msgstr["):
            index = int(line[len("msgstr["):line.index("]")])
            current = index
            msgstrs[index] = ast.literal_eval(line[line.index("]") + 1:].strip())
        elif line.startswith("msgstr"):
            current = 0
            msgstrs[0] = ast.literal_eval(line[len("msgstr"):].strip())
        elif line.startswith('"'):
            text = ast.literal_eval(line)
            if current == "msgid":
                msgid += text
            elif current == "msgid_plural":
                msgid_plural += text
            elif isinstance(current, int):
                msgstrs[current] += text
        else:
            raise SystemExit(f"{path}:{number}: cannot parse line: {raw!r}")
    flush()
    return messages


def write_mo(messages, target):
    keys = sorted(messages)
    ids = b""
    strs = b""
    offsets = []
    for key in keys:
        encoded_key = key.encode("utf-8")
        encoded_value = messages[key].encode("utf-8")
        offsets.append((len(ids), len(encoded_key), len(strs), len(encoded_value)))
        ids += encoded_key + b"\0"
        strs += encoded_value + b"\0"
    count = len(keys)
    keystart = 7 * 4 + 16 * count
    valuestart = keystart + len(ids)
    key_index, value_index = [], []
    for id_offset, id_length, str_offset, str_length in offsets:
        key_index += [id_length, id_offset + keystart]
        value_index += [str_length, str_offset + valuestart]
    header = struct.pack(
        "Iiiiiii", 0x950412DE, 0, count, 7 * 4, 7 * 4 + count * 8, 0, 0
    )
    target.write_bytes(
        header + struct.pack(f"{len(key_index)}i", *key_index)
        + struct.pack(f"{len(value_index)}i", *value_index) + ids + strs
    )


def main():
    po_files = sorted(ROOT.glob("locale/*/LC_MESSAGES/django.po"))
    if not po_files:
        print("No .po files found under locale/.")
        return 1
    for po_file in po_files:
        messages = parse_po(po_file)
        mo_file = po_file.with_suffix(".mo")
        write_mo(messages, mo_file)
        print(f"Compiled {po_file.relative_to(ROOT)} -> {mo_file.name} ({len(messages) - 1} messages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
