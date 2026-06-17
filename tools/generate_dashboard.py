from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from app.config_loader import load_room_registry
from app.dashboard.generator import generate_dashboard


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
