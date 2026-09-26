#!/usr/bin/env python3
"""Copy the built HabitFlame pages from a habitflame-web checkout into this
GitHub Pages mirror, byte for byte, and record their hashes.

  python3 scripts/sync-mirror.py [PATH_TO_HABITFLAME_WEB]

The path defaults to ~/Code/habitflame-web. Build and verify the pages there
first (scripts/build-pages.py, scripts/verify-pages.py), then run this, then
run scripts/verify-pages.py --source PATH here. The mirror map lives in
scripts/verify-pages.py so the two scripts cannot disagree about it.
"""
import hashlib
import json
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERIFY = ROOT / "scripts" / "verify-pages.py"


def mirror_map() -> tuple[dict, str]:
    """MIRROR and CANONICAL_BASE from the verifier, without running its checks."""
    src = VERIFY.read_text(encoding="utf-8")
    head = src.split("MANIFEST = ", 1)[0]
    mod = types.ModuleType("verify_head")
    mod.__file__ = str(VERIFY)
    exec(compile(head, str(VERIFY), "exec"), mod.__dict__)
    return mod.MIRROR, mod.CANONICAL_BASE


def main() -> None:
    source = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path.home() / "Code" / "habitflame-web").resolve()
    mirror, base = mirror_map()
    files = {}
    for rel, (name, _url) in mirror.items():
        data = (source / name).read_bytes()
        dest = ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        files[rel] = {"source": name, "sha256": hashlib.sha256(data).hexdigest()}
        print(f"wrote {rel}")
    manifest = {"canonical_base": base, "files": files}
    (ROOT / "scripts" / "mirror.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("wrote scripts/mirror.json")


if __name__ == "__main__":
    main()
