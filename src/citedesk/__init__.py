"""citedesk: an assistant that answers only from approved entries and cites each one."""

from importlib.metadata import version

from citedesk.assistant import Assistant, Reply
from citedesk.knowledge import Entry, Knowledge, KnowledgeError
from citedesk.model import Draft, Generation, Model, Turn, Usage

__all__ = [
    "Assistant",
    "Draft",
    "Entry",
    "Generation",
    "Knowledge",
    "KnowledgeError",
    "Model",
    "Reply",
    "Turn",
    "Usage",
    "__version__",
]

__version__ = version("citedesk")
