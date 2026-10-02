"""The watcher's states and transitions, its slot-change events and its health
rules, each driven tick by tick against the stand-in router over real HTTP."""

from __future__ import annotations

import threading
import unittest

from watcher_harness import QUIET_LOAD, Harness, at, idle_slot, parse_ts, slot

T0 = at("12:00:00")


def refuse_exit(code: int) -> None:
    raise AssertionError(f"the watcher ended itself with exit code {code}")


def gaps(times: list[float]) -> list[float]:
    return [later - earlier for earlier, later in zip(times, times[1:])]


class Adoption(unittest.TestCase):
    def test_started_with_the_model_loaded_it_is_serving(self) -> None:
        harness = Harness(self.addCleanup, model="loaded", start=T0)
        self.assertEqual(harness.state, "serving")
        (adopted,) = harness.events("state.adopted")
        self.assertEqual(adopted, adopted | {"state": "serving", "previous_state": None, "router_state": "loaded"})

    def test_started_empty_it_is_yielded_and_loads_only_after_the_quiet_period(self) -> None:
        harness = Harness(self.addCleanup, model="unloaded", start=T0)
        self.assertEqual(harness.state, "yielded")
        harness.quiet(T0 + 1, T0 + 59)
        self.assertEqual(harness.server.loads, [])
        harness.tick(T0 + 60)
        self.assertEqual(harness.server.loads, [T0 + 60])
        self.assertEqual(harness.state, "resuming")

    def test_started_during_a_load_it_is_resuming_and_serves_when_it_completes(self) -> None:
        harness = Harness(self.addCleanup, model="loading", start=T0)
        self.assertEqual(harness.state, "resuming")
        harness.quiet(T0 + 1, T0 + 110)
        self.assertEqual(harness.state, "serving")
        # The live load: its own GPU activity must not read as a game.
        self.assertEqual((harness.server.loads, harness.server.unloads), ([], []))
        (resume,) = harness.events("handoff.resume")
        self.assertIsNone(resume["quiet_since_ts"])


