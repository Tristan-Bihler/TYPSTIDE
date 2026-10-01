"""Core data model shared by services, adapters and the API."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Severity = Literal["error", "warning", "grammar", "ai"]


class Problem(BaseModel):
    file: str  # workspace-relative POSIX path; "" if the problem has no location in the workspace
    line: int  # 1-based; 0 if unknown
    column: int  # 1-based; 0 if unknown
    severity: Severity
    message: str
    source: str  # e.g. "typst", "ltex"


class CompileResult(BaseModel):
    ok: bool
    pages: list[str]  # one SVG document per page; empty if compilation failed
    problems: list[Problem]
    duration_ms: float


SnippetKind = Literal["wrap", "line_prefix", "block", "dialog"]
DialogKind = Literal["table", "figure", "equation", "reference", "bibliography", "chart"]


class Snippet(BaseModel):
    """One insert-toolbar entry, defined in snippets.toml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    label: str = Field(min_length=1)
    group: str = Field(min_length=1)
    kind: SnippetKind
    template: str = ""
    placeholder: str = ""
    dialog: DialogKind | None = None
    shortcut: str | None = None
    title: str = ""
    in_toolbar: bool = True
    required_packages: list[str] = []

    @model_validator(mode="after")
    def _consistent(self) -> "Snippet":
        if (self.kind == "dialog") != (self.dialog is not None):
            raise ValueError(f"{self.id}: 'dialog' is required exactly for kind = 'dialog'")
        if self.kind != "dialog" and not self.template:
            raise ValueError(f"{self.id}: kind '{self.kind}' needs a template")
        if self.kind == "wrap" and "{selection}" not in self.template:
            raise ValueError(f"{self.id}: wrap templates must contain {{selection}}")
        return self


# --- AI -----------------------------------------------------------------------------

SuggestionSource = Literal["rule", "local_ai", "claude"]
ReviewMode = Literal["check", "improve", "shorten", "explain"]
Language = Literal["de-DE", "en-US"]


class Suggestion(BaseModel):
    """A proposed replacement. `start`/`end` are UTF-16 offsets in the document, the unit
    the browser editor (CodeMirror) uses."""

    id: str
    source: SuggestionSource
    start: int
    end: int
    original: str
    replacement: str
    reason: str
    category: str
    fixes: list[str] = []  # rule checks: every offered replacement (first = `replacement`)
    rule: str = ""  # rule checks: the LanguageTool rule id


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selection: str = Field(min_length=1)
    selection_start: int = Field(default=0, ge=0)  # UTF-16 offset of the selection in the document
    context_before: str = ""
    context_after: str = ""
    glossary: list[str] = []
    mode: ReviewMode
    language: Language = "de-DE"


class ReviewResult(BaseModel):
    revised_text: str
    explanation: str = ""
    changes: list[Suggestion]
    dropped: int = 0  # proposed changes removed because they were unsafe or not locatable


class AISettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_model: str | None = None
    claude_model: str | None = None


# --- Look and editor behaviour --------------------------------------------------------

Theme = Literal["system", "light", "dark"]


class UiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: Theme = "system"
    autosave: bool = True
    autosave_delay_ms: int = Field(default=2000, ge=500, le=60_000)
    preview_follows_cursor: bool = True
    planner_enabled: bool = False  # the optional Planner extension


# --- Spelling and grammar (rule checks) ----------------------------------------------

MAX_DICTIONARY_WORDS = 5000


class GrammarSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language = "de-DE"
    # Before Phase 6 one list for all projects; moved into the next opened project.
    dictionary: dict[Language, list[str]] = {}
    # Words accepted by the spell check, per project folder (absolute path) and language.
    dictionaries: dict[str, dict[Language, list[str]]] = {}


class GrammarView(BaseModel):
    """What the UI sees: the language and the open project's word list."""

    language: Language
    dictionary: dict[Language, list[str]]


DictionaryWord = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[^\s\x00-\x1f]+$")]


# --- Autocomplete (Tinymist) ---------------------------------------------------------

MAX_COMPLETION_ITEMS = 200


class CompletionItem(BaseModel):
    """One completion, ready for the editor. `insert` is plain text, or an LSP snippet
    (`${1:name}` fields) when `snippet` is true; it replaces [start, end) (UTF-16)."""

    label: str
    detail: str = ""
    kind: str  # editor icon: function, variable, constant, keyword, type, module, label, ...
    insert: str
    snippet: bool = False
    start: int
    end: int


class CompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    content: str = Field(max_length=2_000_000)
    offset: int = Field(ge=0)  # UTF-16 offset of the cursor
