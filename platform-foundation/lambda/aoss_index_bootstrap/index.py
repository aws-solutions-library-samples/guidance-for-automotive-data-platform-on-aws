"""AOSS vector-index bootstrap Lambda.

Custom Resource handler (aws_cdk.custom_resources.Provider framework).
Creates / deletes the FAISS knn_vector index in an AOSS collection.
"""
import os
import time
import logging

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection, NotFoundError, RequestError, AuthorizationException
from requests_aws4auth import AWS4Auth

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _build_index_body(dimensions: int, space_type: str, engine: str) -> dict:
    return {
        "settings": {
            "index": {
                "knn": True,
                "knn.algo_param.ef_search": 512,
            }
        },
        "mappings": {
            "properties": {
                "vector": {
                    "type": "knn_vector",
                    "dimension": dimensions,
                    "method": {
                        "name": "hnsw",
                        "space_type": space_type,
                        "engine": engine,
                        "parameters": {"ef_construction": 512, "m": 16},
                    },
                },
                "text": {"type": "text"},
                "metadata": {"type": "text", "index": False},
            }
        },
    }


def _get_client(endpoint: str) -> OpenSearch:
    session = boto3.session.Session()
    credentials = session.get_credentials().get_frozen_credentials()
    region = session.region_name or os.environ.get("AWS_REGION", "us-east-1")
    auth = AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        region,
        "aoss",
        session_token=credentials.token,
    )
    host = endpoint.replace("https://", "").rstrip("/")
    return OpenSearch(
        hosts=[{"host": host, "port": 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
    )


def _create_index(client: OpenSearch, index_name: str, body: dict, request_id: str) -> None:
    for delay in [5, 10, 20, 40, 80, 160]:
        try:
            client.indices.create(index=index_name, body=body)
            logger.info("request_id=%s action=create_index index=%s status=201", request_id, index_name)
            return
        except RequestError as exc:
            if "resource_already_exists_exception" in str(exc).lower() or getattr(exc, "status_code", None) in (400, 409):
                logger.info("request_id=%s action=create_index index=%s status=already_exists", request_id, index_name)
                return
            raise
        except AuthorizationException:
            logger.warning("request_id=%s action=create_index index=%s status=403 retrying_in=%ss", request_id, index_name, delay)
            time.sleep(delay)
    # Final attempt — let exception propagate
    client.indices.create(index=index_name, body=body)
    logger.info("request_id=%s action=create_index index=%s status=201", request_id, index_name)


def _delete_index(client: OpenSearch, index_name: str, request_id: str) -> None:
    try:
        client.indices.delete(index=index_name)
        logger.info("request_id=%s action=delete_index index=%s status=200", request_id, index_name)
    except NotFoundError:
        logger.info("request_id=%s action=delete_index index=%s status=404_treated_as_success", request_id, index_name)


def handler(event, context):
    request_type = event["RequestType"]
    endpoint = os.environ["COLLECTION_ENDPOINT"]
    index_name = os.environ["INDEX_NAME"]
    dimensions = int(os.environ.get("INDEX_DIMENSIONS", "1024"))
    space_type = os.environ.get("INDEX_SPACE_TYPE", "l2")
    engine = os.environ.get("INDEX_ENGINE", "faiss")
    request_id = getattr(context, "aws_request_id", "local")

    logger.info("request_id=%s request_type=%s index=%s endpoint=%s", request_id, request_type, index_name, endpoint)

    client = _get_client(endpoint)

    if request_type in ("Create", "Update"):
        body = _build_index_body(dimensions, space_type, engine)
        _create_index(client, index_name, body, request_id)
    elif request_type == "Delete":
        _delete_index(client, index_name, request_id)

    return {
        "PhysicalResourceId": index_name,
        "Data": {
            "IndexName": index_name,
            "CollectionEndpoint": endpoint,
        },
    }
