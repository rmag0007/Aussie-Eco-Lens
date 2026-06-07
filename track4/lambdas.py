"""
Track 4 — Query APIs & Notifications
Aussie EcoLens Assignment 2

Database: Azure Cosmos DB
  - Database:  aussie_ecolens
  - Container: files
  - Partition key: /file_id

Environment variables (set in AWS Lambda console):
    COSMOS_ENDPOINT     — e.g. https://your-account.documents.azure.com:443/
    COSMOS_KEY          — your Cosmos DB primary key
    COSMOS_DB_NAME      — aussie_ecolens
    COSMOS_CONTAINER    — files
    SNS_TOPIC_PREFIX    — e.g. aussie-ecolens
    AWS_REGION          — e.g. ap-southeast-2
    MODEL_BUCKET        — S3 bucket name where ml_model.pt lives
    MODEL_KEY           — S3 key e.g. models/ml_model.pt
    CLASS_LABELS        — comma-separated e.g. kangaroo,wombat,koala,dingo,...

Install dependencies in your Lambda layer or requirements.txt:
    azure-cosmos
    torch
    torchvision
    opencv-python-headless
    Pillow
"""

import json
import os
import io
import logging
import subprocess
import sys
import boto3
from azure.cosmos import CosmosClient, exceptions as CosmosExceptions

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ─────────────────────────────────────────────────────────────
# Install torch at cold start if not available
# Only used by /query/file — all other endpoints skip this
# ─────────────────────────────────────────────────────────────

def ensure_torch():
    try:
        import torch
        logger.info("torch already available.")
        return
    except ImportError:
        pass
    logger.info("Installing torch + onnx2torch into /tmp/pypackages (cold start)...")
    # Step 1: install torch CPU (smallest version)
    subprocess.check_call([
        sys.executable, "-m", "pip", "install",
        "torch==2.2.0+cpu", "torchvision==0.17.0+cpu",
        "--target", "/tmp/pypackages",
        "--quiet", "--no-cache-dir",
        "--index-url", "https://download.pytorch.org/whl/cpu"
    ])
    # Remove only CUDA libs — Lambda runs on CPU only
    import glob
    cuda_patterns = [
        "/tmp/pypackages/torch/lib/libcudnn*",
        "/tmp/pypackages/torch/lib/libcublas*",
        "/tmp/pypackages/torch/lib/libcurand*",
        "/tmp/pypackages/torch/lib/libcufft*",
        "/tmp/pypackages/torch/lib/libcusolver*",
        "/tmp/pypackages/torch/lib/libcusparse*",
        "/tmp/pypackages/torch/lib/libnccl*",
        "/tmp/pypackages/torch/lib/libnvrtc*",
    ]
    for pattern in cuda_patterns:
        for path in glob.glob(pattern):
            try:
                os.remove(path)
                logger.info(f"Removed {path}")
            except:
                pass
    # Step 2: install onnx, onnx2torch, and compatible numpy
    subprocess.check_call([
        sys.executable, "-m", "pip", "install",
        "onnx", "onnx2torch", "numpy<2",
        "--target", "/tmp/pypackages",
        "--quiet", "--no-cache-dir",
        "--upgrade",
    ])
    # Put our packages FIRST so they override system numpy
    if "/tmp/pypackages" in sys.path:
        sys.path.remove("/tmp/pypackages")
    sys.path.insert(0, "/tmp/pypackages")
    logger.info("torch + onnx2torch installed successfully.")

# ─────────────────────────────────────────────────────────────
# Clients (initialised once per Lambda container — stays warm)
# ─────────────────────────────────────────────────────────────

sns_client = boto3.client("sns")

def get_cosmos_container():
    """Returns the Cosmos DB container client. Called lazily so cold start is faster."""
    client = CosmosClient(
        url=os.environ["COSMOS_ENDPOINT"],
        credential=os.environ["COSMOS_KEY"],
    )
    db = client.get_database_client(os.environ.get("COSMOS_DB_NAME", "aussie_ecolens"))
    return db.get_container_client(os.environ.get("COSMOS_CONTAINER", "files"))


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def ok(body, status=200):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps(body),
    }

def err(message, status=400):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps({"error": message}),
    }

def parse_body(event):
    try:
        return json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return None


# ─────────────────────────────────────────────────────────────
# DB LAYER — Cosmos DB
# ─────────────────────────────────────────────────────────────

