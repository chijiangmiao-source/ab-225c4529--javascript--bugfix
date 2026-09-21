"""FastAPI application: exact affine-lattice audit service."""

from __future__ import annotations

from typing import List

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictInt

from .solver import ValidationError, solve

app = FastAPI(
    title="Diffraction Lattice Audit",
    version="1.0.0",
    description=(
        "Finds the coarsest integer affine lattice consistent with "
        "integer-pixel diffraction spots using exact integer arithmetic."
    ),
)


class PointIn(BaseModel):
    id: str = Field(..., min_length=1, description="unique point identifier")
    # StrictInt: JSON numbers with a fractional part (e.g. 1.0) or booleans
    # must be rejected at the wire boundary instead of being silently coerced
    # to integers; the solver itself accepts only true Python ints.
    x: StrictInt
    y: StrictInt

    model_config = {"extra": "forbid"}


class AuditRequest(BaseModel):
    points: List[PointIn]
    min_cell_area: StrictInt = Field(..., ge=2, le=1_000_000)
    max_outliers: StrictInt = Field(..., ge=0, le=3)

    model_config = {"extra": "forbid"}


@app.exception_handler(ValidationError)
async def validation_error_handler(_request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "lattice-audit"}


@app.post("/api/audit")
def audit(req: AuditRequest) -> dict:
    payload = {
        "points": [p.model_dump() for p in req.points],
        "min_cell_area": req.min_cell_area,
        "max_outliers": req.max_outliers,
    }
    return solve(payload)
