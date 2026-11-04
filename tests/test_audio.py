import unittest

import numpy as np

from liora.audio_io import to_stereo


class AudioTests(unittest.TestCase):
    def test_channels_first(self):
        audio = np.ones((2, 8), dtype=np.float32)
        stereo = to_stereo(audio)
        self.assertEqual(stereo.shape, (8, 2))

    def test_batch(self):
        audio = np.zeros((1, 2, 4), dtype=np.float32)
        stereo = to_stereo(audio)
        self.assertEqual(stereo.shape, (4, 2))


if __name__ == "__main__":
    unittest.main()
