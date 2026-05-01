class GithubReauthRequired(Exception):  # noqa: N818
    """Raised when a GitHub call returns 401 — the stored OAuth token is no longer valid.

    Named without an `Error` suffix because callers handle it as a control-flow
    signal ("user must re-auth"), not as a faulty-state exception.
    """
