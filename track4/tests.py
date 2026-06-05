"""
Unit tests for Track 4 — Query APIs & Notifications
Run with:  python -m pytest tests.py -v
"""

import json
import unittest
from unittest.mock import patch, MagicMock

# Patch boto3 before importing lambdas so no real AWS calls are made
import sys
sys.modules['boto3'] = MagicMock()

import lambdas  # noqa: E402  (import after mock)


def make_event(method="POST", path="/", body=None, query_params=None, headers=None, base64=False):
    return {
        "httpMethod": method,
        "path": path,
        "body": json.dumps(body) if body and not base64 else body,
        "queryStringParameters": query_params or {},
        "headers": headers or {},
        "isBase64Encoded": base64,
    }


class TestQueryByTags(unittest.TestCase):

    def test_basic_species_query(self):
        event = make_event(body={"koala": 1})
        resp = lambdas.query_by_tags(event, None)
        self.assertEqual(resp["statusCode"], 200)
        data = json.loads(resp["body"])
        self.assertIn("thumbnails", data)
        self.assertIn("videos", data)
        # Both koala records should match
        self.assertEqual(len(data["thumbnails"]), 2)

    def test_count_filters_correctly(self):
        # Only first record has koala >= 3
        event = make_event(body={"koala": 3})
        resp = lambdas.query_by_tags(event, None)
        data = json.loads(resp["body"])
        self.assertEqual(len(data["thumbnails"]), 1)

    def test_logical_and_between_tags(self):
        # Only second record has both wombat AND koala
        event = make_event(body={"wombat": 1, "koala": 1})
        resp = lambdas.query_by_tags(event, None)
        data = json.loads(resp["body"])
        self.assertEqual(len(data["thumbnails"]), 1)

    def test_empty_body_returns_400(self):
        event = make_event(body={})
        resp = lambdas.query_by_tags(event, None)
        self.assertEqual(resp["statusCode"], 400)

    def test_invalid_count_returns_400(self):
        event = make_event(body={"koala": 0})
        resp = lambdas.query_by_tags(event, None)
        self.assertEqual(resp["statusCode"], 400)

    def test_no_results_returns_empty_lists(self):
        event = make_event(body={"platypus": 99})
        resp = lambdas.query_by_tags(event, None)
        data = json.loads(resp["body"])
        self.assertEqual(data["thumbnails"], [])
        self.assertEqual(data["videos"], [])


class TestQueryByThumbnail(unittest.TestCase):

    def test_valid_thumbnail_returns_full_url(self):
        event = make_event(
            method="GET",
            path="/query/thumbnail",
            query_params={"thumbnail_url": "https://s3.amazonaws.com/bucket/thumbs/koala1.jpg"},
        )
        resp = lambdas.query_by_thumbnail(event, None)
        self.assertEqual(resp["statusCode"], 200)
        data = json.loads(resp["body"])
        self.assertIn("full_url", data)
        self.assertIn("koala1.jpg", data["full_url"])

    def test_missing_param_returns_400(self):
        event = make_event(method="GET", path="/query/thumbnail")
        resp = lambdas.query_by_thumbnail(event, None)
        self.assertEqual(resp["statusCode"], 400)

    def test_unknown_thumbnail_returns_404(self):
        event = make_event(
            method="GET",
            query_params={"thumbnail_url": "https://s3.amazonaws.com/bucket/thumbs/nonexistent.jpg"},
        )
        resp = lambdas.query_by_thumbnail(event, None)
        self.assertEqual(resp["statusCode"], 404)