def db_query_by_tags(tag_counts: dict) -> list:
    """
    Find all files where every requested tag meets the minimum count.
    Fetches all tagged files then filters in Python — works around
    Cosmos DB SQL limitations with dynamic keys in nested objects.
    """
    container = get_cosmos_container()

    # First get all tagged files that contain ALL the requested species
    # Use ARRAY_CONTAINS on tag_list for initial filtering (fast index scan)
    species_conditions = " AND ".join(
        [f"ARRAY_CONTAINS(c.tag_list, @tag{i})"
         for i, tag in enumerate(tag_counts.keys())]
    )
    query = f"SELECT * FROM c WHERE c.status = 'tagged' AND {species_conditions}"
    params = [{"name": f"@tag{i}", "value": tag}
              for i, tag in enumerate(tag_counts.keys())]

    logger.info(f"Cosmos query: {query} | params: {params}")
    items = list(container.query_items(
        query=query,
        parameters=params,
        enable_cross_partition_query=True
    ))

    # Then filter in Python for count requirements
    results = []
    for item in items:
        item_tags = item.get("tags", {})
        if all(item_tags.get(tag, 0) >= count for tag, count in tag_counts.items()):
            results.append(item)
    return results


def db_query_by_species(species_list: list) -> list:
    """
    Find all files containing all listed species (AND logic).
    Uses tag_list array field with parameterized queries.
    """
    container = get_cosmos_container()
    conditions = " AND ".join(
        [f"ARRAY_CONTAINS(c.tag_list, @sp{i})" for i, _ in enumerate(species_list)]
    )
    query = f"SELECT * FROM c WHERE c.status = 'tagged' AND {conditions}"
    params = [{"name": f"@sp{i}", "value": s} for i, s in enumerate(species_list)]
    items = list(container.query_items(
        query=query, parameters=params, enable_cross_partition_query=True
    ))
    return items


def db_get_by_thumbnail_url(thumbnail_url: str):
    """Look up a record by its thumbnail_url field, return s3_url."""
    container = get_cosmos_container()
    query = "SELECT c.s3_url, c.thumbnail_url, c.file_id, c.owner_sub, c.media_type FROM c WHERE c.thumbnail_url = @url"
    params = [{"name": "@url", "value": thumbnail_url}]
    items = list(container.query_items(query=query, parameters=params, enable_cross_partition_query=True))
    return items[0] if items else None


def db_update_tags(s3_url: str, tags: list, operation: int) -> bool:
    """
    Add (operation=1) or remove (operation=0) tags from a record.
    Keeps both 'tags' (dict with counts) and 'tag_list' (array) in sync.
    Partition key is owner_sub — must fetch full record first.
    Returns True if record found and updated.
    """
    container = get_cosmos_container()

    query = "SELECT * FROM c WHERE c.s3_url = @url"
    params = [{"name": "@url", "value": s3_url}]
    items = list(container.query_items(query=query, parameters=params, enable_cross_partition_query=True))

    if not items:
        return False

    record = items[0]
    current_tags = record.get("tags", {})
    current_tag_list = record.get("tag_list", [])

    if operation == 1:
        for tag in tags:
            current_tags[tag] = current_tags.get(tag, 0) + 1
            if tag not in current_tag_list:
                current_tag_list.append(tag)
    else:
        for tag in tags:
            if tag in current_tags:
                current_tags[tag] -= 1
                if current_tags[tag] <= 0:
                    del current_tags[tag]
                    if tag in current_tag_list:
                        current_tag_list.remove(tag)

    record["tags"] = current_tags
    record["tag_list"] = current_tag_list
    container.upsert_item(record)
    return True


def db_delete_record(s3_url: str) -> bool:
    """
    Delete the Cosmos DB record by s3_url.
    Partition key is owner_sub — must be passed to delete_item.
    Returns True if found and deleted.
    """
    container = get_cosmos_container()

    query = "SELECT c.id, c.file_id, c.owner_sub FROM c WHERE c.s3_url = @url"
    params = [{"name": "@url", "value": s3_url}]
    items = list(container.query_items(query=query, parameters=params, enable_cross_partition_query=True))

    if not items:
        return False

    record = items[0]
    container.delete_item(item=record["id"], partition_key=record["owner_sub"])
    return True


# ─────────────────────────────────────────────────────────────
# ML MODEL — PyTorch
# ─────────────────────────────────────────────────────────────

# ml_inference is imported lazily inside query_by_file only


# ─────────────────────────────────────────────────────────────
# SNS HELPERS
# ─────────────────────────────────────────────────────────────

def get_or_create_topic_arn(tag: str) -> str:
    prefix = os.environ.get("SNS_TOPIC_PREFIX", "aussie-ecolens")
    topic_name = f"{prefix}-{tag.lower().replace(' ', '-')}"
    response = sns_client.create_topic(Name=topic_name)
    return response["TopicArn"]


