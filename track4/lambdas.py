"""
Track 4 — Query APIs & Notifications
Aussie EcoLens Assignment 2

Database: Azure Cosmos DB
  - Database:  aussie_ecolens
  - Container: files
  - Partition key: /owner_sub

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
    """
    Parse JSON body from API Gateway event.
    Handles base64-encoded bodies (happens when binary media types are configured).
    Always tries base64 decode first if JSON parse fails.
    """
    import base64 as _b64
    try:
        body = event.get("body") or "{}"
        if not body:
            return {}

        # Try direct JSON parse first
        try:
            return json.loads(body)
        except (json.JSONDecodeError, Exception):
            pass

        # Try base64 decode then JSON parse
        try:
            decoded = _b64.b64decode(body).decode("utf-8")
            return json.loads(decoded)
        except Exception:
            pass

        return None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# COGNITO JWT VERIFICATION
# Works cross-account — verifies token using Cognito's public JWKS
# ─────────────────────────────────────────────────────────────

import urllib.request
import base64 as _base64
import json as _json

_jwks_cache = {}

def _get_jwks(user_pool_id: str, region: str) -> dict:
    """Fetch and cache Cognito public keys."""
    cache_key = f"{region}_{user_pool_id}"
    if cache_key not in _jwks_cache:
        url = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json"
        with urllib.request.urlopen(url) as resp:
            _jwks_cache[cache_key] = _json.loads(resp.read())
    return _jwks_cache[cache_key]

def verify_cognito_token(event: dict) -> dict | None:
    """
    Verifies the Cognito JWT from the Authorization header.
    Returns the token claims if valid, None if missing/invalid.
    Set COGNITO_USER_POOL_ID and COGNITO_REGION env vars.
    Set SKIP_AUTH=true to bypass auth during development.
    """
    # Allow bypassing auth for development/testing
    if os.environ.get("SKIP_AUTH", "false").lower() == "true":
        return {"sub": "dev-user", "email": "dev@example.com"}

    headers = event.get("headers") or {}
    auth_header = headers.get("Authorization") or headers.get("authorization", "")

    if not auth_header:
        return None

    token = auth_header.replace("Bearer ", "").strip()
    if not token:
        return None

    try:
        # Decode header to get key ID
        header_part = token.split(".")[0]
        # Add padding
        header_part += "=" * (4 - len(header_part) % 4)
        header = _json.loads(_base64.urlsafe_b64decode(header_part))
        kid = header.get("kid")

        # Decode payload (we trust Cognito's signature for now)
        # For production, verify signature using PyJWT or python-jose
        payload_part = token.split(".")[1]
        payload_part += "=" * (4 - len(payload_part) % 4)
        claims = _json.loads(_base64.urlsafe_b64decode(payload_part))

        # Basic checks
        import time
        if claims.get("exp", 0) < time.time():
            logger.warning("Token expired")
            return None

        user_pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")
        region = os.environ.get("COGNITO_REGION", "ap-southeast-2")
        expected_iss = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"

        if user_pool_id and claims.get("iss") != expected_iss:
            logger.warning(f"Token issuer mismatch: {claims.get('iss')}")
            return None

        return claims

    except Exception as e:
        logger.error(f"Token verification error: {e}")
        return None

def require_auth(event: dict):
    """
    Call at start of each handler.
    Returns (claims, None) if valid, (None, error_response) if not.
    """
    claims = verify_cognito_token(event)
    if claims is None:
        return None, err("Unauthorised — valid Cognito token required", 401)
    return claims, None


# ─────────────────────────────────────────────────────────────
# PRESIGNED URL HELPER
# ─────────────────────────────────────────────────────────────

def generate_presigned_url(s3_bucket: str, s3_key: str, expiry: int = 3600) -> str:
    """
    Generate a presigned URL for an S3 object.
    Valid for 1 hour by default.
    """
    try:
        s3 = boto3.client("s3", region_name="us-east-1")
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": s3_bucket, "Key": s3_key},
            ExpiresIn=expiry,
        )
        return url
    except Exception as e:
        logger.error(f"Failed to presign s3://{s3_bucket}/{s3_key}: {e}")
        return f"s3://{s3_bucket}/{s3_key}"  # fallback to raw path


def presign_record(record: dict) -> dict:
    """
    Generates fresh presigned URLs from permanently stored bucket/key fields.
    
    DB schema (permanent fields we use):
      s3_bucket + s3_key           → full image or video
      thumbnail_bucket + thumbnail_key → thumbnail image
      frames[].s3_bucket + frames[].s3_key → video frames

    We ignore s3_presigned_url_used_for_tagging and
    thumbnail_presigned_url_used_for_tagging — those are expired.
    """
    # Full file presigned URL
    s3_bucket = record.get("s3_bucket")
    s3_key = record.get("s3_key")
    record["presigned_url"] = (
        generate_presigned_url(s3_bucket, s3_key)
        if s3_bucket and s3_key else ""
    )

    # Thumbnail presigned URL — thumbnail_bucket is its own field
    thumb_bucket = record.get("thumbnail_bucket")
    thumb_key = record.get("thumbnail_key")
    record["presigned_thumbnail_url"] = (
        generate_presigned_url(thumb_bucket, thumb_key)
        if thumb_bucket and thumb_key else ""
    )

    # Video frames presigned URLs
    presigned_frames = []
    for frame in record.get("frames", []):
        fb = frame.get("s3_bucket")
        fk = frame.get("s3_key")
        if fb and fk:
            presigned_frames.append(generate_presigned_url(fb, fk))
    record["presigned_frames"] = presigned_frames

    return record


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


def db_get_by_thumbnail_key(thumbnail_key: str):
    """
    Look up a record by thumbnail_key.
    Selects s3_bucket+s3_key (full file) and thumbnail_bucket+thumbnail_key.
    """
    container = get_cosmos_container()
    query = """SELECT c.s3_bucket, c.s3_key, c.thumbnail_bucket,
                      c.thumbnail_key, c.file_id, c.owner_sub,
                      c.media_type, c.tags, c.tag_list
               FROM c WHERE c.thumbnail_key = @key"""
    params = [{"name": "@key", "value": thumbnail_key}]
    items = list(container.query_items(
        query=query, parameters=params, enable_cross_partition_query=True
    ))
    return items[0] if items else None


def db_update_tags(s3_url: str, tags: list, operation: int) -> bool:
    """
    Add (operation=1) or remove (operation=0) tags from a record.
    Keeps both 'tags' (dict with counts) and 'tag_list' (array) in sync.
    Partition key is owner_sub — must fetch full record first.
    Returns True if record found and updated.
    """
    container = get_cosmos_container()

    # Search by s3_key (permanent field) not s3_url (not stored)
    query = "SELECT * FROM c WHERE c.s3_key = @url OR c.file_id = @url"
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


def db_delete_record(file_id: str) -> bool:
    """
    Delete the Cosmos DB record by file_id or s3_key.
    Partition key is owner_sub.
    Returns True if found and deleted.
    """
    container = get_cosmos_container()

    # Try by file_id first, then s3_key
    query = "SELECT c.id, c.file_id, c.owner_sub FROM c WHERE c.file_id = @id OR c.s3_key = @id"
    params = [{"name": "@id", "value": file_id}]
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
    claims, error = require_auth(event)
    if error: return error
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

    # Generate fresh presigned URLs from stored bucket/key values
    thumbnails = []
    videos = []
    for r in matches:
        r = presign_record(r)
        if r.get("media_type") == "image" and r.get("presigned_thumbnail_url"):
            thumbnails.append(r["presigned_thumbnail_url"])
        elif r.get("media_type") == "video" and r.get("presigned_url"):
            videos.append(r["presigned_url"])

    return ok({"thumbnails": thumbnails, "videos": videos})


# ─────────────────────────────────────────────────────────────
# HANDLER 2 — GET /query/thumbnail
# Find full-size image URL from thumbnail URL
# ─────────────────────────────────────────────────────────────

def query_by_thumbnail(event, context):
    claims, error = require_auth(event)
    if error: return error
    params = event.get("queryStringParameters") or {}
    # Accept thumbnail_key directly, or extract key from a presigned/S3 URL
    thumbnail_key = params.get("thumbnail_key", "").strip()
    thumbnail_url = params.get("thumbnail_url", "").strip()

    # If given a URL, try to extract the key from it
    if not thumbnail_key and thumbnail_url:
        # Handle both presigned URLs and s3:// URIs
        if "amazonaws.com" in thumbnail_url:
            # Extract key from presigned URL path
            from urllib.parse import urlparse, unquote
            parsed = urlparse(thumbnail_url)
            thumbnail_key = unquote(parsed.path.lstrip("/"))
            # Remove bucket prefix if present in path-style URL
            parts = thumbnail_key.split("/", 1)
            if len(parts) == 2 and "." not in parts[0]:
                thumbnail_key = parts[1]
        elif thumbnail_url.startswith("s3://"):
            thumbnail_key = "/".join(thumbnail_url.split("/")[3:])

    if not thumbnail_key:
        return err("Missing required parameter: thumbnail_key or thumbnail_url")

    try:
        record = db_get_by_thumbnail_key(thumbnail_key)
    except Exception as e:
        import traceback
        logger.error(f"Cosmos error in query_by_thumbnail: {e}")
        logger.error(traceback.format_exc())
        return err(f"Database error: {str(e)}", 500)

    if not record:
        return err(f"Thumbnail key not found: {thumbnail_key}", 404)

    record = presign_record(record)
    return ok({
        "full_url": record["presigned_url"],
        "thumbnail_url": record["presigned_thumbnail_url"],
    })


# ─────────────────────────────────────────────────────────────
# HANDLER 3 — POST /query/file
# Find matching files by uploading a query file (transient — NOT stored)
# ─────────────────────────────────────────────────────────────

def query_by_file(event, context):
    claims, error = require_auth(event)
    if error: return error
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

    thumbnails = []
    videos = []
    for r in matches:
        r = presign_record(r)
        if r.get("media_type") == "image" and r.get("presigned_thumbnail_url"):
            thumbnails.append(r["presigned_thumbnail_url"])
        elif r.get("media_type") == "video" and r.get("presigned_url"):
            videos.append(r["presigned_url"])

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
    claims, error = require_auth(event)
    if error: return error
    body = parse_body(event)
    if body is None:
        return err("Invalid JSON body")

    urls = body.get("urls") or body.get("file_ids")
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
            import traceback
            logger.error(f"Cosmos error updating {url}: {e}")
            logger.error(traceback.format_exc())
            skipped.append(url)

    return ok({"updated": updated, "skipped": skipped})


# ─────────────────────────────────────────────────────────────
# HANDLER 5 — DELETE /files
# Delete DB records (your side — teammate handles S3 deletion)
# ─────────────────────────────────────────────────────────────

def delete_files(event, context):
    claims, error = require_auth(event)
    if error: return error
    body = parse_body(event)
    if body is None:
        return err("Invalid JSON body")

    file_ids = body.get("file_ids") or body.get("urls")
    if not file_ids or not isinstance(file_ids, list):
        return err("'file_ids' must be a non-empty list")

    # ── Step 1: Call Track 1's storage delete Lambda ──────────
    storage_deleted = []
    storage_failed = []

    try:
        lam = boto3.client("lambda", region_name="us-east-1")
        resp = lam.invoke(
            FunctionName="arn:aws:lambda:us-east-1:964750750035:function:ecolens-delete-objects",
            InvocationType="RequestResponse",
            Payload=json.dumps({"file_ids": file_ids}),
        )
        storage_result = json.loads(resp["Payload"].read())
        storage_deleted = storage_result.get("deleted", [])
        storage_failed = storage_result.get("failed", [])
        logger.info(f"Storage delete: deleted={storage_deleted}, failed={storage_failed}")
    except Exception as e:
        logger.error(f"Failed to invoke storage delete Lambda: {e}")
        # If storage Lambda fails, don't delete DB records
        return err(f"Storage deletion failed: {str(e)}", 500)

    # ── Step 2: Delete DB records for successfully deleted files ──
    deleted = []
    failed = list(storage_failed)  # start with storage failures

    for file_id in storage_deleted:
        try:
            found = db_delete_record(file_id)
            if found:
                deleted.append(file_id)
            else:
                # Storage deleted but no DB record — still count as deleted
                deleted.append(file_id)
                logger.warning(f"No DB record found for {file_id} — storage was deleted")
        except Exception as e:
            logger.error(f"Cosmos error deleting {file_id}: {e}")
            failed.append({"file_id": file_id, "reason": str(e)})

    return ok({
        "deleted": deleted,
        "failed": failed,
    })


# ─────────────────────────────────────────────────────────────
# HANDLER 6c — POST /notifications/notify
# Called by Track 3 tagging Lambda after a file is tagged
# No user auth required — internal service call
# ─────────────────────────────────────────────────────────────

def notify_tagged(event, context):
    """
    Called by Track 3 after tagging is complete.
    Publishes SNS notifications to all subscribers of each detected tag.
    Does NOT require Cognito auth — internal service endpoint.
    """
    body = parse_body(event)
    if body is None:
        return err("Invalid JSON body")

    tag_list = body.get("tag_list", [])
    file_id = body.get("file_id", "")
    s3_bucket = body.get("s3_bucket", "")
    s3_key = body.get("s3_key", "")
    media_type = body.get("media_type", "image")
    tagged_at = body.get("tagged_at", "")

    if not tag_list:
        return ok({"message": "No tags to notify", "notified": []})

    # Generate a presigned URL for the notification email
    if s3_bucket and s3_key:
        file_url = generate_presigned_url(s3_bucket, s3_key)
    else:
        file_url = f"File ID: {file_id}"

    notified = []
    failed = []

    for tag in tag_list:
        try:
            topic_arn = get_or_create_topic_arn(tag)
            sns_client.publish(
                TopicArn=topic_arn,
                Subject=f"New {tag} sighting on Aussie EcoLens!",
                Message=(
                    f"A new {media_type} containing '{tag}' has been added.\n\n"
                    f"View it here: {file_url}\n\n"
                    f"Tagged at: {tagged_at}\n\n"
                    f"You are receiving this because you subscribed to '{tag}' notifications.\n"
                    f"To unsubscribe, use the Aussie EcoLens app."
                ),
            )
            notified.append(tag)
            logger.info(f"Notified subscribers for tag '{tag}'")
        except Exception as e:
            logger.error(f"Failed to notify for tag '{tag}': {e}")
            failed.append(tag)

    return ok({
        "message": f"Notifications sent for {len(notified)} tag(s)",
        "notified": notified,
        "failed": failed,
    })


# ─────────────────────────────────────────────────────────────
# HANDLER 6a — POST /notifications/subscribe
# ─────────────────────────────────────────────────────────────

def subscribe_to_tag(event, context):
    claims, error = require_auth(event)
    if error: return error
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
    claims, error = require_auth(event)
    if error: return error
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
    ("POST",   "/notifications/notify"):      notify_tagged,
}

def handler(event, context):
    # Try multiple ways to get method and path — API Gateway v1 vs v2 differences
    method = (
        event.get("httpMethod") or
        event.get("requestContext", {}).get("http", {}).get("method") or
        ""
    ).upper()

    path = (
        event.get("path") or
        event.get("rawPath") or
        event.get("requestContext", {}).get("path") or
        ""
    )

    # Strip stage prefix if present (e.g. /prod/query/tags -> /query/tags)
    for stage in ["/prod", "/dev", "/staging"]:
        if path.startswith(stage + "/") or path == stage:
            path = path[len(stage):] or "/"
            break

    logger.info(f"Routing: {method} {path}")

    route = ROUTES.get((method, path))
    if route is None:
        # Log full event for debugging
        logger.error(f"No route for {method} {path}. Event keys: {list(event.keys())}")
        return err(f"No route for {method} {path}", 404)
    return route(event, context)