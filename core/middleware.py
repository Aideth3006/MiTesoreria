class RequestAuditMiddleware:
    """Expose the originating request's basic audit metadata to form saves."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.audit_ip = self._client_ip(request)
        request.audit_device = request.META.get("HTTP_USER_AGENT", "")[:500]
        return self.get_response(request)

    @staticmethod
    def _client_ip(request):
        # Do not trust forwarded headers; deployment is bound to localhost in this phase.
        return request.META.get("REMOTE_ADDR") or None
