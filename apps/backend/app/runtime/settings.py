from dataclasses import dataclass


@dataclass
class RuntimeSettings:
    model: str
    personality: str = "default"
