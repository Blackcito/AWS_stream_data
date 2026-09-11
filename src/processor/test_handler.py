import unittest
from unittest.mock import Mock

from botocore.exceptions import ClientError

from handler import assess_event, is_duplicate


class DeduplicationTests(unittest.TestCase):
    def test_first_event_is_new(self):
        dynamodb = Mock()

        self.assertFalse(is_duplicate(dynamodb, "dedup-table", "event-1"))
        dynamodb.put_item.assert_called_once()

    def test_conditional_failure_is_duplicate(self):
        error = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "exists"}},
            "PutItem",
        )
        dynamodb = Mock()
        dynamodb.put_item.side_effect = error

        self.assertTrue(is_duplicate(dynamodb, "dedup-table", "event-1"))

    def test_unexpected_dynamodb_error_is_re_raised(self):
        error = ClientError(
            {"Error": {"Code": "InternalServerError", "Message": "temporary"}},
            "PutItem",
        )
        dynamodb = Mock()
        dynamodb.put_item.side_effect = error

        with self.assertRaises(ClientError):
            is_duplicate(dynamodb, "dedup-table", "event-1")


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


if __name__ == "__main__":
    unittest.main()
