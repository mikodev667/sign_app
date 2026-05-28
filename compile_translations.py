from pathlib import Path
import polib


BASE_DIR = Path(__file__).resolve().parent

po_files = [
    BASE_DIR / "locale" / "ru" / "LC_MESSAGES" / "django.po",
    BASE_DIR / "locale" / "kk" / "LC_MESSAGES" / "django.po",
]

for po_path in po_files:
    if not po_path.exists():
        print(f"Not found: {po_path}")
        continue

    mo_path = po_path.with_suffix(".mo")

    po = polib.pofile(str(po_path))
    po.save_as_mofile(str(mo_path))

    print(f"Compiled: {mo_path}")