"""Standard-library-only password records for private host bootstrap."""
import hashlib
import secrets


def password_record(username, password):
    if not isinstance(username,str) or not 0 < len(username) <= 200 or not isinstance(password,str) or not 12 <= len(password) <= 1000:
        raise ValueError('Use a username and a password of 12 to 1000 characters.')
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return {'username': username, 'salt': salt.hex(), 'password_hash': digest.hex()}
