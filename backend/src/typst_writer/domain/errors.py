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
