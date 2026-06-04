from auth import verify_token

# Go to your index.html in the browser, click "Copy ID Token", paste it below
token = "eyJraWQiOiI2WVBpdzdVUlk5eEVMbWhBRWtmK3ZUYVhvb2o3Q0J5eG1VUmlJSVVJaXE0PSIsImFsZyI6IlJTMjU2In0.eyJzdWIiOiI2OTFlNzQ3OC1kMGExLTcwM2ItMDViMS0wODJhYWUwNmM1NmIiLCJlbWFpbF92ZXJpZmllZCI6ZmFsc2UsImlzcyI6Imh0dHBzOi8vY29nbml0by1pZHAuYXAtc291dGhlYXN0LTIuYW1hem9uYXdzLmNvbS9hcC1zb3V0aGVhc3QtMl9WSjJmaGNVYzciLCJjb2duaXRvOnVzZXJuYW1lIjoiNjkxZTc0NzgtZDBhMS03MDNiLTA1YjEtMDgyYWFlMDZjNTZiIiwiZ2l2ZW5fbmFtZSI6IlJpc2hpIiwib3JpZ2luX2p0aSI6ImRhYTIyYjk3LTYxMGQtNDRmNS05ZjhhLWEzYzk2MWRjOTQ1NSIsImF1ZCI6InVlaDJmdDJsOGFwNmNjcm1rNXRjamZzdWEiLCJldmVudF9pZCI6IjU0OGE1ZjFmLTFkZDItNDE5OC04YTQ4LTM3YjllOTc4MDgzMyIsInRva2VuX3VzZSI6ImlkIiwiYXV0aF90aW1lIjoxNzgwNDYxMDg5LCJleHAiOjE3ODA0NjQ2ODksImlhdCI6MTc4MDQ2MTA4OSwiZmFtaWx5X25hbWUiOiJNYWdhdmkiLCJqdGkiOiIyMzc1ZTllNy03N2U3LTQ2OTYtYTA5My0zMjI3ZDI5YTQzOTQiLCJlbWFpbCI6InJpc2hpbWFnYXZpN0BnbWFpbC5jb20ifQ.TjSnX03qWwCfsfX-NDczknoS0MtR8jIux0A-pPsRW67Ur-qYjibAj6qocC4wK_1n4T7vPCqQeVjfPI7s05EwiYj0ddM9B9iHT3L1i7DbmFiYO_VdtfDZ43TAgkhO9EpUfW2pzRWeWydq9DMdVLrXnYoZ7j_V6-fTKtTrH4sZ714Ak5UTytlAN60hviy11KxqKrMz3GtCV3MhhaP564jb4KcXFMtt68or1DGynYyabYH7WRaCx5ZZz0atiKcbleE87whqmwhw-ecSiCywrYIAvM3GnhwH2AfH90fcPtdh_Rv5yKDSiMXE5Qqm81yKl4d1TwpjxNdjicb_220FF2Kn0Q"

try:
    payload = verify_token(token)
    print("✅ Token valid!")
    print(f"   Email:      {payload['email']}")
    print(f"   Name:       {payload['given_name']} {payload['family_name']}")
    print(f"   User ID:    {payload['sub']}")
    print(f"   Expires at: {payload['exp']}")
except ValueError as e:
    print(f"❌ {e}")