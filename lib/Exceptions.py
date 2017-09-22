class ConfigurationInvalidException(Exception):
    pass


class ChecksumFailException(Exception):
    pass


class ManifestInvalidException(Exception):
    pass


class ManifestInvalidSignature(Exception):
    pass


class UpdateException(Exception):
    pass


class UpdateInsufficientSpace(UpdateException):
    """Raised when there is insufficient space to download
    a file or install into a new BE.
    Attributes:
      value -- a string containing the error message from the script
    """
    def __init__(self, value=""):
        self.value = value
    def __str__(self):
        return repr(self.value)
    
class UpdateInvalidUpdateException(UpdateException):
    """Raised when a package validation script fails.
    Attributes:
       value -- string containing the error message from the script
    """
    def __init__(self, value=""):
        self.value = value
    def __str__(self):
        return repr(self.value)

class UpdateIncompleteCacheException(UpdateException):
    pass


class UpdateInvalidCacheException(UpdateException):
    pass


class UpdateBusyCacheException(UpdateException):
    pass


class UpdatePackageNotFound(UpdateException):
    pass

class UpdateManifestNotFound(UpdateException):
    pass


class UpdateApplyException(UpdateException):
    pass


class InvalidBootEnvironmentNameException(UpdateException):
    pass

class UpdateBootEnvironmentException(UpdateException):
    pass


class UpdateSnapshotException(UpdateException):
    pass


class UpdatePackageException(UpdateException):
    pass
