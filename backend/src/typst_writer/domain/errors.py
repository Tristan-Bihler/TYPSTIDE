"""Domain errors. The API layer maps each to an HTTP status code."""


class WorkspaceError(Exception):
    """Base class for all expected, user-facing workspace errors."""


class NoWorkspaceError(WorkspaceError):
    def __init__(self) -> None:
        super().__init__("No folder is open. Open a folder first.")


class PathOutsideWorkspaceError(WorkspaceError):
    def __init__(self, path: str) -> None:
        super().__init__(f"'{path}' is outside the open folder.")


class EntryNotFoundError(WorkspaceError):
    def __init__(self, path: str) -> None:
        super().__init__(f"'{path}' does not exist.")


class EntryExistsError(WorkspaceError):
    def __init__(self, path: str) -> None:
        super().__init__(f"'{path}' already exists.")


class InvalidNameError(WorkspaceError):
    pass


class NotATextFileError(WorkspaceError):
    pass


class NoMainFileError(WorkspaceError):
    def __init__(self) -> None:
        super().__init__("No main file. Right-click a .typ file and choose 'Set as main file'.")


class UnknownSnippetError(WorkspaceError):
    def __init__(self, snippet_id: str) -> None:
        super().__init__(f"There is no snippet '{snippet_id}'.")


class InvalidSnippetParamsError(WorkspaceError):
    pass


class AIUnavailableError(WorkspaceError):
    """No usable AI for this action (slot is None, command missing, not logged in)."""


class AIFailedError(WorkspaceError):
    """The AI was called but did not return a usable answer."""


class TextTooLongError(WorkspaceError):
    pass


class CheckerUnavailableError(WorkspaceError):
    """Spelling and grammar checks cannot run (LTeX+ not installed, failed to start)."""
