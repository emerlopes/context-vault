"""Standardized error codes and exit codes."""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    REVISION_CONFLICT = "REVISION_CONFLICT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    REPOSITORY_UNAVAILABLE = "REPOSITORY_UNAVAILABLE"
    INDEX_INCONSISTENT = "INDEX_INCONSISTENT"
    GIT_ERROR = "GIT_ERROR"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    LOCK_TIMEOUT = "LOCK_TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# Exit codes are stable and part of the public CLI contract.
EXIT_CODES: dict[ErrorCode, int] = {
    ErrorCode.NOT_FOUND: 3,
    ErrorCode.AMBIGUOUS_MATCH: 4,
    ErrorCode.VALIDATION_ERROR: 5,
    ErrorCode.REVISION_CONFLICT: 6,
    ErrorCode.PERMISSION_DENIED: 7,
    ErrorCode.REPOSITORY_UNAVAILABLE: 8,
    ErrorCode.INDEX_INCONSISTENT: 9,
    ErrorCode.GIT_ERROR: 10,
    ErrorCode.CONFIRMATION_REQUIRED: 11,
    ErrorCode.LOCK_TIMEOUT: 12,
    ErrorCode.INTERNAL_ERROR: 1,
}


class VaultError(Exception):
    """Base error carrying a standardized code and optional structured details."""

    code: ErrorCode = ErrorCode.INTERNAL_ERROR

    def __init__(self, message: str, *, code: ErrorCode | None = None, details: dict[str, Any] | None = None):
        super().__init__(message)
        if code is not None:
            self.code = code
        self.message = message
        self.details = details or {}

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.code]

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"code": self.code.value, "message": self.message}
        if self.details:
            data["details"] = self.details
        return data


class NotFoundError(VaultError):
    code = ErrorCode.NOT_FOUND


class AmbiguousMatchError(VaultError):
    code = ErrorCode.AMBIGUOUS_MATCH


class ValidationError(VaultError):
    code = ErrorCode.VALIDATION_ERROR


class RevisionConflictError(VaultError):
    code = ErrorCode.REVISION_CONFLICT


class PermissionDeniedError(VaultError):
    code = ErrorCode.PERMISSION_DENIED


class RepositoryUnavailableError(VaultError):
    code = ErrorCode.REPOSITORY_UNAVAILABLE


class IndexInconsistentError(VaultError):
    code = ErrorCode.INDEX_INCONSISTENT


class GitError(VaultError):
    code = ErrorCode.GIT_ERROR


class ConfirmationRequiredError(VaultError):
    code = ErrorCode.CONFIRMATION_REQUIRED


class LockTimeoutError(VaultError):
    code = ErrorCode.LOCK_TIMEOUT
