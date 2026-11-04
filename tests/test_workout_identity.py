import hashlib
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch

from personal_assistant.workout.store import Workouts
from personal_assistant.workout.identity import (
    Identity,IdentityError,LoginFailed,EnrollmentDenied,RateLimited,
    normalized_name,b64,hash_auth_secret,verify_auth_secret,AUTH_WINDOW,NAME_ATTEMPTS,
    CLIENT_KDF_VERSION,CLIENT_KDF_ITERATIONS,
)


AUTH=b64(b'a'*32)
OTHER=b64(b'b'*32)
SALT=b64(b'c'*16)
NEW_SALT=b64(b'd'*16)


class WorkoutIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.now=1900000000
        self.workouts=Workouts(Path(self.temp.name)/'workouts.sqlite3',clock=lambda:self.now)
        # The identity seam deliberately does not create or migrate Accounts tables.
        with self.workouts.db() as db:
            db.executescript('''CREATE TABLE train_users(id TEXT PRIMARY KEY,name TEXT NOT NULL,setup_complete INTEGER DEFAULT 1);
                CREATE TABLE train_sessions(hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires REAL NOT NULL);''')
        self.identity=Identity(self.workouts)

    def profile(self,identifier,name):
        with self.workouts.db() as db:db.execute('INSERT INTO train_users(id,name) VALUES(?,?)',(identifier,name))

    def session(self,identifier,*,expires=None):
        token=secrets.token_urlsafe(32)
        with self.workouts.db() as db:
            db.execute('INSERT INTO train_sessions VALUES(?,?,?)',
                (hashlib.sha256(token.encode()).hexdigest(),identifier,self.now+3600 if expires is None else expires))
        return token

    def test_memory_hard_verifier_has_unique_salt_and_constant_comparison(self):
        first,second=hash_auth_secret(AUTH),hash_auth_secret(AUTH)
        self.assertNotEqual(first,second);self.assertTrue(first.startswith('scrypt$v1$32768$8$3$'))
        self.assertNotIn(AUTH,first)
        self.assertTrue(verify_auth_secret(AUTH,first));self.assertFalse(verify_auth_secret(OTHER,first))
        self.assertFalse(verify_auth_secret(AUTH,'scrypt$v2$malformed'))

    def test_auth_material_is_canonical_base64url_not_raw_password(self):
        for invalid in ('a normal password',AUTH+'=',AUTH[:-1]+'!',None,'x'*5000):
            with self.subTest(value=invalid),self.assertRaises(IdentityError):hash_auth_secret(invalid)
        with self.assertRaises(IdentityError):self.identity.register('New User',AUTH,'invalid-salt','client-one')

    def test_normalized_name_supports_unicode_and_rejects_control_characters(self):
        self.assertEqual(normalized_name('  Ａlex   SMITH '),('Alex SMITH','alex smith'))
        self.assertEqual(normalized_name('Straße')[1],normalized_name('STRASSE')[1])
        for name in ('','\u200bname','x'*81,None):
            with self.subTest(name=name),self.assertRaises(IdentityError):normalized_name(name)

    def test_new_registration_and_login_have_no_plaintext_secret_storage(self):
        identifier=self.identity.register('Alex Smith',AUTH,SALT,'client-one')
        self.assertEqual(self.identity.login('  ＡLEX smith ',AUTH,'client-one'),identifier)
        with self.workouts.db() as db:
            row=dict(db.execute('SELECT * FROM train_credentials').fetchone())
            profile=db.execute('SELECT * FROM train_users WHERE id=?',(identifier,)).fetchone()
        self.assertEqual(profile['setup_complete'],0)
        self.assertEqual(row['login_name'],'alex smith');self.assertNotIn(AUTH,str(row))
        parameters=self.identity.parameters('Alex Smith')
        self.assertEqual(parameters,{'version':CLIENT_KDF_VERSION,'kdf':'PBKDF2','hash':'SHA-256',
            'iterations':CLIENT_KDF_ITERATIONS,'salt':SALT})
        self.assertEqual(set(self.identity.parameters('Unknown Person')),set(parameters))

    def test_existing_name_cannot_be_taken_by_registration_or_first_password(self):
        self.profile('existing','Alex Smith')
        with self.assertRaises(EnrollmentDenied):self.identity.register('ＡLEX smith',AUTH,SALT,'client-one')
        self.profile('another','Sam Jones');wrong=self.session('another')
        with self.assertRaises(EnrollmentDenied):self.identity.claim('Alex Smith',AUTH,SALT,wrong,'client-one')
        with self.workouts.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM train_credentials').fetchone()[0],0)

    def test_expired_session_cannot_claim_existing_profile(self):
        self.profile('existing','Alex Smith');expired=self.session('existing',expires=self.now)
        with self.assertRaises(EnrollmentDenied):self.identity.claim('Alex Smith',AUTH,SALT,expired,'client-one')

    def test_exact_prior_session_claim_revokes_all_previous_sessions(self):
        self.profile('existing','Alex Smith');old=self.session('existing');self.session('existing')
        self.profile('another','Sam Jones');other=self.session('another')
        seen=[]
        identifier=self.identity.claim('alex smith',AUTH,SALT,old,'client-one',on_enroll=lambda db,user:seen.append(user))
        self.assertEqual(identifier,'existing');self.assertEqual(seen,['existing'])
        with self.workouts.db() as db:
            rows=db.execute('SELECT user_id FROM train_sessions').fetchall()
        self.assertEqual([row['user_id'] for row in rows],['another'])
        self.assertEqual(self.identity.login('Alex Smith',AUTH,'client-one'),'existing')
        with self.assertRaises(EnrollmentDenied):self.identity.claim('Alex Smith',OTHER,NEW_SALT,self.session('existing'),'client-one')
        self.assertEqual(self.identity.login('Alex Smith',AUTH,'client-one'),'existing')

    def test_legacy_normalization_collision_requires_resolution_not_arbitrary_claim(self):
        self.profile('first','Alex Smith');self.profile('second','Ａlex Smith')
        with self.assertRaises(EnrollmentDenied):
            self.identity.claim('Alex Smith',AUTH,SALT,self.session('first'),'client-one')

    def test_unknown_user_and_wrong_secret_have_same_error_and_both_run_verifier(self):
        self.identity.register('Alex Smith',AUTH,SALT,'client-one')
        errors=[]
        with patch('personal_assistant.workout.identity._derive',return_value=b'z'*32) as derive:
            for name in ('Alex Smith','Unknown User'):
                with self.assertRaises(LoginFailed) as caught:self.identity.login(name,OTHER,'client-one')
                errors.append(str(caught.exception))
            self.assertEqual(derive.call_count,2)
        self.assertEqual(errors[0],errors[1])

    def test_persistent_rate_limit_precedes_expensive_verification(self):
        with patch('personal_assistant.workout.identity._derive',return_value=b'z'*32) as derive:
            for _ in range(NAME_ATTEMPTS):
                with self.assertRaises(LoginFailed):self.identity.login('Unknown User',AUTH,'client-one')
            reopened=Identity(self.workouts)
            with self.assertRaises(RateLimited) as caught:reopened.login('Unknown User',AUTH,'another-client')
            self.assertEqual(caught.exception.retry_after,AUTH_WINDOW)
            self.assertEqual(derive.call_count,NAME_ATTEMPTS)
            self.now+=AUTH_WINDOW+1
            with self.assertRaises(LoginFailed):reopened.login('Unknown User',AUTH,'client-one')
            self.assertEqual(derive.call_count,NAME_ATTEMPTS+1)

    def test_password_change_revokes_sessions_and_updates_client_salt(self):
        identifier=self.identity.register('Alex Smith',AUTH,SALT,'client-one');self.session(identifier)
        self.identity.change_secret(identifier,AUTH,OTHER,NEW_SALT,'client-one')
        with self.workouts.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM train_sessions').fetchone()[0],0)
        self.assertEqual(self.identity.login('Alex Smith',OTHER,'client-one'),identifier)
        with self.assertRaises(LoginFailed):self.identity.login('Alex Smith',AUTH,'client-one')
        self.assertEqual(self.identity.parameters('Alex Smith')['salt'],NEW_SALT)

    def test_revoke_all_invalidates_racing_verified_login_before_session_issue(self):
        identifier=self.identity.register('Alex Smith',AUTH,SALT,'client-one');issued=[]
        original=verify_auth_secret
        def race(secret,verifier):
            valid=original(secret,verifier);self.identity.revoke_all(identifier);return valid
        with patch('personal_assistant.workout.identity.verify_auth_secret',side_effect=race):
            with self.assertRaises(LoginFailed):
                self.identity.login('Alex Smith',AUTH,'client-one',on_login=lambda db,user:issued.append(user))
        self.assertEqual(issued,[])

    def test_enrollment_callback_failure_rolls_back_profile_credentials_and_vault_write(self):
        def fail(db,identifier):
            db.execute("CREATE TABLE enrollment_fixture(user_id TEXT)")
            db.execute('INSERT INTO enrollment_fixture VALUES(?)',(identifier,))
            raise ValueError('Fixture callback failed')
        with self.assertRaisesRegex(ValueError,'Fixture callback failed'):
            self.identity.register('Alex Smith',AUTH,SALT,'client-one',on_enroll=fail)
        with self.workouts.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM train_users').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM train_credentials').fetchone()[0],0)

    def test_logout_revokes_only_selected_session(self):
        self.profile('existing','Alex Smith');one=self.session('existing');two=self.session('existing')
        self.identity.revoke(one)
        with self.workouts.db() as db:
            rows=db.execute('SELECT hash FROM train_sessions').fetchall()
        self.assertEqual([row['hash'] for row in rows],[hashlib.sha256(two.encode()).hexdigest()])


if __name__=='__main__':unittest.main()
