from typing import Annotated

from fastapi import Body, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator

from a_stock_lab.api.errors import register_exception_handlers


class ValidatedBody(BaseModel):
    value: int

    @field_validator("value")
    @classmethod
    def reject_value(cls, value: int) -> int:
        raise ValueError("value was rejected")


def test_validation_error_context_remains_a_structured_422_response() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/validated")
    def validated(_: Annotated[ValidatedBody, Body()]) -> None:
        return None

    with TestClient(app) as client:
        response = client.post("/validated", json={"value": 1})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"][0]["type"] == "value_error"
    assert response.json()["error"]["details"][0]["msg"] == "Value error, value was rejected"
