from pathlib import Path


PO_FILES = [
    Path("locale/ru/LC_MESSAGES/django.po"),
    Path("locale/kk/LC_MESSAGES/django.po"),
]


def split_entries(text):
    entries = []
    current = []

    for line in text.splitlines(keepends=True):
        if line.startswith("msgid ") and current:
            entries.append("".join(current))
            current = [line]
        else:
            current.append(line)

    if current:
        entries.append("".join(current))

    return entries


def extract_msgid(entry):
    lines = entry.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("msgid "):
            value = line[len("msgid "):].strip()
            parts = [value]

            j = i + 1
            while j < len(lines) and lines[j].startswith('"'):
                parts.append(lines[j].strip())
                j += 1

            return "\n".join(parts)

    return None


def main():
    for po_path in PO_FILES:
        if not po_path.exists():
            print(f"Skip, not found: {po_path}")
            continue

        text = po_path.read_text(encoding="utf-8")
        entries = split_entries(text)

        header = []
        normal_entries = []

        for entry in entries:
            if 'msgid ""' in entry and 'Content-Type:' in entry:
                header.append(entry)
            else:
                normal_entries.append(entry)

        seen = set()
        cleaned = []

        for entry in normal_entries:
            msgid = extract_msgid(entry)

            if not msgid:
                cleaned.append(entry)
                continue

            if msgid in seen:
                continue

            seen.add(msgid)
            cleaned.append(entry)

        result = "".join(header + cleaned)

        backup_path = po_path.with_suffix(".po.bak")
        backup_path.write_text(text, encoding="utf-8")
        po_path.write_text(result, encoding="utf-8")

        print(f"Cleaned: {po_path}")
        print(f"Backup:  {backup_path}")
        print(f"Removed duplicates: {len(normal_entries) - len(cleaned)}")


if __name__ == "__main__":
    main()