def publish_tag_notification(tags: list, file_url: str):
    """
    Call this whenever a new file is confirmed tagged.
    Notifies all SNS subscribers for each detected tag.
    Your teammate's tagging Lambda should call this, or you hook into their S3 event.
    """
    for tag in tags:
        try:
            topic_arn = get_or_create_topic_arn(tag)
            sns_client.publish(
                TopicArn=topic_arn,
                Subject=f"New {tag} sighting on Aussie EcoLens!",
                Message=(
                    f"A new file containing '{tag}' has been added to Aussie EcoLens.\n\n"
                    f"View it here: {file_url}\n\n"
                    f"You're receiving this because you subscribed to '{tag}' notifications."
                ),
            )
            logger.info(f"Notified subscribers for tag '{tag}'")
        except Exception as e:
            logger.error(f"SNS publish failed for tag '{tag}': {e}")


# ─────────────────────────────────────────────────────────────
# HANDLER 1 — POST /query/tags
# Find files by tag counts (logical AND)
# Supports both count queries {"kangaroo": 2} and species queries {"dingo": 1}
# ─────────────────────────────────────────────────────────────

def query_by_tags(event, context):
    body = parse_body(event)
    if body is None:
        return err("Invalid JSON body")
    if not body:
        return err("Request body must contain at least one tag")

    tag_counts = {}
    for tag, count in body.items():
        if not isinstance(count, int) or count < 1:
            return err(f"Count for '{tag}' must be a positive integer")
        tag_counts[tag] = count

    try:
        matches = db_query_by_tags(tag_counts)
    except Exception as e:
        logger.error(f"Cosmos error in query_by_tags: {e}")
        return err("Database error", 500)

    thumbnails = [r["thumbnail_url"] for r in matches if r.get("media_type") == "image" and r.get("thumbnail_url")]
    videos = [r["s3_url"] for r in matches if r.get("media_type") == "video"]

    return ok({"thumbnails": thumbnails, "videos": videos})


# ─────────────────────────────────────────────────────────────
# HANDLER 2 — GET /query/thumbnail
# Find full-size image URL from thumbnail URL
# ─────────────────────────────────────────────────────────────

def query_by_thumbnail(event, context):
    params = event.get("queryStringParameters") or {}
    thumbnail_url = params.get("thumbnail_url", "").strip()

    if not thumbnail_url:
        return err("Missing required query parameter: thumbnail_url")

    try:
        record = db_get_by_thumbnail_url(thumbnail_url)
    except Exception as e:
        logger.error(f"Cosmos error in query_by_thumbnail: {e}")
        return err("Database error", 500)

    if not record:
        return err("Thumbnail URL not found", 404)

    return ok({"full_url": record["s3_url"]})


# ─────────────────────────────────────────────────────────────
# HANDLER 3 — POST /query/file
# Find matching files by uploading a query file (transient — NOT stored)
# ─────────────────────────────────────────────────────────────

def query_by_file(event, context):
    import base64
    import sys
    ensure_torch()  # install torch if not present
    sys.path.insert(0, "/tmp/pypackages")  # make sure installed packages are on path
    from ml_inference import run_ml_model_on_file

    body = event.get("body", "")
    is_base64 = event.get("isBase64Encoded", False)

    if not body:
        return err("No file provided")

    try:
        raw_bytes = base64.b64decode(body) if is_base64 else body.encode()
    except Exception:
        return err("Could not decode request body")

    content_type = (event.get("headers") or {}).get("content-type", "")
    file_type = "video" if "video" in content_type else "image"

    try:
        detected_tags = run_ml_model_on_file(raw_bytes, file_type)
    except Exception as e:
        import traceback
        logger.error(f"ML model error: {e}")
        logger.error(traceback.format_exc())
        return err(f"Failed to process file with ML model: {str(e)}", 500)

    if not detected_tags:
        return ok({"detected_tags": [], "thumbnails": [], "videos": []})

    # Query DB for files with count >= 1 for each detected tag
    tag_counts = {tag: 1 for tag in detected_tags}

    try:
        matches = db_query_by_tags(tag_counts)
    except Exception as e:
        logger.error(f"Cosmos error in query_by_file: {e}")
        return err("Database error", 500)

    thumbnails = [r["thumbnail_url"] for r in matches if r.get("media_type") == "image" and r.get("thumbnail_url")]
    videos = [r["s3_url"] for r in matches if r.get("media_type") == "video"]

    return ok({
        "detected_tags": list(detected_tags.keys()),
        "thumbnails": thumbnails,
        "videos": videos,
    })


# ─────────────────────────────────────────────────────────────
# HANDLER 4 — POST /tags/bulk
# Add or remove tags from multiple files
# ─────────────────────────────────────────────────────────────