class SlotChanges(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Harness(self.addCleanup, model="loaded", start=T0)

    def test_one_event_per_change_and_none_when_nothing_changed(self) -> None:
        h = self.harness
        h.tick(T0 + 1)
        h.tick(T0 + 2)
        h.server.slots[0] = slot(0, 1200, busy=True)
        h.tick(T0 + 3)
        h.tick(T0 + 4)
        h.server.slots[0] = slot(0, 1450, busy=True)
        h.server.slots[2] = slot(2, 300, busy=False)
        h.tick(T0 + 5)
        h.server.slots[0] = slot(0, 1450, busy=False)
        h.tick(T0 + 6)
        h.tick(T0 + 7)

        events = h.events("slots.changed")
        self.assertEqual(len(events), 4)
        self.assertEqual(
            events[2]["slots"],
            [
                {"id": 0, "tokens": 1450, "busy": True},
                {"id": 1, "tokens": 0, "busy": False},
                {"id": 2, "tokens": 300, "busy": False},
                {"id": 3, "tokens": 0, "busy": False},
            ],
        )
        self.assertEqual([e["pool_tokens"] for e in events], [0, 1200, 1750, 1750])
        self.assertEqual({e["pool_limit"] for e in events}, {204800})

    def test_slots_empty_when_the_model_unloads(self) -> None:
        h = self.harness
        h.server.slots[1] = slot(1, 5000, busy=False)
        h.tick(T0 + 1)
        h.clock.now = T0 + 2
        h.watcher.yield_now()
        h.tick(T0 + 3)
        last = h.events("slots.changed")[-1]
        self.assertEqual((last["slots"], last["pool_tokens"]), ([], 0))

    def test_the_slot_report_never_asks_the_router_to_load_and_no_text_is_logged(self) -> None:
        h = self.harness
        h.server.slots[0] = slot(0, 900, busy=True, prompt="MARKER-7f3a conversation text")
        h.tick(T0 + 1)
        self.assertNotIn("MARKER-7f3a", h.log.getvalue())
        self.assertTrue(h.server.slot_queries)
        for query in h.server.slot_queries:
            self.assertEqual(query["autoload"], ["false"])


class UnansweredSlotReads(unittest.TestCase):
    """The model process answers a slot read only between steps, and saving or
    restoring a conversation is one long step."""

    def setUp(self) -> None:
        self.harness = Harness(self.addCleanup, model="loaded", start=T0,
                               env={"WATCHER_SERVER_SILENT_SECONDS": "10"})
        self.harness.server.slots[0] = slot(0, 52000, busy=False)
        self.harness.tick(T0 + 1)

    def test_an_unanswered_read_is_a_busy_model_whose_last_report_stands(self) -> None:
        h = self.harness
        h.server.silent = True
        for second in range(2, 9):
            h.tick(T0 + second, util=30)
        self.assertEqual(h.state, "serving")
        self.assertEqual(h.server.unloads, [])
        self.assertEqual(len(h.events("slots.changed")), 1)
        self.assertEqual(h.watcher.snapshot().pool_tokens, 52000)

        h.server.silent = False
        for second in range(9, 13):
            h.tick(T0 + second, util=30)
        # The first answered sample follows a busy one and does not count.
        self.assertEqual(h.server.unloads, [T0 + 12])

    def test_reads_unanswered_for_too_long_are_unhealthy_until_one_answers(self) -> None:
        h = self.harness
        h.server.silent = True
        h.quiet(T0 + 2, T0 + 12)
        self.assertIsNone(h.watcher.health())
        h.tick(T0 + 13)
        self.assertEqual(h.watcher.health(), "server_unresponsive")
        h.tick(T0 + 14)
        self.assertEqual([e["reason"] for e in h.events("watcher.unhealthy")], ["server_unresponsive"])
        h.watcher.end_if_stalled(refuse_exit)
        h.server.silent = False
        h.tick(T0 + 15)
        self.assertIsNone(h.watcher.health())


class SlotReadErrors(unittest.TestCase):
    """The model process can end, or the router start loading it again, between
    the status read and the slot read of one tick."""

    def setUp(self) -> None:
        self.harness = Harness(self.addCleanup, model="loaded", start=T0, load_profile=QUIET_LOAD, load_seconds=5)
        self.harness.server.slots[0] = slot(0, 900, busy=False)
        self.harness.tick(T0 + 1)

    def test_a_death_inside_the_slot_read_is_counted_once_by_the_next_tick(self) -> None:
        for answer in (500, 400):
            with self.subTest(answer=answer):
                h = Harness(self.addCleanup, model="loaded", start=T0, load_profile=QUIET_LOAD, load_seconds=5)
                h.tick(T0 + 1)
                h.server.dies_in_slot_read = answer
                h.tick(T0 + 2)
                h.tick(T0 + 3)
                (failure,) = h.events("load.failed")
                self.assertTrue(failure["error"].endswith("while serving"), failure["error"])
                self.assertEqual(h.state, "yielded")

    def test_an_error_answer_is_a_busy_model_whose_last_report_stands(self) -> None:
        h = self.harness
        h.server.dies_in_slot_read = 503
        h.tick(T0 + 2)
        self.assertEqual(h.watcher.snapshot().pool_tokens, 900)
        self.assertEqual(len(h.events("slots.changed")), 1)
        h.tick(T0 + 3)
        self.assertEqual(h.state, "resuming")


class UnloadingAModelAlreadyGone(unittest.TestCase):
    """The router answers "model is not running" to an unload that arrives
    after the model process ended on its own."""

    def test_yield_pressed_after_the_model_died_counts_the_death_and_holds(self) -> None:
        h = Harness(self.addCleanup, model="loaded", start=T0, load_profile=QUIET_LOAD, load_seconds=5)
        h.tick(T0 + 1)
        h.server.kill()
        h.clock.now = T0 + 1.5
        h.watcher.yield_now()
        h.tick(T0 + 2)
        (failure,) = h.events("load.failed")
        self.assertTrue(failure["error"].endswith("while serving"), failure["error"])
        self.assertEqual(h.events("handoff.yield"), [])
        self.assertEqual(h.state, "yielded")
        self.assertTrue(h.watcher.snapshot().held)
        h.quiet(T0 + 3, T0 + 600)
        self.assertEqual(h.server.loads, [])

    def test_yield_pressed_as_a_load_fails_is_the_failure_not_an_abandoned_load(self) -> None:
        h = Harness(self.addCleanup, model="unloaded", start=T0, load_profile=QUIET_LOAD, load_seconds=30)
        h.server.failing_loads = 1
        h.quiet(T0 + 1, T0 + 89)
        self.assertEqual(h.server.loads, [T0 + 60])
        h.clock.now = T0 + 90.5  # the load failed at T0 + 90; the watcher has not ticked since
        h.watcher.yield_now()
        h.tick(T0 + 91)
        self.assertEqual(h.events("handoff.resume_abandoned"), [])
        self.assertEqual([e["attempt"] for e in h.events("load.failed")], [1])
        self.assertEqual(h.state, "yielded")
        h.quiet(T0 + 92, T0 + 690)
        self.assertEqual(h.server.loads, [T0 + 60])

    def test_a_death_just_before_the_watchers_own_unload_is_counted(self) -> None:
        h = Harness(self.addCleanup, model="loaded", start=T0, load_profile=QUIET_LOAD, load_seconds=5)
        h.server.dies_before_unload = True
        for second in range(1, 8):
            h.tick(T0 + second, util=30)
        (failure,) = h.events("load.failed")
        self.assertTrue(failure["error"].endswith("while serving"), failure["error"])
        self.assertEqual(h.events("handoff.yield"), [])
        self.assertEqual(h.state, "yielded")


class Button(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Harness(self.addCleanup, model="loaded", start=T0)
        self.harness.tick(T0 + 1)
        self.harness.clock.now = T0 + 2
        self.harness.watcher.yield_now()

    def test_yield_unloads_at_once_and_holds_the_model_away_for_the_hold(self) -> None:
        h = self.harness
        self.assertEqual(h.server.unloads, [T0 + 2])
        h.quiet(T0 + 3, T0 + 601)
        self.assertEqual(h.server.loads, [])
        h.tick(T0 + 602)
        self.assertEqual(h.server.loads, [T0 + 602])
        (event,) = h.events("handoff.yield")
        self.assertEqual(event["trigger"], "button")
        self.assertIsNone(event["first_activity_ts"])

    def test_yield_while_busy_counts_the_requests_cut(self) -> None:
        harness = Harness(self.addCleanup, model="loaded", start=T0)
        harness.server.slots = [slot(0, 800, True), slot(1, 300, True), idle_slot(2), idle_slot(3)]
        harness.tick(T0 + 1)
        harness.clock.now = T0 + 2
        harness.watcher.yield_now()
        harness.quiet(T0 + 3, T0 + 5)
        (event,) = harness.events("handoff.yield")
        self.assertEqual(event["requests_cut"], 2)

    def test_resume_ends_the_hold_and_loads_at_once(self) -> None:
        h = self.harness
        h.quiet(T0 + 3, T0 + 10)
        h.clock.now = T0 + 11
        h.watcher.resume_now()
        self.assertEqual(h.server.loads, [T0 + 11])
        h.quiet(T0 + 12, T0 + 120)
        (event,) = h.events("handoff.resume")
        self.assertEqual(event["trigger"], "button")
        self.assertEqual(h.state, "serving")

    def test_resume_pressed_while_yielding_loads_as_soon_as_the_unload_ends(self) -> None:
        h = self.harness
        h.tick(T0 + 3)
        self.assertEqual(h.state, "yielding")
        h.watcher.resume_now()
        self.assertEqual(h.server.loads, [])
        h.tick(T0 + 4)  # the router reports the unload done
        self.assertEqual(h.server.loads, [T0 + 4])
        h.quiet(T0 + 5, T0 + 110)
        (event,) = h.events("handoff.resume")
        self.assertEqual(event["trigger"], "button")
        self.assertEqual(h.state, "serving")

    def test_yield_pressed_after_that_resume_cancels_it(self) -> None:
        h = self.harness
        h.tick(T0 + 3)
        h.watcher.resume_now()
        h.watcher.yield_now()
        h.quiet(T0 + 4, T0 + 602)
        self.assertEqual(h.server.loads, [])


class Loads(unittest.TestCase):
    """A load is blind, like a busy slot: its own GPU activity looks like a
    game's, so only the Yield button ends one early."""

    def setUp(self) -> None:
        # The live load: requested at T0 + 60, ready at T0 + 165.
        self.harness = Harness(self.addCleanup, model="unloaded", start=T0)
        self.harness.quiet(T0 + 1, T0 + 60)
        self.assertEqual(self.harness.server.loads, [T0 + 60])

    def test_the_loads_own_activity_neither_abandons_it_nor_yields_the_model_after(self) -> None:
        h = self.harness
        h.quiet(T0 + 61, T0 + 240)
        self.assertEqual(h.server.unloads, [])
        self.assertEqual(h.events("handoff.resume_abandoned"), [])
        (resume,) = h.events("handoff.resume")
        self.assertEqual(parse_ts(resume["ready_ts"]), T0 + 165)
        self.assertEqual(h.state, "serving")

    def test_a_game_during_a_load_is_seen_once_the_model_is_ready(self) -> None:
        h = self.harness
        for t in range(int(T0) + 61, int(T0) + 175):
            h.tick(t, util=20 if t >= T0 + 100 else 0)
        self.assertEqual(h.events("handoff.resume_abandoned"), [])
        # Only samples taken after the model was ready count.
        self.assertEqual(h.server.unloads, [T0 + 168])
        h.tick(T0 + 175, util=20)
        (event,) = h.events("handoff.yield")
        self.assertEqual(parse_ts(event["first_activity_ts"]), T0 + 166)

    def test_the_yield_button_cancels_a_load(self) -> None:
        h = self.harness
        h.quiet(T0 + 61, T0 + 79)
        h.clock.now = T0 + 80
        h.watcher.yield_now()
        self.assertEqual(h.server.unloads, [T0 + 80])
        h.quiet(T0 + 81, T0 + 90)
        (abandoned,) = h.events("handoff.resume_abandoned")
        self.assertEqual(parse_ts(abandoned["load_started_ts"]), T0 + 60)
        self.assertEqual(parse_ts(abandoned["abandoned_ts"]), T0 + 80)
        (handoff,) = h.events("handoff.yield")
        self.assertEqual(handoff["trigger"], "button")
        self.assertEqual(h.state, "yielded")
        self.assertEqual(h.events("load.failed"), [])
        h.quiet(T0 + 91, T0 + 679)
        self.assertEqual(h.server.loads, [T0 + 60])


class ExternalLoads(unittest.TestCase):
    """The router's autoload parameter lets something other than the watcher
    load the model."""

    def test_while_a_game_is_active_the_model_is_unloaded_at_once(self) -> None:
        h = Harness(self.addCleanup, model="loaded", start=T0, load_profile=QUIET_LOAD, load_seconds=5)
        for second in range(1, 30):
            h.tick(T0 + second, util=40)
        self.assertEqual(len(h.events("handoff.yield")), 1)
        h.server.load_elsewhere()
        for second in range(30, 40):
            h.tick(T0 + second, util=40)
        self.assertEqual(len(h.server.unloads), 2)
        self.assertEqual([e["trigger"] for e in h.events("handoff.yield")], ["automatic", "external_load"])
        self.assertEqual((h.server.loads, h.events("load.failed")), ([], []))
        self.assertEqual(h.state, "yielded")

    def test_during_a_hold_the_model_is_unloaded_at_once(self) -> None:
        h = Harness(self.addCleanup, model="loaded", start=T0, load_profile=QUIET_LOAD, load_seconds=5)
        h.tick(T0 + 1)
        h.clock.now = T0 + 2
        h.watcher.yield_now()
        h.quiet(T0 + 3, T0 + 200)
        h.server.load_elsewhere()
        h.quiet(T0 + 201, T0 + 220)
        self.assertEqual(h.server.unloads, [T0 + 2, T0 + 201])
        self.assertEqual([e["trigger"] for e in h.events("handoff.yield")], ["button", "external_load"])
        self.assertEqual(h.state, "yielded")

    def test_in_the_quiet_period_after_the_watcher_starts_the_model_is_unloaded_at_once(self) -> None:
        # Quiet counts from the start until activity is seen, for this check as
        # for the watcher's own load.
        h = Harness(self.addCleanup, model="unloaded", start=T0, load_profile=QUIET_LOAD, load_seconds=5)
        h.quiet(T0 + 1, T0 + 30)
        h.server.load_elsewhere()
        h.tick(T0 + 31)
        self.assertEqual(h.server.unloads, [T0 + 31])
        h.quiet(T0 + 32, T0 + 60)
        self.assertEqual([e["trigger"] for e in h.events("handoff.yield")], ["external_load"])
        self.assertEqual(h.server.loads, [T0 + 60])

    def test_once_the_gpu_has_been_quiet_for_the_quiet_period_it_is_adopted(self) -> None:
        # Quiet since the start, with the watcher's own load waiting out a retry delay.
        h = Harness(self.addCleanup, model="unloaded", start=T0, load_profile=QUIET_LOAD, load_seconds=5)
        h.server.failing_loads = 1
        h.quiet(T0 + 1, T0 + 69)
        self.assertEqual([e["attempt"] for e in h.events("load.failed")], [1])
        h.server.load_elsewhere()
        h.tick(T0 + 70)
        self.assertEqual(h.state, "resuming")
        adopted = h.events("state.adopted")[-1]
        self.assertEqual(
            {key: adopted[key] for key in ("previous_state", "router_state", "state")},
            {"previous_state": "yielded", "router_state": "loading", "state": "resuming"},
        )
        h.quiet(T0 + 71, T0 + 100)
        self.assertEqual(h.state, "serving")
        (resume,) = h.events("handoff.resume")
        self.assertEqual(resume["trigger"], "external_load")
        self.assertEqual((h.server.loads, h.server.unloads), ([T0 + 60], []))

    def test_already_running_at_the_watchers_own_load_is_not_a_failed_load(self) -> None:
        h = Harness(self.addCleanup, model="unloaded", start=T0, load_profile=QUIET_LOAD, load_seconds=5)
        h.quiet(T0 + 1, T0 + 59)
        h.server.load_elsewhere_first = True
        h.tick(T0 + 60)
        self.assertEqual(h.events("load.failed"), [])
        self.assertEqual(h.state, "resuming")
        h.quiet(T0 + 61, T0 + 70)
        self.assertEqual(h.state, "serving")


class Recovery(unittest.TestCase):
    def test_failed_loads_retry_with_growing_delays_then_give_up_unhealthy(self) -> None:
        h = Harness(self.addCleanup, model="unloaded", start=T0, load_seconds=5, load_profile=QUIET_LOAD)
        h.server.failing_loads = 99
        h.quiet(T0 + 1, T0 + 1200)

        loads = h.server.loads
        self.assertEqual(len(loads), 5)
        self.assertTrue(all(b > a for a, b in zip(gaps(loads), gaps(loads)[1:])), gaps(loads))
        self.assertEqual([e["attempt"] for e in h.events("load.failed")], [1, 2, 3, 4, 5])
        self.assertEqual(h.state, "yielded")
        self.assertEqual(h.watcher.health(), "load_given_up")
        self.assertEqual([e["reason"] for e in h.events("watcher.unhealthy")], ["load_given_up"])
        h.watcher.end_if_stalled(refuse_exit)

    def test_a_load_that_never_finishes_is_a_failed_attempt(self) -> None:
        h = Harness(self.addCleanup, model="unloaded", start=T0, load_seconds=10**6, load_profile=QUIET_LOAD,
                    env={"WATCHER_LOAD_TIMEOUT_SECONDS": "120"})
        h.quiet(T0 + 1, T0 + 180)
        self.assertEqual((h.server.loads, h.server.unloads), ([T0 + 60], []))
        h.tick(T0 + 181)
        self.assertEqual(h.server.unloads, [T0 + 181])
        (failure,) = h.events("load.failed")
        self.assertEqual(failure["attempt"], 1)
        self.assertIn("timed out", failure["error"])

        h.quiet(T0 + 182, T0 + 1000)
        self.assertEqual(h.server.loads[1], T0 + 196)  # the first retry delay, as for any failure
        self.assertEqual(len(h.server.loads), 5)
        self.assertEqual(len(h.server.unloads), 5)
        self.assertEqual(h.events("handoff.yield"), [])
        self.assertEqual(h.watcher.health(), "load_given_up")

    def test_a_model_that_keeps_dying_is_a_failing_load(self) -> None:
        h = Harness(self.addCleanup, model="unloaded", start=T0, load_seconds=5, load_profile=QUIET_LOAD)
        h.server.lifetimes = [10.0] * 10
        h.quiet(T0 + 1, T0 + 1500)

        loads = h.server.loads
        self.assertEqual(len(loads), 5)
        self.assertTrue(all(b > a for a, b in zip(gaps(loads), gaps(loads)[1:])), gaps(loads))
        self.assertEqual([e["attempt"] for e in h.events("load.failed")], [1, 2, 3, 4, 5])
        lost = [e for e in h.events("state.adopted") if e["previous_state"] == "serving"]
        self.assertEqual({(e["router_state"], e["state"]) for e in lost}, {("unloaded", "yielded")})
        self.assertEqual(len(lost), 5)
        self.assertEqual(h.watcher.health(), "load_given_up")

    def test_a_model_unloaded_by_something_else_while_serving_is_a_failed_load(self) -> None:
        h = Harness(self.addCleanup, model="loaded", start=T0, load_profile=QUIET_LOAD, load_seconds=5)
        h.tick(T0 + 1)
        h.server.unload_elsewhere()
        h.quiet(T0 + 2, T0 + 4)
        (failure,) = h.events("load.failed")
        # The router reports no exit code for a process that exited cleanly.
        self.assertEqual(failure["error"], "model process exited while serving")

    def test_failures_are_forgotten_only_after_ten_minutes_loaded(self) -> None:
        h = Harness(self.addCleanup, model="unloaded", start=T0, load_seconds=5, load_profile=QUIET_LOAD)
        h.server.lifetimes = [10.0, 10.0, 700.0, 10.0]
        h.quiet(T0 + 1, T0 + 900)
        self.assertEqual([e["attempt"] for e in h.events("load.failed")], [1, 2, 1, 2])

    def test_the_routers_forced_stop_of_the_watchers_own_unload_is_not_a_failure(self) -> None:
        h = Harness(self.addCleanup, model="loaded", start=T0, load_profile=QUIET_LOAD, load_seconds=5)
        h.server.forced_stop = True
        for second in range(1, 8):
            h.tick(T0 + second, util=30)
        self.assertEqual(h.state, "yielded")
        self.assertEqual(h.server.status(), h.server.status() | {"value": "unloaded", "failed": True, "exit_code": 1})
        h.quiet(T0 + 8, T0 + 80)
        self.assertEqual(h.events("load.failed"), [])
        self.assertEqual(len(h.events("state.adopted")), 1)
        self.assertEqual(h.server.loads, [T0 + 67])  # the quiet period after the game, as for any yield
        self.assertEqual(h.state, "serving")

    def test_a_retry_waits_for_a_game_seen_during_the_failed_load_to_go_quiet(self) -> None:
        h = Harness(self.addCleanup, model="unloaded", start=T0, load_seconds=30, load_profile=QUIET_LOAD)
        h.server.failing_loads = 1
        h.quiet(T0 + 1, T0 + 60)
        for t in range(int(T0) + 61, int(T0) + 200):
            h.tick(t, util=20 if t < T0 + 90 else 0)
        # Failed at T0 + 90; the retry delay alone would allow T0 + 105.
        self.assertEqual(h.server.loads, [T0 + 60, T0 + 149])


class Health(unittest.TestCase):
    def test_a_stale_sample_is_the_watchdogs_not_the_health_checks(self) -> None:
        h = Harness(self.addCleanup, model="loaded", start=T0)
        h.tick(T0 + 1)
        h.clock.now = T0 + 30
        self.assertIsNone(h.watcher.health())

    def test_a_yield_that_does_not_release_the_gpu_is_unhealthy_past_the_stuck_limit(self) -> None:
        h = Harness(self.addCleanup, model="loaded", start=T0, unload_seconds=3600)
        h.tick(T0 + 1)
        h.clock.now = T0 + 2
        h.watcher.yield_now()
        h.quiet(T0 + 3, T0 + 32)
        self.assertEqual(h.state, "yielding")
        self.assertIsNone(h.watcher.health())
        h.tick(T0 + 33)
        self.assertEqual(h.watcher.health(), "yield_stuck")
        h.watcher.end_if_stalled(refuse_exit)

    def test_vram_at_the_limit_is_unhealthy_while_serving_only(self) -> None:
        h = Harness(self.addCleanup, model="loaded", start=T0)
        h.gpu.memory_used_mib = 31200
        h.tick(T0 + 1)
        self.assertEqual(h.watcher.health(), "vram_at_limit")
        h.watcher.end_if_stalled(refuse_exit)
        yielded = Harness(self.addCleanup, model="unloaded", start=T0)
        yielded.gpu.memory_used_mib = 31500
        yielded.tick(T0 + 1)
        self.assertIsNone(yielded.watcher.health())


class ModelFileCache(unittest.TestCase):
    def test_dropped_each_time_the_model_becomes_loaded_or_unloaded_whoever_caused_it(self) -> None:
        h = Harness(self.addCleanup, model="loaded", start=T0, load_profile=QUIET_LOAD, load_seconds=5)
        h.tick(T0 + 1)  # loaded at start
        h.clock.now = T0 + 2
        h.watcher.yield_now()
        h.quiet(T0 + 3, T0 + 4)  # unloaded at T0 + 4
        h.clock.now = T0 + 5
        h.watcher.resume_now()
        h.quiet(T0 + 6, T0 + 70)  # loaded at T0 + 10
        h.server.kill()
        h.tick(T0 + 71)
        h.server.load_elsewhere()
        h.quiet(T0 + 72, T0 + 80)  # found loading after a quiet period, then loaded at T0 + 76
        self.assertEqual(h.events("handoff.resume")[-1]["trigger"], "external_load")
        self.assertEqual(h.guest.drops, [T0 + 1, T0 + 4, T0 + 10, T0 + 71, T0 + 76])


class WallClockCorrections(unittest.TestCase):
    """WSL2 moves the guest's wall clock when Windows sleeps or resumes."""

    def test_a_correction_moves_no_deadline_and_trips_no_watchdog(self) -> None:
        for correction in (3600.0, -3600.0):
            with self.subTest(correction=correction):
                h = Harness(self.addCleanup, model="loaded", start=T0, load_profile=QUIET_LOAD, load_seconds=5)
                h.tick(T0 + 1)
                h.clock.now = T0 + 2
                h.watcher.yield_now()
                h.quiet(T0 + 3, T0 + 5)
                h.clock.wall_correction = correction
                h.watcher.end_if_stalled(refuse_exit)
                h.quiet(T0 + 6, T0 + 601)
                self.assertEqual(h.server.loads, [])
                h.quiet(T0 + 602, T0 + 607)
                self.assertEqual(h.server.loads, [T0 + 602])
                (resume,) = h.events("handoff.resume")
                # Log lines carry the corrected wall time; the durations between them do not move.
                self.assertEqual(parse_ts(resume["ts"]), T0 + 607 + correction)
                self.assertEqual(parse_ts(resume["ready_ts"]) - parse_ts(resume["load_started_ts"]), 5)


class StallWatchdog(unittest.TestCase):
    """A stale sample ends the process so Docker restarts it; nothing else does."""

    def setUp(self) -> None:
        self.harness = Harness(self.addCleanup, model="loaded", start=T0)
        self.harness.tick(T0 + 1)
        self.exits: list[int] = []

    def test_a_stale_sample_ends_the_process_after_one_unhealthy_line(self) -> None:
        h = self.harness
        h.clock.now = T0 + 11
        h.watcher.end_if_stalled(self.exits.append)
        self.assertEqual(self.exits, [])
        h.clock.now = T0 + 11.5
        h.watcher.end_if_stalled(self.exits.append)
        self.assertEqual(self.exits, [1])
        self.assertEqual([e["reason"] for e in h.events("watcher.unhealthy")], ["sample_stale"])

    def test_it_ends_the_process_while_the_tick_is_stuck_holding_the_lock(self) -> None:
        h = self.harness
        h.gpu.reading.clear()
        h.gpu.release.clear()
        self.addCleanup(h.gpu.release.set)
        stuck = threading.Thread(target=h.tick, args=(T0 + 2,), daemon=True)
        stuck.start()
        self.assertTrue(h.gpu.reading.wait(timeout=5))
        h.clock.now = T0 + 12
        check = threading.Thread(target=h.watcher.end_if_stalled, args=(self.exits.append,), daemon=True)
        check.start()
        check.join(timeout=5)
        self.assertFalse(check.is_alive(), "the stall check waited on the stuck tick")
        self.assertEqual(self.exits, [1])
        h.gpu.release.set()
        stuck.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
