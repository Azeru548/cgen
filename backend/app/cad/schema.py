"""Versioned CAD specification schema (Milestone 2: box only).

Contract boundary: Groq produces JSON -> this schema validates it ->
CadQuery builds geometry. Anything outside this schema is rejected.

Schema version: 1.0
Supported operations in v1.0: box only.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SPEC_VERSION = "1.0"

# Hard cap per dimension so the AI cannot request absurd geometry.
MAX_DIMENSION_MM = 10_000.0

MAX_NAME_LENGTH = 100


class BoxOperation(BaseModel):
    """A single rectangular block. All dimensions in millimeters."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["box"] = "box"
    width: float = Field(gt=0, le=MAX_DIMENSION_MM)
    depth: float = Field(gt=0, le=MAX_DIMENSION_MM)
    height: float = Field(gt=0, le=MAX_DIMENSION_MM)


class CADSpec(BaseModel):
    """Top-level validated CAD specification, schema v1.0."""

    model_config = ConfigDict(extra="forbid")

    document_type: Literal["3d_part"] = "3d_part"
    units: Literal["mm"] = "mm"
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    operation: BoxOperation

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned
