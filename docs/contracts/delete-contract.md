# Delete Contract (Track 1 ↔ Track 4)

Track 4 owns the public `DELETE /files` endpoint and DB row removal.
Track 4 invokes Track 1's Lambda to remove storage objects.

## Lambda
- Name: `ecolens-delete-objects`
- Invocation: direct (Lambda Invoke) or via API Gateway internal route

## Request
```json
{ "file_ids": ["uuid1", "uuid2"] }
```
Track 4 must supply file_ids it pulled from the DB (which holds the s3_keys).
If Track 4 only has URLs, it must map URL → file_id via the DB first.

## Response
```json
{
  "deleted": ["uuid1"],
  "failed": [{"file_id": "uuid2", "reason": "not_found"}]
}
```

## Behaviour
- Removes from `ecolens-raw`, `ecolens-thumbs`, and `ecolens-frames/{file_id}/`
- Idempotent: missing objects count as success
- Also removes the dedup row from `file_checksums` DynamoDB table
