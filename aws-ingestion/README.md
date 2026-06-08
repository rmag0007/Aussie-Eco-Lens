# Track 1 — AWS Ingestion Pipeline

The AWS half of Aussie EcoLens. Handles **uploads, deduplication, thumbnails, video frame extraction, delete cascade, and event delivery to Track 3 (Azure)**.

All infrastructure is defined in `template.yaml` and deployed via AWS SAM.

---

## What it does

```
User → POST /upload-url ─────→ presigned PUT URL ──→ User PUTs file directly to S3
                                                            ↓
                                                S3 ObjectCreated event
                                                            ↓
                                              ingest-trigger Lambda
                                                ├─ SHA256 checksum dedup (DynamoDB)
                                                ├─ invoke thumbnail Lambda (images)
                                                ├─ invoke video-frames Lambda (videos)
                                                └─ HTTP POST upload-event JSON → Azure Function
```

Rubric coverage: **2.1.1** upload + checksum dedup, **2.1.2** OpenCV thumbnails + 1 fps video frames, **2.3.2** delete cascade (storage side), **1.3** cross-account bucket policies.

---

## Live endpoints (current deployment)

| Thing | Value |
|---|---|
| **Upload API** | `POST https://pe8yzy3fo3.execute-api.us-east-1.amazonaws.com/upload-url` |
| Region | `us-east-1` |
| AWS account | `964750750035` |
| Raw bucket | `ecolens-raw-slee0133` |
| Thumbnails bucket | `ecolens-thumbs-slee0133` |
| Frames bucket | `ecolens-frames-slee0133` |
| Query-tmp bucket | `ecolens-query-tmp-slee0133` |
| DynamoDB table | `file_checksums` (GSI: `by-file-id`) |
| Delete Lambda (cross-account invoke) | `arn:aws:lambda:us-east-1:964750750035:function:ecolens-delete-objects` |
| Ingest trigger Lambda | `arn:aws:lambda:us-east-1:964750750035:function:ecolens-ingest-trigger` |
| Upload handler Lambda | `arn:aws:lambda:us-east-1:964750750035:function:ecolens-upload-handler` |
| Thumbnail Lambda | `arn:aws:lambda:us-east-1:964750750035:function:ecolens-thumbnail` |
| Video frames Lambda | `arn:aws:lambda:us-east-1:964750750035:function:ecolens-video-frames` |
| Track 3 (downstream) tagger URL | `https://aussie-ecolens-track3-suryashree.azurewebsites.net/api/tag-upload` |

---

## Resources deployed

| Type | Name | Purpose |
|---|---|---|
| API Gateway HTTP API | `UploadApi` | `POST /upload-url` endpoint (returns presigned PUT URL) |
| Lambda | `ecolens-upload-handler` | Validates filename, generates `file_id`, returns presigned URL |
| Lambda | `ecolens-ingest-trigger` | Fires on S3 raw upload — dedup, orchestrate, deliver to Track 3 |
| Lambda | `ecolens-thumbnail` | OpenCV resize (300px max, aspect-ratio preserved, JPEG q80) |
| Lambda | `ecolens-video-frames` | ffmpeg extracts 1 frame per second from videos |
| Lambda | `ecolens-delete-objects` | Cascade-delete raw + thumb + frames + dedup row (called by Track 4) |
| S3 | `ecolens-raw-<suffix>` | Original uploads (private, versioned, CORS for browser PUT) |
| S3 | `ecolens-thumbs-<suffix>` | Generated thumbnails |
| S3 | `ecolens-frames-<suffix>` | Extracted video frames (`frames/{file_id}/{NNNN}.jpg`) |
| S3 | `ecolens-query-tmp-<suffix>` | Transient uploads for query-by-file (24h lifecycle, no pipeline trigger) |
| DynamoDB | `file_checksums` | SHA256 → file_id dedup table (with `by-file-id` GSI for delete lookups) |

---

## Deploy

Requires: AWS CLI v2, SAM CLI, Docker (for OpenCV/ffmpeg in-zip builds), Python 3.11.

```bash
# Get your LabRole ARN
aws iam get-role --role-name LabRole --query 'Role.Arn' --output text

# First-time deploy
sam build --use-container
sam deploy --guided     # supply Suffix and LabRoleArn parameters

# Subsequent deploys
sam build --use-container
sam deploy
```

Outputs after deploy include `UploadApiUrl` — the public endpoint for `POST /upload-url`.

---

## Test (smoke)

```bash
# 1. Get a presigned upload URL via the API
API="$(aws cloudformation describe-stacks --stack-name ecolens-track1 \
  --query "Stacks[0].Outputs[?OutputKey=='UploadApiUrl'].OutputValue" --output text)"

curl -X POST "$API/upload-url" \
  -H "Content-Type: application/json" \
  -d '{"filename":"koala.jpg","content_type":"image/jpeg","owner_sub":"test-user"}'
# → returns {upload_url, file_id, s3_bucket, s3_key, expires_in_seconds}

# 2. PUT the file directly to S3 using the returned upload_url
curl -X PUT "<upload_url>" \
  -H "Content-Type: image/jpeg" \
  --data-binary "@koala.jpg"

# 3. Watch the pipeline fire
sam logs --stack-name ecolens-track1 --name IngestTriggerFunction --tail
# You will see: checksum → UPLOAD_EVENT → Tagger delivery OK (200)

# 4. Test dedup — upload the same file again, watch for "DUPLICATE detected"

# 5. Test delete cascade
aws lambda invoke --function-name ecolens-delete-objects \
  --payload '{"file_ids":["<paste file_id>"]}' \
  --cli-binary-format raw-in-base64-out /tmp/out.json && cat /tmp/out.json
```

---

## Contracts (in `../docs/contracts/`)

- `buckets-and-keys.md` — bucket naming + key conventions (consumed by all tracks)
- `upload-event.md` — JSON Track 3's Azure Function receives after each upload
- `delete-contract.md` — Track 4's invoke signature for `ecolens-delete-objects`
- `tag-only-contract.md` — transient query-by-file flow (rubric 2.2.3)

---

## Cross-account access (Track 4)

`template.yaml` includes S3 bucket policies granting Track 4's account (`267451756103`) read access to raw/thumbs/frames and read+write+delete on query-tmp. Track 4's Lambda generates presigned URLs itself using its own LabRole.

The `ecolens-delete-objects` Lambda has a resource policy allowing Track 4's account to `lambda:InvokeFunction`.

---

## Notes / design decisions

- **In-zip OpenCV + ffmpeg** instead of Lambda layers — AWS Academy SCP blocks `lambda:GetLayerVersion` on cross-account layers like Klayers. `imageio-ffmpeg` bundles the binary inside the wheel.
- **Presigned URLs everywhere** (60-min default) — Azure Function and Track 4 fetch S3 objects via plain HTTPS GET, no AWS credentials needed cross-cloud.
- **DynamoDB GSI `by-file-id`** — lets the delete Lambda look up an `s3_key` in one query instead of scanning the table.
- **`query-tmp` bucket has no S3 event trigger** — guarantees the rubric 2.2.3 "not persisted" requirement at the infrastructure level. Lifecycle rule auto-expires after 24h as defence in depth.
- **`Tagger URL` is an env var** — model/endpoint changes don't require code changes (aligns with rubric 4.1 thinking).
