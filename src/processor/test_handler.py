import base64
import json
import os
import unittest
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError

from handler import assess_event, lambda_handler, record_event


def make_kinesis_record(event):
    return {
        "kinesis": {
            "data": base64.b64encode(json.dumps(event).encode("utf-8")).decode("utf-8"),
        }
    }


def make_event(event_id="evt-1", station_id="cutting"):
    return {
        "event_id": event_id,
        "piece_id": "piece-1",
        "station_id": station_id,
        "event_type": "station_completed",
        "event_timestamp": "2026-09-08T10:00:00Z",
        "cycle_time_seconds": 3.0,
    }


class RecordEventTests(unittest.TestCase):
    def test_new_event_is_processed(self):
        dynamodb = Mock()
        dynamodb.transact_write_items.return_value = {}

        result = record_event(dynamodb, "dedup-table", "corr-table", make_event(), "ok")

        self.assertEqual(result, "processed")
        dynamodb.transact_write_items.assert_called_once()

    def test_ok_event_writes_dedup_and_state(self):
        dynamodb = Mock()
        dynamodb.transact_write_items.return_value = {}

        record_event(dynamodb, "dedup-table", "corr-table", make_event(), "ok")

        items = dynamodb.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual(len(items), 2)
        self.assertIn("Put", items[0])
        self.assertIn("Update", items[1])

    def test_out_of_order_event_only_writes_dedup(self):
        dynamodb = Mock()
        dynamodb.transact_write_items.return_value = {}

        record_event(dynamodb, "dedup-table", "corr-table", make_event(), "out_of_order")

        items = dynamodb.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual(len(items), 1)
        self.assertIn("Put", items[0])

    def test_duplicate_cancels_transaction(self):
        error = ClientError(
            {
                "Error": {"Code": "TransactionCanceledException", "Message": "cancelled"},
                "CancellationReasons": [
                    {"Code": "ConditionalCheckFailed", "Message": "exists"},
                    {"Code": "None"},
                ],
            },
            "TransactWriteItems",
        )
        dynamodb = Mock()
        dynamodb.transact_write_items.side_effect = error

        result = record_event(dynamodb, "dedup-table", "corr-table", make_event(), "ok")

        self.assertEqual(result, "duplicate")

    def test_unexpected_error_is_re_raised(self):
        error = ClientError(
            {"Error": {"Code": "InternalServerError", "Message": "temporary"}},
            "TransactWriteItems",
        )
        dynamodb = Mock()
        dynamodb.transact_write_items.side_effect = error

        with self.assertRaises(ClientError):
            record_event(dynamodb, "dedup-table", "corr-table", make_event(), "ok")


class EventQualityTests(unittest.TestCase):
    def test_missing_previous_station_is_gap(self):
        dynamodb = Mock()
        dynamodb.query.return_value = {
            "Items": [{"station_id": {"S": "cutting"}, "event_timestamp": {"S": "2026-09-08T10:00:00Z"}}]
        }
        event = {"piece_id": "piece-1", "station_id": "inspection", "event_timestamp": "2026-09-08T10:00:06Z"}

        status, missing = assess_event(
            dynamodb, "correlation-table", event, ("cutting", "assembly", "inspection")
        )

        self.assertEqual(status, "gap")
        self.assertEqual(missing, ["assembly"])

    def test_older_event_is_out_of_order(self):
        dynamodb = Mock()
        dynamodb.query.return_value = {
            "Items": [
                {"station_id": {"S": "cutting"}, "event_timestamp": {"S": "2026-09-08T10:00:00Z"}},
                {"station_id": {"S": "inspection"}, "event_timestamp": {"S": "2026-09-08T10:00:06Z"}},
            ]
        }
        event = {"piece_id": "piece-1", "station_id": "assembly", "event_timestamp": "2026-09-08T10:00:03Z"}

        status, missing = assess_event(
            dynamodb, "correlation-table", event, ("cutting", "assembly", "inspection")
        )

        self.assertEqual(status, "out_of_order")
        self.assertEqual(missing, [])

    def test_unknown_station_does_not_report_false_gaps(self):
        dynamodb = Mock()
        dynamodb.query.return_value = {"Items": []}
        event = {"piece_id": "piece-1", "station_id": "unknown", "event_timestamp": "2026-09-08T10:00:00Z"}

        status, missing = assess_event(
            dynamodb, "correlation-table", event, ("cutting", "assembly", "inspection")
        )

        self.assertEqual(status, "ok")
        self.assertEqual(missing, [])


class LambdaHandlerTests(unittest.TestCase):
    def setUp(self):
        os.environ["DEDUPLICATION_TABLE"] = "dedup-table"
        os.environ["CORRELATION_TABLE"] = "correlation-table"
        os.environ["DATA_LAKE_BUCKET"] = "data-lake"
        os.environ.pop("STATION_ORDER", None)

        self.dynamodb = Mock()
        self.s3 = Mock()
        self.dynamodb.transact_write_items.return_value = {}
        self.dynamodb.query.return_value = {"Items": []}

    def _invoke(self, event):
        with patch("handler.boto3.client", side_effect=[self.dynamodb, self.s3]):
            return lambda_handler({"Records": [make_kinesis_record(event)]}, None)

    def test_new_event_persists_and_updates_state(self):
        result = self._invoke(make_event())

        self.assertEqual(result, {"processed": 1, "duplicates": 0, "out_of_order": 0, "gaps": 0})
        self.assertEqual(self.s3.put_object.call_count, 2)
        self.dynamodb.transact_write_items.assert_called_once()

    def test_duplicate_cancels_transaction(self):
        error = ClientError(
            {
                "Error": {"Code": "TransactionCanceledException", "Message": "cancelled"},
                "CancellationReasons": [{"Code": "ConditionalCheckFailed", "Message": "exists"}],
            },
            "TransactWriteItems",
        )
        self.dynamodb.transact_write_items.side_effect = error

        result = self._invoke(make_event("evt-dup"))

        self.assertEqual(result, {"processed": 0, "duplicates": 1, "out_of_order": 0, "gaps": 0})
        self.dynamodb.transact_write_items.assert_called_once()


if __name__ == "__main__":
    unittest.main()
