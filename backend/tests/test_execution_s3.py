from __future__ import annotations

import io
import os
import unittest
from unittest.mock import patch

from app import execution


class _Paginator:
    def __init__(self, client):
        self.client = client

    def paginate(self, Bucket, Prefix):
        contents = [{"Key": key} for key in self.client.objects if key.startswith(Prefix)]
        return [{"Contents": contents}]


class _MemoryS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType, Metadata):
        self.objects[Key] = {
            "body": bytes(Body),
            "metadata": dict(Metadata),
            "content_type": ContentType,
        }

    def get_object(self, Bucket, Key):
        item = self.objects[Key]
        return {"Body": io.BytesIO(item["body"]), "Metadata": item["metadata"]}

    def delete_objects(self, Bucket, Delete):
        for item in Delete["Objects"]:
            self.objects.pop(item["Key"], None)

    def get_paginator(self, operation):
        if operation != "list_objects_v2":
            raise AssertionError(operation)
        return _Paginator(self)


class S3ExecutionStorageTests(unittest.TestCase):
    def setUp(self):
        self.client = _MemoryS3()
        self.env = patch.dict(os.environ, {
            "AGENTHQ_WORKSPACE_STORAGE": "s3",
            "AWS_S3_BUCKET": "agenthq-test",
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
            "AWS_REGION": "ap-southeast-1",
            "AWS_ENDPOINT_URL_S3": "https://s3.example.test",
        })
        self.env.start()
        self.client_patch = patch("boto3.client", return_value=self.client)
        self.client_patch.start()

    def tearDown(self):
        self.client_patch.stop()
        self.env.stop()

    def test_writes_pending_artifacts_and_reads_them_back(self):
        manifest = execution.write_draft_artifacts(
            "exec-s3-001",
            [{"path": "docs/plan.md", "content": "# Durable plan\\n"}],
        )
        self.assertEqual(manifest[0]["path"], "docs/plan.md")
        payload = execution.read_artifact_bytes(
            "exec-s3-001", "docs/plan.md", manifest, approved=False
        )
        self.assertEqual(payload, b"# Durable plan\\n")
        key = "agenthq/executions/pending/exec-s3-001/docs/plan.md"
        self.assertIn(key, self.client.objects)
        self.assertNotIn("ACL", self.client.objects[key])

    def test_approval_copies_to_approved_prefix_and_cleanup_removes_objects(self):
        manifest = execution.write_draft_artifacts(
            "exec-s3-002",
            [{"path": "README.md", "content": "# Approved\\n"}],
        )
        execution.publish_approved_artifacts("exec-s3-002", manifest)
        payload = execution.read_artifact_bytes(
            "exec-s3-002", "README.md", manifest, approved=True
        )
        self.assertEqual(payload, b"# Approved\\n")
        execution.remove_approved_workspace("exec-s3-002")
        self.assertFalse(any("/approved/exec-s3-002/" in key for key in self.client.objects))
        execution.remove_draft_workspace("exec-s3-002")
        self.assertFalse(any("/pending/exec-s3-002/" in key for key in self.client.objects))

    def test_storage_fails_closed_when_credentials_are_missing(self):
        with patch.dict(os.environ, {"AWS_SECRET_ACCESS_KEY": ""}):
            with self.assertRaises(execution.ArtifactValidationError):
                execution.write_draft_artifacts(
                    "exec-s3-003",
                    [{"path": "README.md", "content": "x"}],
                )


if __name__ == "__main__":
    unittest.main()
