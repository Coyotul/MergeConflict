import unittest

from scripts.backend_smoke import smoke


class BackendLiveHttpTests(unittest.TestCase):
    def test_authenticated_synthetic_journey_over_live_uvicorn(self):
        result = smoke()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["checks"], 22)
        self.assertFalse(result["signed"])
        self.assertFalse(result["funded"])