def bulk_tag_update(event, context):
    body = parse_body(event)
    if body is None:
        return err("Invalid JSON body")

    urls = body.get("urls")
    tags = body.get("tags")
    operation = body.get("operation")

    if not urls or not isinstance(urls, list):
        return err("'urls' must be a non-empty list")
    if not tags or not isinstance(tags, list):
        return err("'tags' must be a non-empty list")
    if operation not in (0, 1):
        return err("'operation' must be 0 (remove) or 1 (add)")

    updated = 0
    skipped = []

    for url in urls:
        try:
            found = db_update_tags(url, tags, operation)
            if found:
                updated += 1
            else:
                skipped.append(url)
        except Exception as e:
            logger.error(f"Cosmos error updating {url}: {e}")
            skipped.append(url)

    return ok({"updated": updated, "skipped": skipped})


# ─────────────────────────────────────────────────────────────
# HANDLER 5 — DELETE /files
# Delete DB records (your side — teammate handles S3 deletion)
# ─────────────────────────────────────────────────────────────

def delete_files(event, context):
    body = parse_body(event)
    if body is None:
        return err("Invalid JSON body")

    urls = body.get("urls")
    if not urls or not isinstance(urls, list):
        return err("'urls' must be a non-empty list")

    deleted = 0
    not_found = []

    for url in urls:
        try:
            found = db_delete_record(url)
            if found:
                deleted += 1
            else:
                not_found.append(url)
        except Exception as e:
            logger.error(f"Cosmos error deleting {url}: {e}")
            not_found.append(url)

    return ok({"deleted": deleted, "not_found": not_found})


# ─────────────────────────────────────────────────────────────
# HANDLER 6a — POST /notifications/subscribe
# ─────────────────────────────────────────────────────────────

def subscribe_to_tag(event, context):
    body = parse_body(event)
    if body is None:
        return err("Invalid JSON body")

    email = body.get("email", "").strip()
    tag = body.get("tag", "").strip()

    if not email or "@" not in email:
        return err("'email' must be a valid email address")
    if not tag:
        return err("'tag' must be a non-empty string")

    try:
        topic_arn = get_or_create_topic_arn(tag)
        response = sns_client.subscribe(
            TopicArn=topic_arn,
            Protocol="email",
            Endpoint=email,
            ReturnSubscriptionArn=True,
        )
        subscription_arn = response.get("SubscriptionArn", "pending confirmation")
    except Exception as e:
        logger.error(f"SNS subscribe error: {e}")
        return err("Failed to create subscription", 500)

    return ok({
        "message": f"Confirmation email sent to {email} for tag: {tag}",
        "subscription_arn": subscription_arn,
    })


# ─────────────────────────────────────────────────────────────
# HANDLER 6b — POST /notifications/unsubscribe
# ─────────────────────────────────────────────────────────────

def unsubscribe_from_tag(event, context):
    body = parse_body(event)
    if body is None:
        return err("Invalid JSON body")

    email = body.get("email", "").strip()
    tag = body.get("tag", "").strip()

    if not email or "@" not in email:
        return err("'email' must be a valid email address")
    if not tag:
        return err("'tag' must be a non-empty string")

    try:
        topic_arn = get_or_create_topic_arn(tag)
        paginator = sns_client.get_paginator("list_subscriptions_by_topic")
        subscription_arn = None

        for page in paginator.paginate(TopicArn=topic_arn):
            for sub in page["Subscriptions"]:
                if sub["Endpoint"] == email and sub["Protocol"] == "email":
                    subscription_arn = sub["SubscriptionArn"]
                    break
            if subscription_arn:
                break

        if not subscription_arn or subscription_arn == "PendingConfirmation":
            return err(f"No active subscription found for {email} on tag '{tag}'", 404)

        sns_client.unsubscribe(SubscriptionArn=subscription_arn)

    except Exception as e:
        logger.error(f"SNS unsubscribe error: {e}")
        return err("Failed to unsubscribe", 500)

    return ok({"message": f"{email} unsubscribed from tag: {tag}"})


# ─────────────────────────────────────────────────────────────
# ROUTER — single Lambda entry point
# ─────────────────────────────────────────────────────────────

ROUTES = {
    ("POST",   "/query/tags"):                query_by_tags,
    ("GET",    "/query/thumbnail"):           query_by_thumbnail,
    ("POST",   "/query/file"):                query_by_file,
    ("POST",   "/tags/bulk"):                 bulk_tag_update,
    ("DELETE", "/files"):                     delete_files,
    ("POST",   "/notifications/subscribe"):   subscribe_to_tag,
    ("POST",   "/notifications/unsubscribe"): unsubscribe_from_tag,
}

def handler(event, context):
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    route = ROUTES.get((method, path))
    if route is None:
        return err(f"No route for {method} {path}", 404)
    return route(event, context)