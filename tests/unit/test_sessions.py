import unittest
from datetime import timedelta

from src.core.catalogue import Catalogue
from src.core.errors import DomainError
from src.core.settings import ROOT
from src.models.common import utc_now
from src.models.requests import SessionInput
from src.security.sessions import DemoSessions


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.sessions = DemoSessions(Catalogue.load(ROOT).fixtures.accounts)

    def test_normalization_role_binding_and_generic_bad_credentials(self):
        input = SessionInput(role="customer", email=" ALEX@EXAMPLE.TEST ", password="ClientDemo123!")
        session = self.sessions.create(input)
        self.assertEqual(self.sessions.require(session.token).id, "customer-alex")
        failures = []
        for email, password, role in (("alex@example.test", "bad", "customer"), ("alex@example.test", "ClientDemo123!", "reviewer"), ("missing@example.test", "bad", "customer")):
            with self.assertRaises(DomainError) as raised:
                self.sessions.create(SessionInput(role=role, email=email, password=password))
            failures.append((raised.exception.code, raised.exception.message))
        self.assertEqual(len(set(failures)), 1)

    def test_expiration_logout_and_restart(self):
        now = utc_now()
        input = SessionInput(role="customer", email="alex@example.test", password="ClientDemo123!")
        session = self.sessions.create(input, now)
        self.assertEqual(session.expires_at, now + timedelta(hours=8))
        self.sessions.require(session.token, now + timedelta(hours=7))
        with self.assertRaises(DomainError):
            self.sessions.require(session.token, now + timedelta(hours=8))
        session = self.sessions.create(input, now)
        self.sessions.revoke(session.token)
        with self.assertRaises(DomainError):
            self.sessions.require(session.token, now)
        with self.assertRaises(DomainError):
            DemoSessions(self.sessions.accounts).require(session.token, now)