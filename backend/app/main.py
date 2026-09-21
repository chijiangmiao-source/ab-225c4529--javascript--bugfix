"""FastAPI application: exact affine-lattice audit service.

All request/response integers cross the HTTP boundary as tagged exact
integers (see :mod:`app.exact_json`), so values beyond the JavaScript
safe-integer range survive the browser's JSON parser without rounding.
The raw request body is decoded into arbitrary-precision Python ints
*before* validation and solving; pydantic/JSON-number coercion is never
in that path.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .exact_json import ExactJSONError, decode_exact_json, encode_exact_json
from .solver import ValidationError, solve

app = FastAPI(
    title="Diffraction Lattice Audit",
    version="1.0.0",
    description=(
        "Finds the coarsest integer affine lattice consistent with "
        "integer-pixel diffraction spots using exact integer arithmetic."
    ),
)


@app.exception_handler(ValidationError)
async def validation_error_handler(_request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(ExactJSONError)
async def exact_json_error_handler(_request: Request, exc: ExactJSONError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "lattice-audit"}


@app.post("/api/audit")
async def audit(request: Request) -> Response:
    payload = decode_exact_json(await request.body())
    if not isinstance(payload, dict):
        raise ExactJSONError("request body must be a JSON object")
    result = solve(payload)
    return Response(
        content=encode_exact_json(result),
        media_type="application/json",
    )
