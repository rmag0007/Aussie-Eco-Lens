# Track 4 — Query APIs & Notifications
**Developer:** Akshaya  
**Assignment:** FIT5225 Assignment 2 — Aussie EcoLens

---

## Services Used

| Service | Purpose |
|---|---|
| AWS Lambda | Single function handling all 8 endpoints |
| AWS API Gateway | REST API with Cognito authorizer |
| AWS SNS | Email notifications for species tag subscriptions |
| AWS Cognito | JWT token verification (cross-account, Track 2) |
| Azure Cosmos DB | File metadata storage (cross-cloud, Track 3) |
| AWS S3 (cross-account) | Presigned URL generation for Track 1's buckets |
| AWS EventBridge | Warmup rule every 5 min to keep Lambda warm |

---

## Endpoints

**Base URL:** `https://pjt56rikpk.execute-api.ap-southeast-2.amazonaws.com/prod`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/query/tags` | ✅ Cognito | Find files by species tag + minimum count (AND logic) |
| GET | `/query/thumbnail` | ✅ Cognito | Map thumbnail key/URL → full-size presigned URL |
| POST | `/query/file` | ✅ Cognito | Upload image/video, ML detects species, returns matching files |
| POST | `/tags/bulk` | ✅ Cognito | Add or remove tags from multiple files |
| DELETE | `/files` | ✅ Cognito | Delete files from S3 (via Track 1) and Cosmos DB |
| POST | `/notifications/subscribe` | ✅ Cognito | Subscribe email to species tag notifications |
| POST | `/notifications/unsubscribe` | ✅ Cognito | Unsubscribe email from species tag |
| POST | `/notifications/notify` | ❌ No auth | Called by Track 3 after tagging — triggers SNS emails |

---

## Main Files

| File | Description |
|---|---|
| `lambdas.py` | All Lambda handlers + router (single entry point) |
| `ml_inference.py` | ML pipeline — MegaDetector + 46-species classifier |
| `query_ui.html` | Frontend UI (also deployed as `query.html` in root) |
| `openapi.yaml` | API specification |
| `tests.py` | Unit tests |
| `deployment.zip` | Lambda deployment package |

---

## What Works

- ✅ **Search by tags** — AND logic with minimum counts, returns presigned thumbnail URLs
- ✅ **Thumbnail → Full image** — maps thumbnail key/URL to full-size presigned URL
- ✅ **Search by file** — ML model detects species from uploaded image/video, returns matching DB records. File is NOT stored.
- ✅ **Bulk tag edit** — add/remove tags with operation 0/1, keeps `tags` dict and `tag_list` array in sync
- ✅ **Delete files** — calls Track 1's Lambda to delete from S3, then deletes Cosmos DB record
- ✅ **SNS notifications** — subscribe/unsubscribe to species tags, notify endpoint triggered by Track 3
- ✅ **Cross-account S3 presigned URLs** — generates valid URLs for Track 1's `us-east-1` buckets
- ✅ **Cognito JWT verification** — cross-account token validation
- ✅ **CORS** — all endpoints support browser-based requests
- ✅ **UI** — fully functional with login integration, thumbnail previews, click-to-fullsize modal

---

## Known Limitations

- **ML cold start** — `/query/file` takes 2–3 minutes on first call after Lambda goes cold (torch install). EventBridge warmup rule runs every 5 minutes to mitigate.
- **File size limit** — API Gateway has a ~10MB limit. The UI automatically compresses images over 2MB before sending.
- **Presigned URL expiry** — URLs expire after 1 hour. Re-querying generates fresh URLs.
- **Cosmos DB cross-partition queries** — all queries use `enable_cross_partition_query=True` which has higher RU cost but is necessary since `owner_sub` is the partition key.

---

## How It Integrates With Other Tracks

**Track 1 (Sam — Storage, `us-east-1`):**
- Track 4 reads from Sam's S3 buckets (`ecolens-raw-slee0133`, `ecolens-thumbs-slee0133`, `ecolens-frames-slee0133`) using cross-account IAM role
- Track 4 calls Sam's delete Lambda (`arn:aws:lambda:us-east-1:964750750035:function:ecolens-delete-objects`) for file deletion
- All presigned URLs are generated with `region_name="us-east-1"` to match Sam's bucket region

**Track 2 (Cognito — `ap-southeast-2`):**
- All protected endpoints verify Cognito JWT from `Authorization: Bearer <token>` header
- User Pool: `ap-southeast-2_VJ2fhcUc7`
- After login, `login.html` stores token as `ecolens_id_token` in sessionStorage — `query.html` reads it automatically

**Track 3 (Suryashree — Azure Cosmos DB, Japan East):**
- All file metadata is stored in and queried from Track 3's Cosmos DB (`aussie_ecolens` / `files` container)
- Track 3 calls Track 4's `/notifications/notify` endpoint after tagging a file, which triggers SNS email notifications to subscribers

---

## AWS Account Info

| Resource | Value |
|---|---|
| Account ID | `267451756103` |
| Region | `ap-southeast-2` |
| Lambda function | `ecolens-track4` |
| Lambda role | `arn:aws:iam::267451756103:role/ecolens-track4-role-yjei507z` |
| ML model bucket | `aussie-ecolens-assets-267451756103-ap-southeast-2-an` |
| SNS topic prefix | `aussie-ecolens` |
