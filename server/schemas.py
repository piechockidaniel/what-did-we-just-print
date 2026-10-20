from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator


def uid():
    return str(uuid4())


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False
    )


class Variant(StrictModel):
    id: str = Field(default_factory=uid, min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=250)
    destination: str = Field(min_length=1, max_length=250)
    quantity: int = Field(ge=1, le=1000000, strict=True)
    image: str = Field(max_length=14000000)
    side: Literal["front", "back"] = "front"
    # Legacy catalog fields are accepted, but decoded dimensions are authoritative.
    fileName: str | None = None
    mimeType: str | None = None
    pixelWidth: int | None = None
    pixelHeight: int | None = None
    status: str | None = None


class Order(StrictModel):
    id: str = Field(default_factory=uid, min_length=1, max_length=100)
    orderNumber: str = Field(min_length=1, max_length=100)
    customer: str = Field(min_length=1, max_length=150)
    widthMm: float = Field(ge=20, le=150)
    heightMm: float = Field(ge=20, le=150)
    createdAt: str | None = None
    variants: list[Variant] = Field(min_length=1, max_length=50)


class Catalog(StrictModel):
    schemaVersion: Literal[1]
    orders: list[Order] = Field(max_length=500)
    exportedAt: str | None = None
    imageEncoding: Literal["data-url"] = "data-url"


class Placement(StrictModel):
    variantId: str = Field(min_length=1, max_length=100)
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    rotation: Literal[0, 90, 180, 270] = 0
    side: Literal["front", "back"] = "front"
    artworkVersionId: str | None = Field(default=None, max_length=100)


class Sheet(StrictModel):
    number: str = Field(min_length=1, max_length=100)
    widthMm: float = Field(gt=0, le=3000)
    heightMm: float = Field(gt=0, le=3000)
    impressions: int = Field(ge=1, le=1000000, strict=True)
    placements: list[Placement] = Field(min_length=1, max_length=500)


class Mutation(StrictModel):
    key: str = Field(min_length=8, max_length=100)


class SheetUpdate(Sheet):
    key: str = Field(min_length=8, max_length=100)
    expectedRevision: int = Field(ge=1, strict=True)


class Release(Mutation):
    expectedRevision: int = Field(default=1, ge=1, strict=True)


class ArtworkUpdate(Mutation):
    image: str = Field(max_length=14000000)
    expectedRevision: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=500)


class Packing(Mutation):
    quantity: int = Field(ge=1, le=1000000, strict=True)
    revision: int = Field(ge=1, strict=True)
    scanId: str | None = None
    reason: str = Field(min_length=1, max_length=500)


class Reason(Mutation):
    reason: str = Field(min_length=1, max_length=500)


class Review(StrictModel):
    allocationId: str | None = None
    decision: Literal["confirm", "reject"]
    reason: str = Field(min_length=1, max_length=500)


class Scan(StrictModel):
    image: str = Field(max_length=14000000)
    sheetId: str | None = None
    stationId: str | None = None
    autoCrop: bool = False
    corners: list[list[float]] | None = None

    @field_validator("corners")
    @classmethod
    def validate_corners(cls, value):
        if value is not None and (len(value) != 4 or any(len(p) != 2 for p in value)):
            raise ValueError(
                "Provide four [x,y] corners: top-left, top-right, bottom-right, bottom-left"
            )
        return value


class Login(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=500)


class Station(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    maxWidthMm: float = Field(ge=20, le=3000)
    maxHeightMm: float = Field(ge=20, le=3000)
    notes: str = Field(max_length=1000, default="")
