import importlib.util
from pathlib import Path
import unittest

path=Path(__file__).resolve().parents[1]/'integrations/home_assistant/custom_components/assistant_dispatch/routing.py'
spec=importlib.util.spec_from_file_location('dispatch_routing',path)
routing=importlib.util.module_from_spec(spec);spec.loader.exec_module(routing)


class RoutingTests(unittest.TestCase):
    def test_unmatched_speech_or_targets_fall_through(self):
        self.assertTrue(routing.should_dispatch('no_intent_match'))
        self.assertTrue(routing.should_dispatch('no_valid_targets'))
        for error in (None,'unknown','failed_to_handle','no_area','no_device'):
            self.assertFalse(routing.should_dispatch(error))
    def test_no_replay_after_attempted_programmed_actions(self):
        self.assertFalse(routing.should_dispatch('no_valid_targets',success_results=['already_done']))
        self.assertFalse(routing.should_dispatch('no_valid_targets',failed_results=['already_attempted']))
    def test_offline_ack_is_saved_not_executed(self):
        body={'job':{'id':'test-request-abcdefgh','state':'queued'},'connection':{'laptop':'unavailable'},'notifications':{'enabled':True}}
        message=routing.acknowledgement(body)
        self.assertIn('Waiting for the laptop',message);self.assertIn('phone',message);self.assertNotIn('completed',message)
