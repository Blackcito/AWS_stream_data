import unittest

from producer import apply_failure_profile, build_events


class FailureProfileTests(unittest.TestCase):
    def setUp(self):
        self.events = build_events(1, ["cutting", "assembly", "inspection"], "test-run")

    def test_run_id_namespaces_piece_ids(self):
        self.assertEqual(self.events[0]["piece_id"], "piece-test-run-0001")

    def test_duplicates_reuse_event_id(self):
        events = apply_failure_profile(self.events, "duplicates")

        self.assertEqual(len(events), 4)
        self.assertEqual(events[0]["event_id"], events[-1]["event_id"])

    def test_out_of_order_keeps_timestamps_but_changes_publication_order(self):
        events = apply_failure_profile(self.events, "out_of_order")

        self.assertEqual([event["station_id"] for event in events], ["cutting", "inspection", "assembly"])
        self.assertEqual(
            {event["event_id"] for event in events},
            {event["event_id"] for event in self.events},
        )

    def test_gaps_omits_assembly_event(self):
        events = apply_failure_profile(self.events, "gaps")

        self.assertEqual(len(events), 2)
        self.assertNotIn("assembly", [event["station_id"] for event in events])


if __name__ == "__main__":
    unittest.main()