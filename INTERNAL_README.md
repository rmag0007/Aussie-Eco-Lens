# AussieEcoLens — Track 2: Auth & Cross-Cloud Security

## Overview
This track implements all authentication and authorisation for the AussieEcoLens platform using AWS Cognito, API Gateway, and a cross-cloud JWT verification module.

---

## Project Structure

├── signup.html       # User registration page
├── login.html        # User login page
├── index.html        # Protected dashboard
├── auth.py           # JWT verification module (for cloud functions)
├── test_auth.py      # Local test script for auth.py
├── requirements.txt  # Python dependencies
└── INTERNAL_README.md

## AWS Resources Created

| Resource | Name/ID |
|---|---|
| Cognito User Pool | ap-southeast-2_VJ2fhcUc7 |
| Cognito App Client | ueh2ft2l8ap6ccrmk5tcjfsua |
| API Gateway | mdd2joqn1a |
| Cognito Authoriser | 14tlcc |
| Region | ap-southeast-2 (Sydney) |

---

## Setup & Dependencies

### Python (for auth.py)
```bash
pip install python-jose cryptography
```

### Frontend
No installation needed. Open `signup.html` directly in a browser.

---

## Authentication Flow

1. User registers via `signup.html` (email, first name, last name, password)
2. Cognito sends a verification code to their email
3. User enters the code — account is confirmed
4. User logs in via `login.html`
5. Cognito returns a JWT ID token
6. Token is stored in `sessionStorage`
7. Every API request includes the token in the `Authorization` header
8. API Gateway Cognito Authoriser validates the token before allowing the request through

---

## API Gateway

**Base URL:**
https://mdd2joqn1a.execute-api.ap-southeast-2.amazonaws.com/prod

**Test endpoint (requires auth):**

GET /health

**How to call any protected endpoint:**

Include this header in every request:
Authorization: Bearer <ID token>

**Test without token (expect 401):**
```bash
curl -X GET https://mdd2joqn1a.execute-api.ap-southeast-2.amazonaws.com/prod/health
```

**Test with token (expect 200):**
```bash
curl -X GET https://mdd2joqn1a.execute-api.ap-southeast-2.amazonaws.com/prod/health \
  -H "Authorization: Bearer YOUR_ID_TOKEN"
```

---

## Protecting a New Endpoint (Track 1 & Track 4)

When adding a new method to API Gateway, attach the Cognito Authoriser using this command:

```bash
aws apigateway put-method \
  --rest-api-id mdd2joqn1a \
  --resource-id YOUR_RESOURCE_ID \
  --http-method POST \
  --authorization-type COGNITO_USER_POOLS \
  --authorizer-id 14tlcc \
  --region ap-southeast-2
```

Replace `YOUR_RESOURCE_ID` with your resource's ID and `POST` with your HTTP method.

---

## IAM Roles (Lambda Execution Roles)

When creating a Lambda function, paste the relevant role ARN into the **"Execution role"** field.

| Track | Role ARN |
|---|---|
| Track 1 — Upload/Thumbnail Lambda | arn:aws:iam::163475281708:role/ecolens-upload-role |
| Track 3 — ML Tagging/Database Lambda | arn:aws:iam::163475281708:role/ecolens-tagging-role |
| Track 4 — Query/Notifications Lambda | arn:aws:iam::163475281708:role/ecolens-query-role |

### Permissions per role

**ecolens-upload-role (Track 1)**
- AmazonS3FullAccess
- CloudWatchLogsFullAccess

**ecolens-tagging-role (Track 3)**
- AmazonS3ReadOnlyAccess
- AmazonDynamoDBFullAccess
- CloudWatchLogsFullAccess

**ecolens-query-role (Track 4)**
- AmazonS3ReadOnlyAccess
- AmazonDynamoDBFullAccess
- AmazonSNSFullAccess
- CloudWatchLogsFullAccess

---

## Cross-Cloud JWT Verification (Track 3)

`auth.py` allows your cloud function to verify Cognito tokens without calling AWS directly.

## Notes
- JWT tokens expire after **1 hour** — users must log in again to get a fresh token
- Always use the **ID token** (not the access token) in the Authorization header
- The `auth.py` JWKS cache means public keys are only fetched once per function cold start — no performance issue


## NOTE - 
Once SES production access is approved, email verification works automatically for all users.