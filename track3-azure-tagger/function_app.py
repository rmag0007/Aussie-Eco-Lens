import json
from datetime import datetime, timezone

import azure.functions as func

from auth import get_user_from_request
from database.cosmos_db import save_file_record
from tagging.pipeline import tag_media_file

app = func.FunctionApp()


@app.route(route="tag-upload", methods=["POST"])
def tag_upload(req: func.HttpRequest) -> func.HttpResponse:
    try:
        # 1. Verify Cognito ID token from Authorization header
        user = get_user_from_request(req.headers)

        token_owner_sub = user["sub"]
        owner_email = user.get("email")

    # 1. TEMPORARY DEV AUTH BYPASS
# Replace this with real Cognito auth once Track 2 is ready.
        token_owner_sub = "test-user-123"
        owner_email = "test@example.com"
        # 2. Read Track 1 upload event
        event = req.get_json()

        file_id = event["file_id"]
        owner_sub = event.get("owner_sub", token_owner_sub)

        # Safety check: token user should match event owner
        if owner_sub != token_owner_sub:
            return func.HttpResponse(
                json.dumps({
                    "status": "unauthorised",
                    "message": "Token user does not match upload owner"
                }),
                status_code=403,
                mimetype="application/json"
            )

        media_type = event["media_type"]
        s3_bucket = event["s3_bucket"]
        s3_key = event["s3_key"]
        s3_url = event["s3_url"]
        checksum_sha256 = event["checksum_sha256"]

        thumbnail_bucket = event.get("thumbnail_bucket")
        thumbnail_key = event.get("thumbnail_key")
        thumbnail_url = event.get("thumbnail_url")

        frames = event.get("frames", [])
        uploaded_at = event.get("uploaded_at")

        # 3. Run ML tagging
        # For now this returns fake tags from tagging/pipeline.py
        tags = tag_media_file(
            media_type=media_type,
            s3_url=s3_url,
            frames=frames
        )

        now = datetime.now(timezone.utc).isoformat()

        # 4. Build Cosmos DB record
        record = {
            "id": file_id,
            "file_id": file_id,

            "owner_sub": owner_sub,
            "owner_email": owner_email,

            "media_type": media_type,
            "checksum_sha256": checksum_sha256,

            "s3_bucket": s3_bucket,
            "s3_key": s3_key,
            "s3_url": s3_url,

            "thumbnail_bucket": thumbnail_bucket,
            "thumbnail_key": thumbnail_key,
            "thumbnail_url": thumbnail_url,

            "frames": frames,

            "tags": tags,
            "tag_list": list(tags.keys()),

            "status": "tagged",
            "uploaded_at": uploaded_at,
            "tagged_at": now,
            "updated_at": now
        }

        # 5. Save to Azure Cosmos DB
        save_file_record(record)

        # 6. Return result
        return func.HttpResponse(
            json.dumps({
                "status": "success",
                "file_id": file_id,
                "owner_sub": owner_sub,
                "tags": tags,
                "tag_list": list(tags.keys())
            }),
            status_code=200,
            mimetype="application/json"
        )

    except ValueError as e:
        return func.HttpResponse(
            json.dumps({
                "status": "unauthorised",
                "message": str(e)
            }),
            status_code=401,
            mimetype="application/json"
        )

    except KeyError as e:
        return func.HttpResponse(
            json.dumps({
                "status": "bad_request",
                "message": f"Missing required field: {str(e)}"
            }),
            status_code=400,
            mimetype="application/json"
        )

    except Exception as e:
        return func.HttpResponse(
            json.dumps({
                "status": "error",
                "message": str(e)
            }),
            status_code=500,
            mimetype="application/json"
        )
