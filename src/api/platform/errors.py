from pydantic import BaseModel


class ErrorResponse(BaseModel):
    code: str
    message: str


class InvalidRequest(ErrorResponse):
    fields: list[str]


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.body = ErrorResponse(code=code, message=message)
