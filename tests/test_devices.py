import unittest

from liora.devices import recommend


class RecommendTests(unittest.TestCase):
    def test_cpu_stays_on_small(self):
        model, allow, notes = recommend(None, "cpu", False)
        self.assertEqual(model, "small-music")
        self.assertFalse(allow)
        self.assertTrue(notes)

    def test_eight_gb_without_flash_defaults_small_but_can_try(self):
        model, allow, _notes = recommend(8.0, "zluda", False)
        self.assertEqual(model, "small-music")
        self.assertTrue(allow)

    def test_eight_gb_with_flash_uses_medium(self):
        model, allow, notes = recommend(8.0, "rocm", True)
        self.assertEqual(model, "medium")
        self.assertTrue(allow)
        self.assertTrue(any("chunked" in note.lower() for note in notes))

    def test_tiny_gpu_refuses_medium(self):
        _model, allow, _notes = recommend(4.0, "cuda", True)
        self.assertFalse(allow)


if __name__ == "__main__":
    unittest.main()
