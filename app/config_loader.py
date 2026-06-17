from pathlib import Path

import yaml
from pydantic import BaseModel

from app.domain.models import HotelPolicy, RoomRegistry


def load_yaml_model[ModelT: BaseModel](path: Path, model_type: type[ModelT]) -> ModelT:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return model_type.model_validate(data)


def load_room_registry(path: Path) -> RoomRegistry:
    return load_yaml_model(path, RoomRegistry)


def load_hotel_policy(path: Path) -> HotelPolicy:
    return load_yaml_model(path, HotelPolicy)
