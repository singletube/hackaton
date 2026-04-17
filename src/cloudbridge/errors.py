class CloudBridgeError(RuntimeError):
    pass


class ProviderError(CloudBridgeError):
    pass


class ProviderAuthenticationError(ProviderError):
    pass


class ResourceMissingError(ProviderError):
    pass


class ConflictError(ProviderError):
    pass
