class AuthzUnavailable(Exception):
    """Authorization state is missing, down, or too old. Callers must fail closed."""


class RetrievalUnavailable(Exception):
    """Every configured retriever failed or timed out, so there is no evidence to answer from."""


class StateUnavailable(Exception):
    """The document-state store (the commit point) can't be read, so version visibility
    can't be verified. Callers must fail closed."""


class FileRejected(Exception):
    """An uploaded file can't be used. The message is safe to show to the person who uploaded it."""


    
        