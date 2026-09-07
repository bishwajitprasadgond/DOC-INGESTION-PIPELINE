class RagConfigurationError(Exception):
    """Raised when required Elasticsearch/embedding configuration is missing or invalid."""


class ElasticsearchConnectionError(Exception):
    """Raised when the Elasticsearch cluster is unreachable or rejects the connection."""
