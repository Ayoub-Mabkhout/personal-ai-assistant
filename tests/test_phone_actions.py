import argparse
import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location('phone_actions_cli', Path(__file__).resolve().parents[1]/'scripts/phone_actions.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PhoneActionTests(unittest.TestCase):
    def test_alarm_selects_only_active_phone_and_retries_keep_id(self):
        class Client:
            def __init__(self): self.calls = []
            def call(self, path, body=None):
                self.calls.append((path, body))
                if path.endswith('/phones'):
                    return [{'id':'phone-active-123','revoked':0},{'id':'phone-revoked-456','revoked':1}]
                return {'id':body['id'],'state':'queued','clock_registration_verified':False}
        client = Client()
        args = module.parser().parse_args(['alarm','--id','alarm-stable-123','--time','07:30','--label','Morning'])
        first = module.execute(args, client)
        second = module.execute(args, client)
        writes = [body for path,body in client.calls if path.endswith('/alarms')]
        self.assertEqual(writes,[{'id':'alarm-stable-123','phone':'phone-active-123','hour':7,'minute':30,'label':'Morning','launch':False}]*2)
        self.assertEqual(first,second)
        self.assertFalse(first['clock_registration_verified'])

    def test_no_phone_multiple_phones_and_revoked_selection_require_resolution(self):
        for phones, requested in (([],None),([{'id':'phone-one-123'},{'id':'phone-two-456'}],None),
                                  ([{'id':'phone-old-123','revoked':1}],'phone-old-123')):
            with self.subTest(phones=phones), self.assertRaises(ValueError):
                module.select_phone(phones,requested)
        self.assertEqual(module.select_phone([{'id':'phone-one-123'},{'id':'phone-two-456'}],'phone-two-456'),'phone-two-456')

    def test_time_requires_unambiguous_24_hour_value(self):
        self.assertEqual(module.clock_time('23:59'),(23,59))
        for value in ('24:00','12:60','7:30','7pm','-1:00','07:30 tomorrow'):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                module.clock_time(value)

    def test_read_actions_do_not_write_or_read_device_credentials(self):
        class Client:
            def __init__(self): self.calls=[]
            def call(self,path,body=None): self.calls.append((path,body)); return {'state':'delegated','clock_registration_verified':False}
        client=Client()
        module.execute(module.parser().parse_args(['phones']),client)
        result=module.execute(module.parser().parse_args(['status','alarm-stable-123']),client)
        self.assertEqual(client.calls,[(module.BASE+'phones',None),(module.BASE+'alarms/alarm-stable-123',None)])
        self.assertFalse(result['clock_registration_verified'])


if __name__=='__main__':
    unittest.main()
