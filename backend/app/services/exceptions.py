class DocumentNotFoundError(Exception):
    pass


class ChunkNotFoundError(Exception):
    pass


class ChangeNotFoundError(Exception):
    pass


class VersionConflictError(Exception):
    pass


class ChangeValidationError(Exception):
    pass


class ChangeConflictError(Exception):
    pass
