"""The watcher's rules against the one recorded game session.

fixtures/watcher_game_session.csv is the trial install's GPU probe
(/opt/llm/probe/gpu-probe.sh on fractal): about one row a second of whole-GPU
utilisation and VRAM as the WSL guest sees them, while a light game was
launched, sat on its loading screen for nine minutes, was played, and quit.
The model was loaded and idle through the launch. Each row is fed to the
watcher in place of the GPU reader, at its recorded time, with the stand-in
router answering for the model. The model's return after the quit is a real
load's length and GPU activity (fixtures/watcher_live_load.csv). The recording
ends before a quiet period and a load could pass, so the replay carries on with
synthetic idle samples for that long.
"""

from __future__ import annotations

import unittest

from watcher_harness import LINUX_ONLY, LIVE_LOAD, QUIET_S, Harness, at, game_session, idle_slot, parse_ts, slot

# The first sample at or above 3% after ninety idle seconds.
LAUNCH = at("17:54:37")
# The game's steady 17% ends here and its VRAM falls by 770 MiB.
QUIT = at("18:05:45")
# The last sample at or above 3%, a few seconds after the quit.
LAST_ACTIVITY = at("18:05:54")


@LINUX_ONLY
class GameSessionReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        session = game_session()
        cls.harness = Harness(cls.addClassCleanup, model="loaded", start=session[0].t - 1)
        for sample in session:
            cls.harness.tick(sample.t, sample.util)
        cls.harness.quiet(session[-1].t + 1, session[-1].t + QUIET_S + LIVE_LOAD[-1].t)

    def test_decides_to_yield_within_six_seconds_of_the_launch(self) -> None:
        (event,) = self.harness.events("handoff.yield")
        self.assertEqual(event["trigger"], "automatic")
        self.assertEqual(parse_ts(event["first_activity_ts"]), LAUNCH)
        self.assertLessEqual(parse_ts(event["decided_ts"]) - LAUNCH, 6)
        self.assertEqual(self.harness.server.unloads, [parse_ts(event["decided_ts"])])

    def test_never_resumes_during_the_load_screen_or_the_game(self) -> None:
        (load,) = self.harness.server.loads
        self.assertGreater(load, QUIT)

    def test_resumes_one_quiet_period_after_the_last_game_activity(self) -> None:
        (load,) = self.harness.server.loads
        self.assertGreaterEqual(load - LAST_ACTIVITY, QUIET_S)
        self.assertLessEqual(load - LAST_ACTIVITY, QUIET_S + 1)

    def test_ends_with_the_model_back_and_serving_despite_the_loads_own_activity(self) -> None:
        (load,) = self.harness.server.loads
        (event,) = self.harness.events("handoff.resume")
        self.assertEqual(event["trigger"], "automatic")
        self.assertEqual(parse_ts(event["load_started_ts"]), load)
        self.assertEqual(self.harness.events("handoff.resume_abandoned"), [])
        self.assertEqual(len(self.harness.events("handoff.yield")), 1)
        self.assertEqual(self.harness.state, "serving")

    def test_the_yield_event_carries_its_timings_and_the_samples_before_it(self) -> None:
        (event,) = self.harness.events("handoff.yield")
        decided = parse_ts(event["decided_ts"])
        self.assertGreater(parse_ts(event["released_ts"]), decided)
        self.assertEqual(event["requests_cut"], 0)
        self.assertEqual(event["busy_before_s"], 0)
        times = [parse_ts(sample["t"]) for sample in event["samples"]]
        self.assertEqual(max(times), decided)
        self.assertGreater(min(times), decided - 30)
        self.assertGreaterEqual(len(times), 25)
        self.assertEqual(set(event["samples"][-1]), {"t", "util", "busy"})


@LINUX_ONLY
class BusyAtLaunch(unittest.TestCase):
    """A request runs across the launch: the model's own work hides the game."""

    BUSY_FROM = at("17:54:30")
    IDLE_FROM = at("17:54:50")

    def test_no_yield_until_the_slot_goes_idle_then_one_within_the_window(self) -> None:
        session = [s for s in game_session() if s.t <= at("17:56:00")]
        harness = Harness(self.addCleanup, model="loaded", start=session[0].t - 1)
        for sample in session:
            busy = self.BUSY_FROM <= sample.t < self.IDLE_FROM
            harness.server.slots = [slot(0, 61000, busy)] + [idle_slot(i) for i in range(1, 4)]
            harness.tick(sample.t, sample.util)

        (unload,) = harness.server.unloads
        self.assertGreater(unload, self.IDLE_FROM)
        self.assertLessEqual(unload - self.IDLE_FROM, 5)
        (event,) = harness.events("handoff.yield")
        # Busy from the 17:54:30 sample to the 17:54:49 one: the upper bound on
        # how long the watcher could not see the game.
        self.assertEqual(event["busy_before_s"], 19)
        self.assertTrue(any(sample["busy"] for sample in event["samples"]))


if __name__ == "__main__":
    unittest.main()
