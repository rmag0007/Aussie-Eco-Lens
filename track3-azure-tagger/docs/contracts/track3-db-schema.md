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
  "s3_url": "https://ecolens-raw.s3.amazonaws.com/uploads/user/file.jpg",

  "thumbnail_bucket": "ecolens-thumbs",
  "thumbnail_key": "thumbs/user/file.jpg",
  "thumbnail_url": "https://ecolens-thumbs.s3.amazonaws.com/thumbs/user/file.jpg",

  "frames": [],

  "tags": {
    "kangaroo": 2,
    "wombat": 1
  },

  "tag_list": [
    "kangaroo",
    "wombat"
  ],

  "status": "tagged",
  "uploaded_at": "2026-06-04T10:30:00Z",
  "tagged_at": "2026-06-04T10:31:00Z",
  "updated_at": "2026-06-04T10:31:00Z"
}
