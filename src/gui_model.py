"""GUI Model layer: data classes and constants."""
from dataclasses import dataclass, field
from typing import List

TARGET_OPTIONS = {
    "kvm": "target.kvm",
    "nutanix": "target.nutanix",
    "both": "target.both",
}

DEFAULT_EXTENSIONS = ".vmx,.ovf,.ova"


@dataclass
class ConversionState:
    running: bool = False
    total: int = 0
    current: int = 0
    success: int = 0
    errors: List[str] = field(default_factory=list)
