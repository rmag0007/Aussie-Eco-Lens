# Track 3 Azure Tagging Endpoint

## Endpoint

`POST /api/tag-upload`

Hosted on Azure Functions.

## Authentication

Requires Cognito ID token from Track 2.

Header:

```http
Authorization: Bearer <ID_TOKEN>
