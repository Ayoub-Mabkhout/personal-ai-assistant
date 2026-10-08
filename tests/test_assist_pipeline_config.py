"""Native and cached phone selections must not bypass Luna fallback."""
import importlib.util
from pathlib import Path
import unittest

path=Path(__file__).resolve().parents[1]/'scripts/assist_pipeline_config.py'
spec=importlib.util.spec_from_file_location('assist_pipeline_config',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class PipelineRoutingTests(unittest.TestCase):
    def test_native_alternate_pipeline_and_local_preference_cannot_bypass_dispatch(self):
        pipelines=[{'id':'cached-phone-selection','name':'Home Assistant',
                    'conversation_engine':'conversation.home_assistant','prefer_local_intents':True,
                    'language':'de','stt_engine':'stt.existing','tts_voice':'existing-voice'},
                   {'id':'personal','name':'Personal assistant',
                    'conversation_engine':module.DISPATCH_ENGINE,'prefer_local_intents':True},
                   {'id':'separate-agent','conversation_engine':'conversation.other_agent',
                    'prefer_local_intents':True}]
        updates=module.dispatch_updates(pipelines)
        self.assertEqual([u['pipeline_id'] for u in updates],['cached-phone-selection','personal'])
        self.assertEqual(updates[0]['language'],'de')
        self.assertEqual(updates[0]['stt_engine'],'stt.existing')
        self.assertEqual(updates[0]['tts_voice'],'existing-voice')
        for update in updates:
            self.assertEqual(update['conversation_engine'],module.DISPATCH_ENGINE)
            self.assertFalse(update['prefer_local_intents'])
        self.assertTrue(pipelines[0]['prefer_local_intents'])

    def test_reconfiguration_is_idempotent(self):
        self.assertEqual(module.dispatch_updates([{'id':'native','conversation_engine':module.DISPATCH_ENGINE,
                                                  'prefer_local_intents':False}]),[])
