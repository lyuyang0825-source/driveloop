import unittest

from driveloop.ngsim import frames_from_rows


def _rows(n=50):
    rows = []
    for i in range(n):
        # ego: 40 ft/s = 43.9 kph，沿 y 正向；actor 从右侧 5m 缓慢并到 0.1m。
        rows.append(
            {
                "frame": 100 + i, "vid": "1", "x": 16.0, "y": 100.0 + i * 4.0,
                "lane": 2, "vel": 40.0, "acc": 0.0, "cls": 2,
            }
        )
        rows.append(
            {
                "frame": 100 + i, "vid": "2", "x": 21.0 - i * 0.1, "y": 128.0 + i * 4.0,
                "lane": 3, "vel": 40.0, "acc": 0.0, "cls": 2,
            }
        )
    return rows


class NgsimConverterTest(unittest.TestCase):
    def test_frames_and_units(self):
        frames = frames_from_rows(_rows(), ego_id="1", duration_s=4.9)
        self.assertEqual(len(frames), 50)
        self.assertAlmostEqual(frames[0].t, 0.0)
        self.assertAlmostEqual(frames[-1].t, 4.9)
        self.assertAlmostEqual(frames[0].speed_kph, 43.89, places=2)
        self.assertEqual(frames[0].accel_long, 0.0)
        self.assertEqual(frames[0].road_type, "highway")
        self.assertEqual(frames[0].speed_limit_kph, 105.0)
        self.assertEqual(frames[0].lane_id, 2)
        self.assertAlmostEqual(frames[0].lane_offset, 0.0)

    def test_object_enters_path(self):
        frames = frames_from_rows(_rows(), ego_id="1", duration_s=4.9)
        first = frames[0].objects[0]
        last = frames[-1].objects[0]
        self.assertEqual(first.id, "2")
        self.assertEqual(first.cls, "car")
        self.assertFalse(first.in_path)
        self.assertGreater(first.lat_m, 4.0)
        self.assertTrue(last.in_path)
        self.assertLess(abs(last.lat_m), 1.0)

    def test_missing_ego_raises(self):
        with self.assertRaises(ValueError):
            frames_from_rows(_rows(), ego_id="99", duration_s=4.9)


if __name__ == "__main__":
    unittest.main()
