"""Code-side routing: explicit model requests, mail tools, then account choice from allowance and reset timing."""
import unittest

from personal_assistant.orchestrator.jev import PROFILES
from personal_assistant.orchestrator.routing_policy import account_score, explicit_preferences, select

NOW = 1_800_000_000


def capacity(codex=None, claude=None):
    return {name:{'five_hour':{'remaining_percent':value[0]},'weekly':{'remaining_percent':value[1]}}
            for name,value in (('codex',codex),('claude',claude)) if value is not None}


def route(text, **body):
    return select({'user_request':text,**body},PROFILES,now=NOW)


class ExplicitRequestTests(unittest.TestCase):
    def prefs(self, text):
        return explicit_preferences(text,PROFILES)[0]

    def test_direct_requests_in_several_phrasings(self):
        for text,expected in (('Use Opus for this',{'agent':'claude','model':'claude-opus-5-5'}),
                              ('Please route this to Sonnet 5.5',{'agent':'claude','model':'claude-sonnet-5-5'}),
                              ('model: gpt-6-astra',{'agent':'codex','model':'gpt-6-astra'}),
                              ('Run this with Claude',{'agent':'claude'}),
                              ('let codex handle it',{'agent':'codex'}),
                              ('Have Sonnet do this: compare two apps',{'agent':'claude','model':'claude-sonnet-5-5'}),
                              ('Get Opus to write the toast',{'agent':'claude','model':'claude-opus-5-5'}),
                              ('ask haiku to summarise it',{'agent':'claude','model':'claude-haiku-5-5'})):
            with self.subTest(text=text):
                self.assertEqual(self.prefs(text),expected)

    def test_effort_is_read_with_or_without_a_model(self):
        self.assertEqual(self.prefs('Use Sol at high effort'),{'agent':'codex','model':'gpt-6.1-sol','effort':'high'})
        self.assertEqual(self.prefs('reasoning effort: extra high'),{'effort':'xhigh'})

    def test_mentions_that_are_not_requests_are_ignored(self):
        for text in ('What is the difference between Opus and Sol?','Should I use Haiku for this?','I have Claude on my phone',
                     'Did you get Sonnet tickets?',
                     'Summarise the "use Opus" section of the doc','> use claude\nfix the typo','Opus is a nice word'):
            with self.subTest(text=text):
                self.assertEqual(self.prefs(text),{})

    def test_negation_excludes_instead_of_selecting(self):
        self.assertEqual(self.prefs("Don't use Claude for this"),{'excluded_agents':['claude']})

    def test_conflicts_and_unknown_versions_are_refused(self):
        with self.assertRaisesRegex(ValueError,'Conflicting'):self.prefs('Use Opus or Sonnet')
        with self.assertRaisesRegex(ValueError,'not in the configured catalog'):self.prefs('Use Opus 9.9')
        with self.assertRaisesRegex(ValueError,'conflict'):self.prefs('Use codex, model: claude-opus-5-5')


class AccountChoiceTests(unittest.TestCase):
    def test_more_headroom_wins(self):
        self.assertEqual(route('Summarise this page',agent_capacity=capacity((12,55),(80,75)))['agent'],'claude')
        self.assertEqual(route('Summarise this page',agent_capacity=capacity((80,75),(12,55)))['agent'],'codex')

    def test_an_imminent_reset_makes_spare_allowance_worth_spending(self):
        soon={'codex':{'five_hour':{'remaining_percent':40,'resets_in_minutes':5},'weekly':{'remaining_percent':60}},
              'claude':{'five_hour':{'remaining_percent':45,'resets_in_minutes':240},'weekly':{'remaining_percent':60}}}
        self.assertGreater(account_score(soon['codex'],None,now=NOW),account_score(soon['claude'],None,now=NOW))
        self.assertEqual(route('Summarise this page',agent_capacity=soon)['agent'],'codex')

    def test_exhausted_or_unusable_accounts_are_skipped(self):
        self.assertIsNone(account_score({'five_hour':{'remaining_percent':0}},None,now=NOW))
        self.assertIsNone(account_score({},{'usable':False},now=NOW))
        self.assertEqual(route('Summarise',agent_capacity=capacity((0,50),(10,10)))['agent'],'claude')
        with self.assertRaisesRegex(ValueError,'No allowed agent'):
            route('Summarise',agent_availability={'codex':False,'claude':False})

    def test_a_stale_low_reading_still_counts_against_its_account(self):
        # Shape of a real snapshot: Codex read at 1% hours ago with its window still running; Claude's window reset since.
        codex={'five_hour':{'remaining_percent':1,'resets_in_minutes':84},'weekly':{'remaining_percent':84},'observed_minutes_ago':140}
        claude={'five_hour':{'remaining_percent':100,'reset_since_observed':True},'weekly':{'remaining_percent':44},'observed_minutes_ago':219}
        self.assertEqual(route('Summarise this page',agent_capacity={'codex':codex,'claude':claude})['agent'],'claude')

    def test_stale_readings_count_as_unknown_not_full(self):
        stale={'five_hour':{'remaining_percent':100},'weekly':{'remaining_percent':100},'observed_minutes_ago':180}
        self.assertLess(account_score(stale,None,now=NOW),account_score(capacity((60,60))['codex'],None,now=NOW))

    def test_explicit_request_beats_allowance_and_limits_profiles(self):
        result=route('Use Opus for this poem',agent_capacity=capacity((95,95),(10,40)))
        self.assertEqual((result['agent'],result['reason']),('claude','explicit_preference'))
        self.assertEqual({p['model'] for p in result['profiles'].values()},{'claude-opus-5-5'})

    def test_mail_pins_codex(self):
        result=route('Check my inbox for the rent email',agent_capacity=capacity((5,20),(95,95)))
        self.assertEqual((result['agent'],result['reason']),('codex','mail_tools'))
        self.assertEqual(route('Write an email-style apology',agent_capacity=capacity((5,20),(95,95)))['agent'],'claude')

    def test_selected_profiles_belong_to_one_account(self):
        result=route('Plan my afternoon in Regensburg',agent_capacity=capacity((30,30),(70,70)))
        self.assertEqual({p['agent'] for p in result['profiles'].values()},{'claude'})


if __name__ == '__main__':
    unittest.main()
