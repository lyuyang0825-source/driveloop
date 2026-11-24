import csv
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from driveloop.cli import mine
from driveloop.detect import cluster_scenes, detect_events
from driveloop.regression import compare_runs, gate
from driveloop.scenario import build_cards, to_osc
from driveloop.schema import CSV_FIELDS, Frame, load_csv, write_csv
from driveloop.synth import generate, make_log


class TestSchema(unittest.TestCase):
    def test_roundtrip(self):
        frames = [
            Frame(
                t=0.0, speed_kph=36.0, accel_long=0.0, accel_lat=0.0, steer_deg=0.0,
                brake=0.0, throttle=0.0, lane_id=-1, lane_offset=0.0,
                weather="clear", visibility_m=800.0, road_type="urban",
                speed_limit_kph=50.0, driver_state="engaged", objects=[],
            )
        ]
        with tempfile.TemporaryDirectory() as d:
            p = write_csv(frames, Path(d) / "x.csv")
            back = load_csv(p)
            self.assertEqual(len(back), 1)
            self.assertEqual(back[0].speed_kph, 36.0)
            with p.open(newline="", encoding="utf-8") as f:
                header = next(csv.reader(f))
            self.assertEqual(header, CSV_FIELDS)


class TestSynth(unittest.TestCase):
    def test_profile_has_expected_moments(self):
        frames = make_log()
        self.assertEqual(len(frames), 901)
        self.assertAlmostEqual(frames[1].t - frames[0].t, 0.1, places=3)
        hard = [f for f in frames if f.accel_long <= -6.0]
        self.assertTrue(hard, "应存在急刹帧")
        fog = [f for f in frames if f.weather == "fog"]
        self.assertTrue(fog and fog[0].visibility_m <= 30)
        takeover = [f for f in frames if f.driver_state != "engaged"]
        self.assertTrue(takeover)


class TestDetect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = make_log()
        cls.events = detect_events(cls.frames)
        cls.scenes = cluster_scenes(cls.events, cls.frames)
        cls.cards = build_cards(cls.scenes)

    def test_event_types(self):
        types = {e.type for e in self.events}
        for t in ["cut_in", "vru_sudden", "near_miss", "hard_brake", "takeover", "low_visibility", "construction"]:
            self.assertIn(t, types)

    def test_scene_clustering(self):
        self.assertGreaterEqual(len(self.scenes), 5)
        self.assertEqual([s.id for s in self.scenes], [f"SC-{i:03d}" for i in range(1, len(self.scenes) + 1)])
        for s in self.scenes:
            self.assertLessEqual(s.risk, 100)
            self.assertGreaterEqual(s.risk, 0)
            self.assertIn(s.severity, {"low", "medium", "high"})
            self.assertLessEqual(s.start, s.end)

    def test_near_miss_threshold(self):
        nm = [e for e in self.events if e.type == "near_miss"]
        self.assertTrue(nm)
        self.assertLess(min(e.detail["ttc_s"] for e in nm), 4.0)

    def test_hard_brake_value(self):
        hb = [e for e in self.events if e.type == "hard_brake"]
        self.assertTrue(hb)
        self.assertLessEqual(min(e.detail["accel_mps2"] for e in hb), -8.0)


class TestScenario(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards = build_cards(cluster_scenes(detect_events(make_log()), make_log()))

    def test_card_fields(self):
        for c in self.cards:
            for key in ["scenario_id", "title", "types", "time_window", "risk", "trigger", "suggested_labels", "regression_assertions"]:
                self.assertIn(key, c)
            self.assertTrue(c["suggested_labels"])
            self.assertTrue(c["regression_assertions"])

    def test_osc_is_valid_xml(self):
        xml = to_osc(self.cards[0])
        root = ET.fromstring(xml)
        self.assertEqual(root.tag, "OpenSCENARIO")


class TestRegression(unittest.TestCase):
    def _run(self, ttc, decel, collision=False, interventions=0):
        return {"id": "SC-001", "min_ttc": ttc, "max_decel": decel,
                "collision": collision, "interventions": interventions}

    def test_identical_passes(self):
        base = {"scenarios": [self._run(3.0, -6.0)]}
        cand = {"scenarios": [self._run(3.0, -6.0)]}
        comps = compare_runs(base, cand)
        self.assertEqual(gate(comps)["decision"], "pass")

    def test_collision_blocks(self):
        base = {"scenarios": [self._run(3.0, -6.0)]}
        cand = {"scenarios": [self._run(2.2, -6.4, collision=True, interventions=1)]}
        comps = compare_runs(base, cand)
        self.assertEqual(gate(comps)["decision"], "block")

    def test_ttc_drop_fails(self):
        base = {"scenarios": [self._run(3.2, -6.0)]}
        cand = {"scenarios": [self._run(2.6, -6.0)]}
        comps = compare_runs(base, cand)
        self.assertEqual(comps[0].status, "fail")

    def test_missing_scenario_reported(self):
        base = {"scenarios": [self._run(3.0, -6.0)]}
        cand = {"scenarios": []}
        comps = compare_runs(base, cand)
        self.assertEqual(len(comps), 1)
        self.assertIsNone(comps[0].candidate_ttc)


class TestCli(unittest.TestCase):
    def test_mine_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            log = generate(Path(d) / "logs")
            out = Path(d) / "out"
            result = mine(log, out)
            self.assertTrue(result["cards"])
            for name in ["scenarios.json", "scenarios.md", "scenarios.csv", "report.html"]:
                self.assertTrue((out / name).exists(), name)
            self.assertTrue(list((out / "osc").glob("*.xosc")))
            cards = json.loads((out / "scenarios.json").read_text(encoding="utf-8"))
            self.assertEqual(len(cards), len(result["cards"]))


if __name__ == "__main__":
    unittest.main()
