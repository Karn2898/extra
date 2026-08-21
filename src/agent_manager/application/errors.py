"""Application-layer failures exposed by conversation use cases."""


class ConversationNotFound(Exception):
    """An operation targeted a conversation id that does not exist."""


class ConversationAccessDenied(Exception):
    """A caller acted on a conversation owned by a different user."""


class ConversationAlreadyExists(Exception):
    """A caller requested a conversation id already owned by someone else."""


class ConversationTokenBudgetExceeded(Exception):
    """A conversation's lifetime token budget is exhausted."""


class ConversationLinkRefused(Exception):
    """A visitor's conversations cannot be handed to the caller."""


class ConversationMessageNotFound(Exception):
    """An edit target is not on the conversation's active branch."""


class ConversationBranchConflict(Exception):
    """Another turn moved the branch head before an append completed."""
