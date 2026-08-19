import os
import base64
import hashlib
from cryptography.fernet import Fernet

class CredentialEncrypter:
    def __init__(self):
        raw_key = os.getenv("ENCRYPTION_KEY", "silvia_default_encryption_secret_key_123456789")
        # Deriving a valid Fernet key from any arbitrary length secret key using SHA-256
        key_hash = hashlib.sha256(raw_key.encode('utf-8')).digest()
        fernet_key = base64.urlsafe_b64encode(key_hash)
        self.cipher = Fernet(fernet_key)

    def encrypt(self, plain_text: str) -> str:
        if not plain_text:
            return ""
        return self.cipher.encrypt(plain_text.encode('utf-8')).decode('utf-8')

    def decrypt(self, encrypted_text: str) -> str:
        if not encrypted_text:
            return ""
        try:
            return self.cipher.decrypt(encrypted_text.encode('utf-8')).decode('utf-8')
        except Exception as e:
            print(f"[Decryption Error]: Failed to decrypt credential: {e}")
            return ""

outreach_crypto = CredentialEncrypter()
