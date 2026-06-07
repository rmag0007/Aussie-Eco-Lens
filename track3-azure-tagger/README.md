# Track 3 — Azure ML Tagging and Cosmos DB

This module implements Track 3 for Aussie EcoLens.

## Responsibility

Track 3 receives upload events from Track 1, generates ML tags, and stores file metadata and tags in Azure Cosmos DB.

## Current status

- Azure Function endpoint created: `POST /api/tag-upload`
- Cosmos DB insertion works
- Fake ML tagging works for image/video events
- Real ML model integration pending Track 1 file access method

## Azure resources

- Cosmos DB database: `aussie_ecolens`
- Container: `files`
- Partition key: `/owner_sub`

## Endpoint

`POST /api/tag-upload`

## Input

Uses Track 1 upload event format.

## Output

Returns detected tags and stores one document in Cosmos DB.

## Local testing

Start the Azure Function:

```bash
func start

test image event
curl -X POST http://localhost:7071/api/tag-upload \
  -H "Content-Type: application/json" \
  -d @tests/events/image_event.json
 
test video event
curl -X POST http://localhost:7071/api/tag-upload \
  -H "Content-Type: application/json" \
  -d @tests/events/video_event.json
