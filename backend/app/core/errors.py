class AppError(Exception):
    code = 50001
    http_status = 500

    def __init__(self, message: str = "服务内部错误") -> None:
        self.message = message
        super().__init__(message)


class BadRequest(AppError):
    code = 40001
    http_status = 400


class Unauthorized(AppError):
    code = 40101
    http_status = 401


class Forbidden(AppError):
    code = 40301
    http_status = 403


class NotFound(AppError):
    code = 40401
    http_status = 404


class Conflict(AppError):
    code = 40901
    http_status = 409


class TooManyRequests(AppError):
    code = 42901
    http_status = 429


class SandboxError(AppError):
    code = 50002
    http_status = 500
