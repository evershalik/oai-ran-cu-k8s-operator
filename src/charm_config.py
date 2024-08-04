#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Config of the Charm."""

import dataclasses
import logging

import ops
from pydantic import (  # pylint: disable=no-name-in-module,import-error
    BaseModel,
    Field,
    StrictStr,
    ValidationError,
)

logger = logging.getLogger(__name__)


class CharmConfigInvalidError(Exception):
    """Exception raised when a charm configuration is found to be invalid."""

    def __init__(self, msg: str):
        """Initialize a new instance of the CharmConfigInvalidError exception.

        Args:
            msg (str): Explanation of the error.
        """
        self.msg = msg


def to_kebab(name: str) -> str:
    """Convert a snake_case string to kebab-case."""
    return name.replace("_", "-")


class CUConfig(BaseModel):  # pylint: disable=too-few-public-methods
    """Represent the OAI RAN CU operator builtin configuration values."""

    class Config:
        """Represent config for Pydantic model."""
        alias_generator = to_kebab
        use_enum_values = True

    f1_interface_name: StrictStr
    f1_port: int
    n2_interface_name: StrictStr
    n3_interface_name: StrictStr
    mcc: int = Field(ge=0, le=65535)
    mnc: int = Field(ge=0, le=65535)
    sst: int = Field(ge=1, le=4)
    tac: int


@dataclasses.dataclass
class CharmConfig:
    """Represents the state of the OAI RAN CU operator charm.

    Attributes:
        f1_interface_name: Name of the network interface used for F1 traffic
        f1_port: Number of the port used for F1 traffic
        n2_interface_name: Name of the network interface used for N2 traffic
        n3_interface_name: Name of the network interface used for N3 traffic
        mcc: Mobile Country Code
        mnc: Mobile Network code
        sst: Slice Service Type
        tac: Tracking Area Code
    """

    f1_interface_name: StrictStr
    f1_port: int
    n2_interface_name: StrictStr
    n3_interface_name: StrictStr
    mcc: int
    mnc: int
    sst: int
    tac: int

    def __init__(self, *, cu_config: CUConfig):
        """Initialize a new instance of the CharmConfig class.

        Args:
            cu_config: OAI RAN CU operator configuration.
        """
        self.f1_interface_name = cu_config.f1_interface_name
        self.f1_port = cu_config.f1_port
        self.n2_interface_name = cu_config.n2_interface_name
        self.n3_interface_name = cu_config.n3_interface_name
        self.mcc = cu_config.mcc
        self.mnc = cu_config.mnc
        self.sst = cu_config.sst
        self.tac = cu_config.tac

    @classmethod
    def from_charm(
        cls,
        charm: ops.CharmBase,
    ) -> "CharmConfig":
        """Initialize a new instance of the CharmState class from the associated charm."""
        try:
            # ignoring because mypy fails with:
            # "has incompatible type "**dict[str, str]"; expected ...""
            return cls(cu_config=CUConfig(**dict(charm.config.items())))  # type: ignore
        except ValidationError as exc:
            error_fields: list = []
            for error in exc.errors():
                if param := error["loc"]:
                    error_fields.extend(param)
                else:
                    value_error_msg: ValueError = error["ctx"]["error"]  # type: ignore
                    error_fields.extend(str(value_error_msg).split())
            error_fields.sort()
            error_field_str = ", ".join(f"'{f}'" for f in error_fields)
            raise CharmConfigInvalidError(
                f"The following configurations are not valid: [{error_field_str}]"
            ) from exc
