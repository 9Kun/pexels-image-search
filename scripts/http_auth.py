"""Keep explicit Pexels authentication isolated from ambient netrc secrets."""

from requests.auth import AuthBase


class NoNetrcAuth(AuthBase):
    """Preserve supplied headers without adding credentials from .netrc.

    An explicit auth handler suppresses Requests' implicit netrc lookup while
    retaining environment proxy and certificate settings.
    """

    def __call__(self, request):
        return request
