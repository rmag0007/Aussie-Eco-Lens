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

## ML Pipeline Status

The Track 3 tagging pipeline can now:

1. Download an image using a presigned S3 URL.
2. Run MegaDetector to detect animal regions.
3. Crop detected animals.
4. Run the SpeciesNet model on the detected crop.
5. Return real tag counts.
6. Save the tagged file record into Azure Cosmos DB.

Test result:

```text
Prediction: australian brushturkey (Alectura_lathami) confidence=0.9999
Final tags:
{'australian brushturkey': 1}

## Deployment Status

Track 3 is deployed as an Azure Function:

`POST https://aussie-ecolens-track3-suryashree.azurewebsites.net/api/tag-upload`

Current deployed flow:

1. Receives Track 1 upload-event JSON.
2. Downloads the uploaded image using the provided presigned S3 URL.
3. Runs the cloud tagging pipeline.
4. Stores file metadata and tags in Azure Cosmos DB.
5. Calls Track 4's notification endpoint after tagging.

The deployed Azure Function uses SpeciesNet/full-image fallback because full MegaDetector deployment exceeded Azure Functions Consumption build storage. The full MegaDetector + SpeciesNet pipeline has been validated locally.

For integration testing, `AUTH_BYPASS=true` is temporarily enabled. This will be disabled once Track 2's final Cognito token flow is connected.
