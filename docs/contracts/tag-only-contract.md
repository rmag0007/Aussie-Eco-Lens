# Transient Tag-Only Contract (Track 1 ↔ Track 4)

Supports rubric 2.2.3 ("Find files based on the tags of a file"), 8 marks.
The query file MUST NOT be persisted or added to the DB.

## Endpoint
- Path: `POST /query-by-file`
- Owned by: Track 4 (API Gateway + Lambda)
- Uses: Track 1's `ecolens-query-tmp` bucket + Track 3's tagger

## Flow
1. User uploads a file to `POST /query-by-file` (multipart or presigned URL)
2. File lands in `ecolens-query-tmp` with key `query/{request_id}.{ext}`
3. Track 4's handler invokes Track 3's tagger DIRECTLY (no S3 event, no
   ingest-trigger), passing the temp object location
4. Tagger returns tag list; Track 4 queries DB for matching files
5. Response returned to user

## Guarantees from Track 1
- `ecolens-query-tmp` has a 1-day expiration lifecycle rule (defence in depth)
- Bucket is NOT wired to `ingest-trigger` (no event subscription)
- No dedup table write
- No emission of upload-event JSON
