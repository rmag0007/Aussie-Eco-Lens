# Track 3 Azure Cosmos DB Schema

Provider: Azure Cosmos DB for NoSQL  
Database: `aussie_ecolens`  
Container: `files`  
Partition key: `/owner_sub`

Each uploaded image/video has one document.

## Document shape

```json
{
  "id": "uuid-v4",
  "file_id": "uuid-v4",

  "owner_sub": "cognito-user-sub",
  "owner_email": "user@email.com",

  "media_type": "image",
  "checksum_sha256": "a3f9...",

  "s3_bucket": "ecolens-raw",
  "s3_key": "uploads/user/file.jpg",
  "s3_presigned_url_used_for_tagging": "temporary URL, expires",

  "thumbnail_bucket": "ecolens-thumbs",
  "thumbnail_key": "thumbs/user/file.jpg",
  "thumbnail_presigned_url_used_for_tagging": "temporary URL, expires",

  "frames": [],

  "tags": {
    "kangaroo": 2
  },

  "tag_list": [
    "kangaroo"
  ],

  "status": "tagged",
  "uploaded_at": "2026-06-04T10:30:00Z",
  "tagged_at": "2026-06-04T10:31:00Z",
  "updated_at": "2026-06-04T10:31:00Z"
}
