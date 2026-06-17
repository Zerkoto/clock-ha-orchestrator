from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config_loader import load_room_registry  # noqa: E402
from app.dashboard.generator import generate_dashboard  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Home Assistant reception dashboard YAML."
    )
    parser.add_argument("--rooms", type=Path, default=Path("config/rooms.example.yaml"))
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("homeassistant/dashboards/hotel-reception.yaml"),
    )
    args = parser.parse_args()

    dashboard = generate_dashboard(load_room_registry(args.rooms))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(dashboard, handle, sort_keys=False, allow_unicode=False)


if __name__ == "__main__":
    main()
