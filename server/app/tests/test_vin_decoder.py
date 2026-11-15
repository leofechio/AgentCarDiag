import unittest
from unittest.mock import patch

from app.vin_decoder import VinDecoderService


class TestVinDecoderValidation(unittest.TestCase):
    def setUp(self):
        self.decoder = VinDecoderService()

    @patch("app.vin_decoder.urllib.request.urlopen")
    def test_rejects_vin_longer_than_17_characters(self, urlopen):
        result = self.decoder.decode("VF1FL000000000000X")

        self.assertFalse(result["valid"])
        self.assertIn("comprimento 18", result["error"])
        urlopen.assert_not_called()

    @patch("app.vin_decoder.urllib.request.urlopen")
    def test_rejects_forbidden_vin_characters(self, urlopen):
        result = self.decoder.decode("VF1FL00000000000I")

        self.assertFalse(result["valid"])
        self.assertIn("I, O e Q", result["error"])
        urlopen.assert_not_called()

    @patch("app.vin_decoder.urllib.request.urlopen", side_effect=OSError("offline"))
    def test_cached_result_isolated_from_caller_mutations(self, urlopen):
        vin = "VF1FL000000000000"
        first_result = self.decoder.decode(vin)
        first_result["make"] = "Alterado pelo chamador"
        first_result["recommended_steps"][0]["query"] = "MUTATED"

        cached_result = self.decoder.decode(vin)

        self.assertEqual(cached_result["make"], "Renault")
        self.assertNotEqual(cached_result["recommended_steps"][0]["query"], "MUTATED")
        urlopen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