class TestBulkTagUpdate(unittest.TestCase):

    def setUp(self):
        # Reset mock DB before each test
        lambdas.MOCK_DB = [
            {
                "url": "https://s3.amazonaws.com/bucket/uploads/koala1.jpg",
                "thumbnail_url": "https://s3.amazonaws.com/bucket/thumbs/koala1.jpg",
                "type": "image",
                "tags": {"koala": 3, "eucalyptus": 1},
                "checksum": "abc123",
            },
        ]

    def test_add_tag(self):
        event = make_event(body={
            "urls": ["https://s3.amazonaws.com/bucket/uploads/koala1.jpg"],
            "tags": ["quokka"],
            "operation": 1,
        })
        resp = lambdas.bulk_tag_update(event, None)
        self.assertEqual(resp["statusCode"], 200)
        data = json.loads(resp["body"])
        self.assertEqual(data["updated"], 1)
        self.assertIn("quokka", lambdas.MOCK_DB[0]["tags"])

    def test_remove_tag(self):
        event = make_event(body={
            "urls": ["https://s3.amazonaws.com/bucket/uploads/koala1.jpg"],
            "tags": ["eucalyptus"],
            "operation": 0,
        })
        resp = lambdas.bulk_tag_update(event, None)
        self.assertEqual(resp["statusCode"], 200)
        self.assertNotIn("eucalyptus", lambdas.MOCK_DB[0]["tags"])

    def test_remove_nonexistent_tag_silently_ignored(self):
        event = make_event(body={
            "urls": ["https://s3.amazonaws.com/bucket/uploads/koala1.jpg"],
            "tags": ["dingo"],  # not in this record
            "operation": 0,
        })
        resp = lambdas.bulk_tag_update(event, None)
        # Should still succeed — silent ignore
        self.assertEqual(resp["statusCode"], 200)

    def test_invalid_operation_returns_400(self):
        event = make_event(body={"urls": ["http://x"], "tags": ["koala"], "operation": 2})
        resp = lambdas.bulk_tag_update(event, None)
        self.assertEqual(resp["statusCode"], 400)

    def test_unknown_url_appears_in_skipped(self):
        event = make_event(body={
            "urls": ["https://s3.amazonaws.com/bucket/uploads/unknown.jpg"],
            "tags": ["koala"],
            "operation": 1,
        })
        resp = lambdas.bulk_tag_update(event, None)
        data = json.loads(resp["body"])
        self.assertEqual(data["updated"], 0)
        self.assertEqual(len(data["skipped"]), 1)


class TestDeleteFiles(unittest.TestCase):

    def setUp(self):
        lambdas.MOCK_DB = [
            {
                "url": "https://s3.amazonaws.com/bucket/uploads/koala1.jpg",
                "thumbnail_url": "https://s3.amazonaws.com/bucket/thumbs/koala1.jpg",
                "type": "image",
                "tags": {"koala": 3},
                "checksum": "abc123",
            },
        ]

    def test_delete_existing_file(self):
        event = make_event(
            method="DELETE",
            body={"urls": ["https://s3.amazonaws.com/bucket/uploads/koala1.jpg"]},
        )
        resp = lambdas.delete_files(event, None)
        self.assertEqual(resp["statusCode"], 200)
        data = json.loads(resp["body"])
        self.assertEqual(data["deleted"], 1)
        self.assertEqual(len(lambdas.MOCK_DB), 0)

    def test_delete_nonexistent_file_in_not_found(self):
        event = make_event(
            method="DELETE",
            body={"urls": ["https://s3.amazonaws.com/bucket/uploads/ghost.jpg"]},
        )
        resp = lambdas.delete_files(event, None)
        data = json.loads(resp["body"])
        self.assertEqual(data["deleted"], 0)
        self.assertEqual(len(data["not_found"]), 1)

    def test_empty_urls_returns_400(self):
        event = make_event(method="DELETE", body={"urls": []})
        resp = lambdas.delete_files(event, None)
        self.assertEqual(resp["statusCode"], 400)


class TestTagMatchLogic(unittest.TestCase):
    """Pure logic tests — no DB or AWS involved."""

    def test_all_tags_must_match(self):
        file_tags = {"koala": 3, "wombat": 2}
        self.assertTrue(all(file_tags.get(t, 0) >= c for t, c in {"koala": 3, "wombat": 1}.items()))
        self.assertFalse(all(file_tags.get(t, 0) >= c for t, c in {"koala": 3, "dingo": 1}.items()))

    def test_exact_count_matches(self):
        file_tags = {"koala": 3}
        self.assertTrue(all(file_tags.get(t, 0) >= c for t, c in {"koala": 3}.items()))

    def test_zero_count_file_doesnt_match(self):
        file_tags = {"wombat": 1}
        self.assertFalse(all(file_tags.get(t, 0) >= c for t, c in {"koala": 1}.items()))


class TestRouter(unittest.TestCase):

    def test_unknown_route_returns_404(self):
        event = make_event(method="GET", path="/nonexistent")
        resp = lambdas.handler(event, None)
        self.assertEqual(resp["statusCode"], 404)

    def test_known_route_dispatches(self):
        event = make_event(method="POST", path="/query/tags", body={"koala": 1})
        resp = lambdas.handler(event, None)
        self.assertIn(resp["statusCode"], [200, 400, 500])


if __name__ == "__main__":
    unittest.main()
