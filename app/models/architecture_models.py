"""Provider-neutral architecture document contracts for application seams."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArchitectureComponent(BaseModel):
    """A semantic component before renderer-specific compilation."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ref: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    catalog_ref: str = Field(alias="catalogRef", min_length=1, max_length=200)
    label: str | None = None
    description: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    group_ref: str | None = Field(default=None, alias="groupRef")


class ArchitectureConnection(BaseModel):
    """A semantic relationship between two architecture components."""

    model_config = ConfigDict(extra="forbid")

    ref: str | None = Field(default=None, min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=100)
    type: str = Field(default="dependency", min_length=1, max_length=80)
    label: str | None = None
    description: str | None = None
    protocol: str | None = None


class ArchitectureDocument(BaseModel):
    """Canonical renderer-independent representation of an architecture."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["1.0"] = Field(default="1.0", alias="schemaVersion")
    title: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)
    components: list[ArchitectureComponent] = Field(default_factory=list, max_length=100)
    connections: list[ArchitectureConnection] = Field(default_factory=list, max_length=200)
    groups: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    layers: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    idempotency_key: str | None = Field(
        default=None,
        alias="idempotencyKey",
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    reasoning_context: dict[str, Any] = Field(
        default_factory=dict,
        alias="reasoningContext",
    )

    @model_validator(mode="after")
    def validate_graph_references(self) -> "ArchitectureDocument":
        """Reject duplicate, dangling, and self-referencing graph links."""

        component_refs = [component.ref for component in self.components]
        if len(component_refs) != len(set(component_refs)):
            raise ValueError("Component refs must be unique")

        connection_refs = [connection.ref for connection in self.connections if connection.ref]
        if len(connection_refs) != len(set(connection_refs)):
            raise ValueError("Connection refs must be unique")

        known_refs = set(component_refs)
        for connection in self.connections:
            if connection.source not in known_refs:
                raise ValueError(f"Connection source does not exist: {connection.source}")
            if connection.target not in known_refs:
                raise ValueError(f"Connection target does not exist: {connection.target}")
            if connection.source == connection.target:
                raise ValueError(f"Self-connections are not supported: {connection.source}")

        return self
