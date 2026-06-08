import json
import os
from datetime import datetime, timezone

import azure.functions as func

from auth import get_user_from_request
from database.cosmos_db import save_file_record
from tagging.pipeline import tag_media_file
from validation import validate_upload_event
from notifications import notify_file_tagged
import azure.functions as func

app = func.FunctionApp()


@app.route(route="tag-upload", methods=["POST"],auth_level=func.AuthLevel.ANONYMOUS)
def tag_upload(req: func.HttpRequest) -> func.HttpResponse:
    try:
        # TEMPORARY DEV AUTH BYPASS
        # Used only while Track 2 Cognito integration is pending.
        # Before final integration, replace this with:
# user = get_user_from_request(req.headers)
# token_owner_sub = user["sub"]
#       owner_email = user.get("email")
        # token_owner_sub = "test-user-123"
        # owner_email = "test@example.com"
        
        # 2. Read Track 1 upload event
        event = req.get_json()
        validate_upload_event(event)

        auth_bypass = os.environ.get("AUTH_BYPASS", "false").lower() == "true"

        if auth_bypass:
            # DEV/INTEGRATION TESTING ONLY
            token_owner_sub = event.get("owner_sub")
            owner_email = event.get("owner_email", "test@example.com")
        else:
            user = get_user_from_request(req.headers)
            token_owner_sub = user["sub"]
            owner_email = user.get("email")

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
        
            # User ownership
            "owner_sub": owner_sub,
            "owner_email": owner_email,

            # File info
            "media_type": media_type,
            "checksum_sha256": checksum_sha256,

            # Permanent S3 location for original file
            # These should be stored long-term because they do not expire.
            "s3_bucket": s3_bucket,
            "s3_key": s3_key,

            # Temporary presigned URL used only for ML tagging.
            # This expires, so Track 4 should NOT rely on it long-term.
            "s3_presigned_url_used_for_tagging": s3_url,

            # Permanent S3 location for thumbnail
            "thumbnail_bucket": thumbnail_bucket,
            "thumbnail_key": thumbnail_key,

            # Temporary presigned thumbnail URL, if Track 1 sends one
            "thumbnail_presigned_url_used_for_tagging": thumbnail_url,

            # Video frames
            # Each frame should store permanent bucket/key.
            # If Track 1 also sends presigned s3_url for frames, it can be kept temporarily.
            "frames": frames,

            # ML tag output
            "tags": tags,
            "tag_list": list(tags.keys()),

            # Status/timestamps
            "status": "tagged",
            "uploaded_at": uploaded_at,
            "tagged_at": now,
            "updated_at": now
        }

        # 5. Save to Azure Cosmos DB
        save_file_record(record)
        notification_result = notify_file_tagged(record)

        # 6. Return result
        return func.HttpResponse(
           json.dumps({
                "status": "success",
                "file_id": file_id,
                "owner_sub": owner_sub,
                "tags": tags,
                "tag_list": list(tags.keys()),
                "notification": notification_result
            }),
            status_code=200,
            mimetype="application/json"
        )

    except ValueError as e:
        return func.HttpResponse(
            json.dumps({
                "status": "bad_request",
                "message": str(e)
            }),
            status_code=400,
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
