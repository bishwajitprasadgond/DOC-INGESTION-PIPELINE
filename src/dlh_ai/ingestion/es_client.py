"""
Elasticsearch client factory for the docs-ingestion pipeline.

This module is responsible for creating, configuring, and verifying
the Elasticsearch client used to push generated Q&A rows into a
vector-searchable index. All connection settings are sourced from
config.toml (or environment overrides), never hardcoded, so secrets
stay out of source control.
"""

import logging

from elasticsearch import Elasticsearch, ConnectionError as ESConnectionError, TransportError

from exceptions import ElasticsearchConnectionError, RagConfigurationError

LOGGER = logging.getLogger("docs_ingestion")

KEYWORD_FIELDS = {"Document-id", "Document-type", "Category", "Sub-category", "Serial-no"}


def build_es_client(
    host: str,
    api_key: str,
    request_timeout: int = 30,
    max_retries: int = 3,
    retry_on_timeout: bool = True,
    verify_certs: bool = True,
    connections_per_node: int = 10,
) -> Elasticsearch:
    """Create a configured Elasticsearch client instance.

    Parameters
    ----------
    host : str
        Elasticsearch cluster URL including scheme and port, e.g. ``"https://host:9201"``.
    api_key : str
        API key for authenticating with Elasticsearch. Never logged or printed.
    request_timeout : int, optional
        Per-request socket timeout in seconds. Default is 30.
    max_retries : int, optional
        Number of automatic retries on transient failures. Default is 3.
    retry_on_timeout : bool, optional
        Whether to retry the request if it times out. Default is True.
    verify_certs : bool, optional
        Whether to verify the TLS certificate. Default is True.
    connections_per_node : int, optional
        Size of the connection pool per Elasticsearch node. Default is 10.

    Returns
    -------
    Elasticsearch
        Ready-to-use Elasticsearch client instance.

    Raises
    ------
    RagConfigurationError
        Raised when ``host`` or ``api_key`` is empty or ``None``.
    ElasticsearchConnectionError
        Raised when the cluster health check fails after client creation.
    """
    if not host:
        raise RagConfigurationError(
            "Elasticsearch 'host' must not be empty. "
            "Set 'elasticsearch.host' in config.toml or 'ELASTICSEARCH__HOST' in the environment."
        )
    if not api_key:
        raise RagConfigurationError(
            "Elasticsearch 'api_key' must not be empty. "
            "Set 'elasticsearch.api_key' in config.toml or 'ELASTICSEARCH__API_KEY' in the environment."
        )

    LOGGER.info("Creating Elasticsearch client for host: %s", host)

    client = Elasticsearch(
        host,
        api_key=api_key,
        request_timeout=request_timeout,
        max_retries=max_retries,
        retry_on_timeout=retry_on_timeout,
        verify_certs=verify_certs,
        connections_per_node=connections_per_node,
    )

    _verify_connection(client, host)
    return client


def _verify_connection(client: Elasticsearch, host: str) -> None:
    """Verify the Elasticsearch connection by calling cluster info.

    Raises
    ------
    ElasticsearchConnectionError
        Raised when ``client.info()`` raises a connection or transport error.
    """
    try:
        info = client.info()
        cluster_name = info.get("cluster_name", "unknown")
        version = info.get("version", {}).get("number", "unknown")
        LOGGER.info("Elasticsearch connected, cluster: '%s', version: %s", cluster_name, version)
    except ESConnectionError as exc:
        raise ElasticsearchConnectionError(
            f"Cannot connect to Elasticsearch at '{host}'. Check network connectivity and cluster health."
        ) from exc
    except TransportError as exc:
        raise ElasticsearchConnectionError(
            f"Elasticsearch at '{host}' rejected the connection. Verify that the API key is valid and not expired."
        ) from exc


def _build_mapping(fields: list[str], embedding_dim: int) -> dict:
    properties = {}
    for name in fields:
        properties[name] = {"type": "keyword" if name in KEYWORD_FIELDS else "text"}
    properties["embedding"] = {"type": "dense_vector", "dims": embedding_dim}
    return {"mappings": {"properties": properties}}


def ensure_index(client: Elasticsearch, index_name: str, index_mode: str, fields: list[str], embedding_dim: int) -> None:
    """Create or verify the target index according to ``index_mode``.

    Parameters
    ----------
    index_mode : str
        ``"create"`` creates the index (with a mapping built from ``fields`` plus a
        ``dense_vector`` "embedding" field) only if it does not already exist; it never
        deletes or recreates an existing index. ``"append"`` requires the index to already
        exist and raises ``RagConfigurationError`` otherwise.

    Raises
    ------
    RagConfigurationError
        Raised for an unrecognized ``index_mode``, or when ``index_mode == "append"`` and
        the index does not exist.
    """
    if index_mode not in ("create", "append"):
        raise RagConfigurationError(f"Invalid elasticsearch.index_mode: {index_mode!r} (expected 'create' or 'append')")

    exists = client.indices.exists(index=index_name)

    if index_mode == "append":
        if not exists:
            raise RagConfigurationError(
                f"Elasticsearch index '{index_name}' does not exist, but index_mode is 'append'. "
                "Either create it out-of-band first, or set elasticsearch.index_mode = \"create\" in config.toml."
            )
        return

    if exists:
        LOGGER.info("Elasticsearch index '%s' already exists, appending to it", index_name)
        return

    LOGGER.info("Creating Elasticsearch index '%s'", index_name)
    client.indices.create(index=index_name, body=_build_mapping(fields, embedding_dim))
