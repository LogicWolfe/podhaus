"""The Alloy parsing modules for the local model service, run against real log lines.

Alloy offers no way to run one module's stages from a unit test, so these tests
read the modules' own regular expressions, selectors and label maps out of the
`.alloy` files and apply them with Python's `re` the way loki.process would.
Python's `re` and Alloy's RE2 agree on every construct the modules use (named
groups, anchors, classes, lazy and greedy quantifiers). What this proves: each
captured server line is classified once, with the right fields. What it does
not prove: that Alloy accepts the file or that its stages compose as modelled
here. The modules were also run once through the Alloy binary itself, which
found two mistakes this model now rejects: a selector that passes a line its
expression misses (the block's labels and kind land on the wrong line), and two
selectors passing one line (the second reuses the first's extracted values).

The model server's lines come from the trial server's journal
(fixtures/llm_server_trace_sample.txt) and from a live router-mode run
(fixtures/llm_server_router_sample.txt, with a real model-process crash and
the router's own lines). fixtures/llm_server_text_bearing_synthetic.txt is not
captured: it is built from the llama.cpp source's format strings for the log
calls that quote a request or a reply, each filled with a MARKER_ string that
must never reach storage. The watcher's lines are written by the watcher's own
code, driven through its test harness. The Caddy access lines are shaped from
the ingress worker's Caddyfile (fixtures/caddy_llm_access_sample.jsonl).

The model also covers the stages that decide what is stored at all: the
multiline join (a message's continuation lines belong to its first line, a
stray line with no entry before it is its own), the drops, the prefix gate and
the text reduction. The Alloy run found that the join leaves a stray line as
its own entry, which the model now follows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from collections import Counter
import json
from pathlib import Path
import re
import unittest

from alloy_pipeline import Entry, Pipeline, Selector
from watcher_harness import LINUX_ONLY, QUIET_LOAD, Harness, at, slot

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "logging" / "alloy-modules"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def alloy_string(literal: str) -> str:
    """The value of an Alloy string literal, given its source text between the quotes."""
    return json.loads(f'"{literal}"')


STRING = r'"((?:[^"\\]|\\.)*)"'


def selector_passes(selector: str, text: str) -> bool:
    """The selector's line filters, as loki.process applies them to the current line."""
    parsed = Selector.read(selector)
    return parsed.passes(text, {name: value for name, op, value in parsed.matchers if op == "="})


def server_pipeline() -> Pipeline:
    return Pipeline.from_module(MODULES / "llm-server.alloy")


def fixture_lines(path: Path) -> list[str]:
    return [
        line for line in path.read_text().splitlines()
        if line and not line.startswith("# ")
    ]


REAL_SERVER_FIXTURES = ("llm_server_trace_sample.txt", "llm_server_router_sample.txt")
SYNTHETIC_FIXTURE = "llm_server_text_bearing_synthetic.txt"
# Kinds a line gets when its text is replaced, so none of them stores the line's own words.
REDUCED_KINDS = {"text_removed", "output_unparsed", "request_exception", "server_exception", "decode_failed"}


class ServerLineParsingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = server_pipeline()
        cls.lines = fixture_lines(FIXTURES / "llm_server_trace_sample.txt")

    def one(self, line: str) -> Entry:
        (entry,) = self.module.process([line])
        return entry

    def line(self, needle: str, nth: int = 0) -> str:
        return [line for line in self.lines if needle in line][nth]

    def assertParsed(self, needle: str, kind: str, labels: dict[str, str],
                     level: str = "INFO", nth: int = 0) -> None:
        entry = self.one(self.line(needle, nth))
        self.assertEqual((entry.kind, entry.level, entry.fields), (kind, level, labels))

    def test_slot_chosen_by_prompt_similarity_carries_the_similarity_figures(self) -> None:
        self.assertParsed(
            "selected slot by LCP", "slot_selected",
            {"llm_slot": "2", "llm_select_by": "LCP", "llm_f_sim": "1.000", "llm_f_keep": "0.798"},
        )

    def test_slot_chosen_as_least_recently_used_has_no_similarity_figures(self) -> None:
        self.assertParsed(
            "selected slot by LRU", "slot_selected", {"llm_slot": "2", "llm_select_by": "LRU"},
        )

    def test_a_new_request_reports_its_prompt_size_and_binds_task_to_slot(self) -> None:
        self.assertParsed(
            "task 5398 | new prompt", "prompt",
            {"llm_slot": "2", "llm_task": "5398", "llm_prompt_tokens": "103"},
        )
        self.assertParsed(
            "task 5398 | processing task", "task_started", {"llm_slot": "2", "llm_task": "5398"},
        )

    def test_tokens_kept_from_the_slot_are_the_first_cached_count(self) -> None:
        self.assertParsed(
            "task 5398 | cached n_tokens", "reuse",
            {"llm_slot": "2", "llm_task": "5398", "llm_cached_tokens": "99"},
        )

    def test_read_timing_carries_tokens_read_time_and_speed(self) -> None:
        self.assertParsed(
            "task 5398 | prompt eval time", "read_timing",
            {"llm_slot": "2", "llm_task": "5398", "llm_read_ms": "87.68",
             "llm_read_tokens": "4", "llm_read_tps": "45.62"},
        )

    def test_generation_timing_is_not_mistaken_for_read_timing(self) -> None:
        self.assertParsed(
            "task 5398 |        eval time", "output_timing",
            {"llm_slot": "2", "llm_task": "5398", "llm_output_ms": "205.19",
             "llm_output_tokens": "27", "llm_output_tps": "126.71"},
        )

    def test_total_time_and_final_context_length(self) -> None:
        self.assertParsed(
            "task 5398 |       total time", "total_timing",
            {"llm_slot": "2", "llm_task": "5398", "llm_total_ms": "292.87", "llm_total_tokens": "31"},
        )
        self.assertParsed(
            "task 5398 | stop processing", "finished",
            {"llm_slot": "2", "llm_task": "5398", "llm_final_tokens": "130", "llm_truncated": "0"},
        )

    def test_drafted_against_accepted_tokens(self) -> None:
        self.assertParsed(
            "task 3441 | draft acceptance", "draft",
            {"llm_slot": "0", "llm_task": "3441", "llm_draft_accepted": "424", "llm_draft_generated": "554"},
        )

    def test_a_forced_full_re_read_is_marked(self) -> None:
        self.assertParsed("forcing full prompt re-processing", "full_reread",
                          {"llm_slot": "0", "llm_task": "3441"})

    def test_a_long_prompt_read_reports_progress_for_slow_starts(self) -> None:
        self.assertParsed(
            "prompt processing, n_tokens", "read_progress",
            {"llm_slot": "0", "llm_task": "3441", "llm_read_tokens": "14336",
             "llm_progress": "0.58", "llm_read_seconds": "3.26"},
        )

    def test_saving_a_conversation_to_memory(self) -> None:
        self.assertParsed(
            "saving prompt with length 467", "conversation_saved",
            {"llm_saved_tokens": "467", "llm_saved_mib": "166.123"},
        )

    def test_restoring_a_saved_conversation_into_a_slot(self) -> None:
        self.assertParsed(
            "found better prompt", "conversation_restored",
            {"llm_restored_f_keep": "1.000", "llm_restored_f_sim": "0.999"},
        )

    def test_discarding_the_oldest_saved_conversation(self) -> None:
        self.assertParsed(
            "making room for prompt cache entry", "conversation_discarded",
            {"llm_discarded_mib": "951.777"}, level="WARN",
        )

    def test_a_saved_conversation_too_large_for_the_memory_is_not_kept(self) -> None:
        self.assertParsed(
            "exceeds cache size limit", "conversation_unsaved",
            {"llm_unsaved_mib": "2090.777", "llm_unsaved_limit_mib": "1024.000"}, level="WARN",
        )

    def test_an_idle_slot_purged_because_the_pool_is_full(self) -> None:
        self.assertParsed(
            "purging slot 0", "slot_purged", {"llm_slot": "0", "llm_purged_tokens": "12761"},
            level="WARN",
        )

    def test_pool_exhaustion_with_every_slot_busy(self) -> None:
        self.assertParsed(
            "failed to find free space in the KV cache", "pool_full",
            {"llm_batch_size": "2048"}, level="WARN",
        )
        self.assertParsed(
            "decode: Context size has been exceeded", "pool_full",
            {"llm_batch_size": "1"}, level="ERROR",
        )

    def test_a_failed_request_carries_the_servers_error(self) -> None:
        self.assertParsed(
            "task id = 59", "request_error",
            {"llm_task": "59", "llm_error": "Context size has been exceeded."}, level="ERROR",
        )
        self.assertParsed(
            "task id = 83", "request_error",
            {"llm_task": "83",
             "llm_error": "request (36728 tokens) exceeds the available context size (32768 tokens), try increasing it"},
            level="ERROR",
        )

    def test_body_is_the_message_without_the_uptime_clock_and_level_letter(self) -> None:
        entry = self.one(self.line("selected slot by LRU"))
        self.assertTrue(entry.text.startswith("slot get_availabl: id  2 | task -1 | selected slot"))

    def test_the_router_forwards_model_process_lines_behind_a_port_tag(self) -> None:
        plain = self.one(self.line("task 5398 | prompt eval time"))
        for tag in ("[50123] ", "[ 8081] "):
            with self.subTest(tag=tag):
                self.assertEqual(self.one(tag + self.line("task 5398 | prompt eval time")), plain)

    def test_a_real_router_mode_request_parses_behind_its_port_tag(self) -> None:
        tagged = [line for line in self.lines if re.match(r"^\[\d+\] ", line)]
        self.assertGreaterEqual(len(tagged), 6)
        kinds = {self.one(line).kind for line in tagged}
        self.assertLessEqual(
            {"slot_selected", "task_started", "read_timing", "output_timing", "total_timing", "finished"}, kinds
        )

    def test_the_tool_schema_warning_is_dropped_as_it_quotes_client_text(self) -> None:
        warning = self.line("WARNING: JSON schema conversion was incomplete")
        self.assertIn("pattern ^(?!", warning)
        self.assertEqual(self.module.process([warning]), [])

    def test_the_tool_schema_warning_is_dropped_behind_the_router_tag_too(self) -> None:
        """The router prefixes every line a model process prints, this one included."""
        warning = "[45589] " + self.line("WARNING: JSON schema conversion was incomplete")
        self.assertEqual(self.module.process([warning]), [])

    def test_only_the_named_drops_remove_real_lines(self) -> None:
        for name in REAL_SERVER_FIXTURES:
            lines = fixture_lines(FIXTURES / name)
            kept = len(self.module.process(lines))
            removed = len(self.module.entries(lines)) - kept
            expected = sum(
                "conv_id=" in line or "WARNING: JSON schema" in line or "proxying request to model" in line
                for line in lines
            )
            with self.subTest(fixture=name):
                self.assertEqual(removed, expected)


class RealFixtureVisibilityTest(unittest.TestCase):
    """What the allow-list keeps of real server output, and what it reduces."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = server_pipeline()

    def entries(self, name: str) -> list[Entry]:
        return self.module.process(fixture_lines(FIXTURES / name))

    def test_every_real_line_that_gave_request_detail_still_does(self) -> None:
        """The baseline is what the module promoted from these fixtures before the allow-list replaced the drop list."""
        baseline = json.loads((FIXTURES / "llm_server_request_detail_baseline.json").read_text())
        for name in REAL_SERVER_FIXTURES:
            now = [
                {"kind": e.kind, "level": e.level, "fields": e.fields}
                for e in self.entries(name) if e.kind not in ("", "other", *REDUCED_KINDS)
            ]
            with self.subTest(fixture=name):
                self.assertEqual(now, baseline[name])

    def test_the_only_real_entries_reduced_are_the_crash_backtraces_and_they_keep_their_level(self) -> None:
        reduced = [
            e for name in REAL_SERVER_FIXTURES for e in self.entries(name) if e.kind in REDUCED_KINDS
        ]
        self.assertEqual(len(reduced), 3)
        for entry in reduced:
            self.assertEqual((entry.text, entry.level, entry.kind), ("text removed", "ERROR", "text_removed"))

    def test_the_real_crash_keeps_its_fact_and_place_as_known_shapes(self) -> None:
        entries = self.entries("llm_server_router_sample.txt")
        fault = [e for e in entries if e.text == "CUDA error: unknown error"]
        device = [e for e in entries if e.text.startswith("  current device: 0, in function ggml_backend_cuda_synchronize")]
        self.assertTrue(fault and device)
        for entry in fault + device:
            self.assertEqual((entry.level, entry.kind), ("ERROR", "other"))
        exits = [e for e in entries if "exited with status 1" in e.text]
        self.assertEqual({(e.level, e.kind) for e in exits}, {("INFO", "other")})

    def test_the_real_sampler_parameters_are_kept_whole_with_their_rows(self) -> None:
        params = [e for e in self.entries("llm_server_trace_sample.txt") if "sampler params" in e.text]
        self.assertEqual(len(params), 4)
        for entry in params:
            self.assertEqual((entry.kind, entry.text.count("\n")), ("other", 4))


class AllowListStrictnessTest(unittest.TestCase):
    """A known shape with anything added does not pass."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = server_pipeline()
        cls.lines = [
            line for name in REAL_SERVER_FIXTURES for line in fixture_lines(FIXTURES / name)
            if re.match(r"^(\[ *\d+\] )?\d+\.\d{2}\.\d{3}\.\d{3} [IWED] ", line)
            and not any(x in line for x in ("proxying request", "conv_id=", "WARNING"))
        ]

    def test_text_appended_to_a_real_line_is_removed(self) -> None:
        for line in self.lines:
            for suffix in (" MARKER_APPENDED", "\nMARKER_NEXT_LINE", " \nMARKER_AFTER_SPACE"):
                with self.subTest(line=line[:90], suffix=suffix):
                    (entry,) = self.module.process([line + suffix])
                    self.assertNotIn("MARKER", entry.text)
                    self.assertNotIn("MARKER", "".join(entry.labels.values()))
                    self.assertTrue(entry.text.endswith("text removed"))

    def test_a_known_shape_in_front_of_other_text_is_removed(self) -> None:
        line = "0.01.000.001 I srv  update_slots: all slots are idle"
        for variant in (line + " MARKER_ONE", "MARKER_TWO " + line, line.replace("all slots", "MARKER_THREE slots")):
            with self.subTest(variant=variant):
                (entry,) = self.module.process([variant])
                self.assertNotIn("MARKER", entry.text)

    def test_every_allow_list_shape_is_anchored_and_bounded(self) -> None:
        """No wildcard, no unbounded word run: a shape's variable parts are numbers, spaces or fixed sets."""
        module = (MODULES / "llm-server.alloy").read_text()
        shapes = [
            block.attrs["selector"] for block in self.allow_list_blocks()
        ]
        self.assertGreaterEqual(len(shapes), 20)
        for selector in shapes:
            (literal,) = [pattern for op, pattern in Selector.read(selector).filters if op == "|~"]
            with self.subTest(shape=literal[:80]):
                self.assertTrue(literal.startswith("^") and literal.endswith("\\z"), literal[:60])
                for forbidden in (r"\.[*+{]", r"\\[SsWD]", r"\[\^", r"\\w[+*]", r"\[[^\]]*[A-Za-z][^\]]*\][+*]"):
                    self.assertIsNone(re.search(forbidden, literal.replace("\\\\", "")), forbidden)
        self.assertIn("stage.multiline", module)

    def allow_list_blocks(self):
        return [
            stage for stage in self.module.stages
            if stage.name == "stage.match" and "|~" in str(stage.attrs.get("selector", ""))
            and not stage.attrs.get("action") and 'llm_line=\\"\\"' not in str(stage.attrs["selector"]).replace('"', '\\"')
            and any(c.name == "stage.static_labels" for c in stage.children)
            and not any(c.name == "stage.output" for c in stage.children)
        ]

    def test_each_kind_blocks_selector_and_expression_are_the_same_shape(self) -> None:
        checked = 0
        for block in self.allow_list_blocks():
            regexes = [c for c in block.children if c.name == "stage.regex"]
            if not regexes:
                continue
            (selector_pattern,) = [p for op, p in Selector.read(str(block.attrs["selector"])).filters if op == "|~"]
            with self.subTest(shape=selector_pattern[:80]):
                self.assertEqual(selector_pattern, regexes[0].attrs["expression"])
            checked += 1
        self.assertGreaterEqual(checked, 18)


class UnprefixedLineTest(unittest.TestCase):
    """A line that carries no level letter is not an `I` line: it gets no level, and unless
    it matches a known shape its text is not stored."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = server_pipeline()
        cls.router = fixture_lines(FIXTURES / "llm_server_router_sample.txt")

    def test_a_lone_line_with_no_level_prefix_is_stored_as_a_fixed_phrase_with_no_level(self) -> None:
        for line in (
            "found 1 CUDA devices with MARKER_FREE text",
            "\ttop_k = 20, top_p = 0.950, min_p = 0.050",
            "[45589] /opt/llm/llama.cpp/ggml/src/ggml-cuda/ggml-cuda.cu:109: CUDA error",
            "MARKER_STRAY free text from somewhere",
        ):
            with self.subTest(line=line):
                (entry,) = self.module.process([line])
                self.assertEqual((entry.text, entry.level, entry.kind), ("text removed", None, "text_removed"))

    def test_a_blank_line_or_a_bare_router_tag_is_dropped(self) -> None:
        self.assertEqual(self.module.process(["[45589] ", "[45589]", ""]), [])

    def test_blank_lines_after_a_message_do_not_change_what_is_stored(self) -> None:
        line = "0.01.000.001 I srv  update_slots: all slots are idle"
        (plain,) = self.module.process([line])
        (padded,) = self.module.process([line, "[45589] ", "[45589] "])
        self.assertEqual(padded, plain)
        self.assertEqual(plain.kind, "other")

    def test_the_real_crash_backtrace_is_stored_at_error_without_its_text(self) -> None:
        entries = self.module.process(self.router)
        (crash,) = [e for e in entries if e.text == "text removed" and "ggml_abort" in "\n".join(self.router)][:1]
        self.assertEqual((crash.level, crash.kind), ("ERROR", "text_removed"))

    def test_sampler_rows_are_stored_with_the_line_they_continue(self) -> None:
        lines = [
            "0.01.000.001 I slot launch_slot_: id  0 | task -1 | sampler params:",
            "\trepeat_last_n = 64, repeat_penalty = 1.000, frequency_penalty = 0.000, presence_penalty = 0.000",
            "\ttop_k = 20, top_p = 0.950, min_p = 0.050, xtc_probability = 0.000",
            "0.01.000.002 I slot launch_slot_: id  0 | task 1 | processing task, is_child = 0",
        ]
        first, second = self.module.process(lines)
        self.assertEqual((first.level, first.kind, first.text.count("\n")), ("INFO", "other", 2))
        self.assertEqual(second.kind, "task_started")

    def test_real_fixtures_leave_no_entry_without_a_level(self) -> None:
        for name in REAL_SERVER_FIXTURES:
            for entry in self.module.process(fixture_lines(FIXTURES / name)):
                with self.subTest(path=name, entry=entry.text[:100]):
                    self.assertIsNotNone(entry.level)

    def test_the_join_applies_to_this_container_only(self) -> None:
        text = (MODULES / "llm-server.alloy").read_text()
        outer = text.index('selector = "{service=\\"llm-server\\"}"')
        self.assertGreater(text.index("stage.multiline"), outer)


class RouterNoiseTest(unittest.TestCase):
    """The router prints one line per proxied request: about 86,000 a day, none of it information."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = server_pipeline()
        cls.lines = fixture_lines(FIXTURES / "llm_server_router_sample.txt")

    def test_the_proxying_line_is_dropped(self) -> None:
        proxying = [line for line in self.lines if "proxying request to model" in line]
        self.assertGreaterEqual(len(proxying), 5)
        for line in proxying:
            with self.subTest(line=line):
                self.assertEqual(self.module.process([line]), [])

    def test_the_router_lines_that_say_what_happened_to_the_model_are_kept_whole(self) -> None:
        for needle in ("spawning server instance", "stopping model instance", "exited with status 1",
                       "force-killing model instance"):
            line = next(line for line in self.lines if needle in line)
            with self.subTest(needle=needle):
                (entry,) = self.module.process([line])
                self.assertEqual((entry.kind, entry.text.endswith("text removed")), ("other", False))


class TextRemovalTest(unittest.TestCase):
    """Text a line quotes from a request or a reply never reaches storage."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = server_pipeline()
        cls.lines = fixture_lines(FIXTURES / SYNTHETIC_FIXTURE)
        cls.entries = cls.module.process(cls.lines)

    def entry(self, needle: str) -> Entry:
        (found,) = [e for e in self.entries if needle in e.text]
        return found

    def test_no_text_from_a_request_or_reply_reaches_storage(self) -> None:
        self.assertGreater(len(self.entries), 20)
        for entry in self.entries:
            with self.subTest(entry=entry.text[:80]):
                self.assertNotIn("MARKER", entry.text)
                self.assertFalse([v for v in entry.labels.values() if "MARKER" in v])

    def test_the_fixture_does_print_each_marker_so_the_check_above_can_fail(self) -> None:
        markers = set(re.findall(r"MARKER_\w+", "\n".join(self.lines)))
        self.assertGreaterEqual(len(markers), 55)

    def test_quoted_text_that_looks_like_log_lines_is_removed_with_everything_after_it(self) -> None:
        """Model output that quotes llama.cpp logs starts new entries with valid level prefixes."""
        finished = {e.fields["llm_task"] for e in self.entries if e.kind == "finished"}
        self.assertIn("94", finished)  # the real line after the quoted text is still read
        self.assertFalse({"90", "93"} & finished)
        for task in ("90", "93"):
            with self.subTest(task=task):
                found = [e for e in self.entries if e.fields.get("llm_task") == task]
                self.assertEqual([(e.text, e.kind) for e in found],
                                 [(f"slot release: id  1 | task {task} | text removed", "text_removed")])
        idle = self.entry("update_slots: text removed")
        self.assertEqual((idle.level, idle.kind), ("WARN", "text_removed"))
        self.assertTrue([e for e in self.entries if e.text == "text removed" and e.level == "INFO"])

    def test_unparsed_model_output_is_kept_as_the_fact_it_happened(self) -> None:
        for needle, fmt in (("unparsed Content-only output", "Content-only"), ("unparsed peg-native output", "peg-native")):
            with self.subTest(format=fmt):
                found = self.entry(needle)
                self.assertEqual(found.text, f"common_chat_peg_parse: unparsed {fmt} output: text removed")
                self.assertEqual((found.kind, found.level, found.fields), ("output_unparsed", "WARN", {"llm_format": fmt}))

    def test_an_exception_in_a_slot_is_kept_with_its_slot_and_task(self) -> None:
        for task in ("72", "73"):
            with self.subTest(task=task):
                found = self.entry(f"task {task} | got exception")
                self.assertEqual(found.text, f"slot      iterate: id  1 | task {task} | got exception: text removed")
                self.assertEqual(
                    (found.kind, found.level, found.fields), ("request_exception", "ERROR", {"llm_slot": "1", "llm_task": task})
                )

    def test_an_exception_answered_to_the_client_is_kept_without_its_body(self) -> None:
        plain = [e for e in self.entries if e.text.startswith("srv    operator(): got exception")]
        self.assertEqual(len(plain), 2)
        for found in plain:
            self.assertEqual(found.text, "srv    operator(): got exception: text removed")
            self.assertEqual((found.kind, found.level), ("server_exception", "WARN"))
        found = self.entry("got another exception")
        self.assertEqual(found.text, "srv    operator(): got another exception: text removed")
        self.assertEqual((found.kind, found.level), ("server_exception", "ERROR"))

    def test_a_request_error_keeps_the_servers_own_wording_but_not_quoted_text(self) -> None:
        errors = {e.fields["llm_task"]: e for e in self.entries if e.kind == "request_error"}
        for task in ("72", "74", "75", "76"):
            with self.subTest(task=task):
                self.assertEqual(errors[task].fields["llm_error"], "text removed")
        self.assertEqual(
            errors["78"].fields["llm_error"],
            "input (40000 tokens) is larger than the max context size (32768 tokens). skipping",
        )
        self.assertEqual(errors["80"].fields["llm_error"], "Compute error.")

    def test_a_direct_decode_failure_keeps_which_step_failed_and_not_its_text(self) -> None:
        """update_slots prints the exception text of pre_decode, decode and post_decode, which can carry model output."""
        for step in ("pre_decode", "decode", "post_decode"):
            found = [e for e in self.entries if e.text == f"srv  update_slots: {step}() failed: text removed"]
            with self.subTest(step=step):
                self.assertTrue(found)
                self.assertEqual({(e.kind, e.level) for e in found}, {("decode_failed", "ERROR")})
        aborted = self.entry("task id = 91")
        self.assertEqual((aborted.kind, aborted.fields["llm_error"]), ("request_error", "text removed"))

    def test_one_line_warnings_that_quote_names_keep_their_heading_only(self) -> None:
        heads = (
            "Tool call mismatch: ",
            "Ignoring content part type: ",
            "Ignoring non-text content part: ",
            "common_chat_verify_template: failed to apply template: ",
            "common_sampler_types_from_names: unable to match sampler by name ",
            "common_sampler_types_from_chars: unable to match sampler by char ",
        )
        for head in heads:
            with self.subTest(head=head):
                found = next(e for e in self.entries if head in e.text)
                self.assertEqual(found.text, head + "text removed")

    def test_the_system_prompt_printed_for_a_malformed_billing_header_is_removed(self) -> None:
        found = [e for e in self.entries if e.text.startswith("anthropic string not as expected")]
        self.assertEqual(len(found), 4)  # two here and the two in the quoted-text section
        for entry in found:
            self.assertEqual((entry.text, entry.level), ("anthropic string not as expected: text removed", "ERROR"))

    def test_a_grammar_a_failed_sampler_printed_is_removed(self) -> None:
        found = self.entry("error initializing grammar sampler")
        self.assertEqual(found.text, "common_sampler_init: error initializing grammar sampler for grammar: text removed")

    def test_a_log_call_the_module_has_never_seen_keeps_its_heading_and_level_only(self) -> None:
        """The server image is unpinned, so a later release can add a call that quotes text."""
        found = self.entry("srv  future_call:")
        self.assertEqual((found.text, found.level, found.kind), ("srv  future_call: text removed", "WARN", "text_removed"))
        slot_line = self.entry("task 92 | text removed")
        self.assertEqual(
            (slot_line.fields, slot_line.level), ({"llm_slot": "1", "llm_task": "92"}, "INFO")
        )
        bare = [e for e in self.entries if e.text == "text removed" and e.level == "WARN"]
        self.assertTrue(bare)

    def test_model_loader_lines_keep_their_heading_from_a_fixed_set(self) -> None:
        self.assertEqual(self.entry("llama_model_loader").text, "llama_model_loader: text removed")
        self.assertEqual(self.entry("print_info").text, "print_info: text removed")
        template = self.entry("srv  init: text removed")
        self.assertEqual((template.level, template.kind), ("INFO", "text_removed"))

    def test_stderr_grammar_errors_and_conversation_ids_are_dropped(self) -> None:
        for needle in ("error parsing grammar", "conv_id="):
            with self.subTest(needle=needle):
                self.assertFalse([e for e in self.entries if needle in e.text])
                self.assertTrue([line for line in self.lines if needle in line])

    def test_the_line_after_a_multi_line_message_still_parses_as_its_own_entry(self) -> None:
        wanted = {line.split("task ")[1].split(" ")[0] for line in self.lines
                  if "stop processing" in line and "MARKER" not in line and re.match(r"^(\[\d+\] )?\d", line)}
        finished = {e.fields["llm_task"] for e in self.entries if e.kind == "finished"}
        self.assertTrue(finished)
        self.assertLessEqual(finished, wanted)

    def test_real_fixtures_are_not_reduced_except_the_crash_backtraces(self) -> None:
        for name in REAL_SERVER_FIXTURES:
            for entry in self.module.process(fixture_lines(FIXTURES / name)):
                if entry.text == "text removed":
                    self.assertEqual(entry.level, "ERROR")
                else:
                    self.assertFalse(entry.text.endswith("text removed"), entry.text[:80])


class RequestAssemblyTest(unittest.TestCase):
    """One request's lines join on task number and slot, and the figures agree."""

    @classmethod
    def setUpClass(cls) -> None:
        module = server_pipeline()
        parsed = module.process(fixture_lines(FIXTURES / "llm_server_trace_sample.txt"))
        cls.parsed = [p for p in parsed if p.kind in ("prompt", "reuse", "read_timing", "output_timing",
                                                      "total_timing", "full_reread", "finished", "task_started")]

    def request(self, task: str) -> dict[str, dict[str, str]]:
        request: dict[str, dict[str, str]] = {}
        for p in self.parsed:
            if p.fields.get("llm_task") == task:
                request.setdefault(p.kind, p.fields)  # the first cached count is the tokens kept
        return request

    def test_a_forced_re_read_reads_every_prompt_token_and_reuses_none(self) -> None:
        request = self.request("3441")
        self.assertIn("full_reread", request)
        self.assertEqual(request["reuse"]["llm_cached_tokens"], "0")
        self.assertEqual(request["prompt"]["llm_prompt_tokens"], request["read_timing"]["llm_read_tokens"])

    def test_a_reused_request_reads_only_what_the_slot_lacked(self) -> None:
        request = self.request("5398")
        reused = int(request["reuse"]["llm_cached_tokens"])
        read = int(request["read_timing"]["llm_read_tokens"])
        self.assertEqual(reused + read, int(request["prompt"]["llm_prompt_tokens"]))

    def test_total_tokens_are_read_plus_output(self) -> None:
        request = self.request("5398")
        self.assertEqual(
            int(request["total_timing"]["llm_total_tokens"]),
            int(request["read_timing"]["llm_read_tokens"]) + int(request["output_timing"]["llm_output_tokens"]),
        )


class WatcherModule:
    """logging/alloy-modules/llm-watcher.alloy: the JSON paths it reads and the labels it sets."""

    def __init__(self, text: str) -> None:
        paths = re.search(r"stage\.json \{\s*expressions\s*=\s*\{([^}]*)\}", text)
        assert paths, "llm-watcher.alloy has no stage.json"
        self.paths = dict(re.findall(r'(\w+)\s*=\s*"(\w+)"', paths.group(1)))
        labels = re.search(r"stage\.labels \{\s*values\s*=\s*\{([^}]*)\}", text)
        assert labels, "llm-watcher.alloy has no stage.labels"
        self.labels = dict(re.findall(r'(\w+)\s*=\s*"(\w+)"', labels.group(1)))
        self.text = text


def real_watcher_lines(add_cleanup) -> list[str]:
    """Every event the watcher can log, written by the watcher's own code
    driven against its test stand-in for the router (llm/tests/watcher_harness.py)."""
    t0 = at("12:00:00")
    lines: list[str] = []

    def scenario(**settings):
        return Harness(add_cleanup, start=t0, load_profile=QUIET_LOAD, load_seconds=5, **settings)

    def collect(h: Harness) -> None:
        lines.extend(h.log.getvalue().splitlines())

    # Adopted serving; a slot change; a game yields the model; the quiet period resumes it.
    h = scenario(model="loaded")
    h.server.slots[0] = slot(0, 24713, busy=True)
    h.tick(t0 + 1)
    h.server.slots[0] = slot(0, 24713, busy=False)
    for second in range(2, 9):
        h.tick(t0 + second, util=30)
    h.quiet(t0 + 9, t0 + 120)
    collect(h)

    # The model process dies while serving, and the watcher loads it again.
    h = scenario(model="unloaded")
    h.server.lifetimes = [10.0]
    h.quiet(t0 + 1, t0 + 120)
    collect(h)

    # Loads fail until the watcher gives up.
    h = scenario(model="unloaded")
    h.server.failing_loads = 99
    h.quiet(t0 + 1, t0 + 1200)
    collect(h)

    # The Yield button cancels a load in progress; the load was adopted mid-way.
    h = scenario(model="loading")
    h.quiet(t0 + 1, t0 + 3)
    h.watcher.yield_now()
    h.quiet(t0 + 4, t0 + 10)
    collect(h)
    h = scenario(model="loading")
    h.quiet(t0 + 1, t0 + 20)
    collect(h)

    # Something other than the watcher loads the model during a hold, and once the GPU has been quiet for the quiet period.
    h = scenario(model="loaded")
    h.tick(t0 + 1)
    h.clock.now = t0 + 2
    h.watcher.yield_now()
    h.quiet(t0 + 3, t0 + 200)
    h.server.load_elsewhere()
    h.quiet(t0 + 201, t0 + 220)
    collect(h)
    h = scenario(model="unloaded")
    h.server.failing_loads = 1
    h.quiet(t0 + 1, t0 + 69)
    h.server.load_elsewhere()
    h.quiet(t0 + 70, t0 + 100)
    collect(h)

    # The remaining unhealthy reasons: the VRAM limit, a yield that never completes, a silent server, a stalled sampler.
    h = scenario(model="loaded")
    h.gpu.memory_used_mib = 31200
    h.tick(t0 + 1)
    collect(h)
    h = scenario(model="loaded", unload_seconds=3600)
    h.tick(t0 + 1)
    h.clock.now = t0 + 2
    h.watcher.yield_now()
    h.quiet(t0 + 3, t0 + 40)
    collect(h)
    h = scenario(model="loaded", env={"WATCHER_SERVER_SILENT_SECONDS": "10"})
    h.server.slots[0] = slot(0, 52000, busy=False)
    h.tick(t0 + 1)
    h.server.silent = True
    h.quiet(t0 + 2, t0 + 14)
    collect(h)
    h = scenario(model="loaded")
    h.tick(t0 + 1)
    h.clock.now = t0 + 11.5
    h.watcher.end_if_stalled(lambda code: None)
    collect(h)
    return lines


@LINUX_ONLY
class WatcherEventParsingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = WatcherModule((MODULES / "llm-watcher.alloy").read_text())

        cls.lines = real_watcher_lines(cls.addClassCleanup)
        cls.events = [json.loads(line) for line in cls.lines]

    def extracted(self, event: dict) -> dict[str, object]:
        return {name: event[path] for name, path in self.module.paths.items()}

    def test_the_lines_cover_every_event_the_watcher_logs(self) -> None:
        self.assertEqual(
            {event["event"] for event in self.events},
            {"handoff.yield", "handoff.resume", "handoff.resume_abandoned", "slots.changed",
             "state.adopted", "load.failed", "watcher.unhealthy"},
        )

    def test_the_lines_cover_every_unhealthy_reason_and_the_watchdogs_own(self) -> None:
        reasons = {e["reason"] for e in self.events if e["event"] == "watcher.unhealthy"}
        self.assertEqual(
            reasons, {"yield_stuck", "vram_at_limit", "load_given_up", "server_unresponsive", "sample_stale"}
        )

    def test_a_yield_is_triggered_by_a_game_the_button_or_another_client_loading_the_model(self) -> None:
        triggers = {e["trigger"] for e in self.events if e["event"] == "handoff.yield"}
        self.assertEqual(triggers, {"automatic", "button", "external_load"})

    def test_a_resume_for_a_load_already_running_at_start_has_no_quiet_period(self) -> None:
        quiet = [e["quiet_since_ts"] for e in self.events if e["event"] == "handoff.resume"]
        self.assertIn(None, quiet)
        self.assertTrue(any(value is not None for value in quiet))

    def test_adopting_at_start_is_info_and_finding_the_router_in_another_state_is_a_warning(self) -> None:
        adopted = [e for e in self.events if e["event"] == "state.adopted"]
        self.assertEqual({e["level"] for e in adopted if e["previous_state"] is None}, {"info"})
        found = [e for e in adopted if e["previous_state"] is not None]
        self.assertEqual({e["level"] for e in found}, {"warning"})
        self.assertTrue({"serving", "yielded"} <= {e["previous_state"] for e in found})
        for e in adopted:
            self.assertLessEqual({"state", "previous_state", "router_state"}, set(e))

    def test_a_model_that_dies_while_serving_is_a_warning_and_a_failed_load_with_its_exit_code(self) -> None:
        (died,) = [e for e in self.events if e["event"] == "load.failed" and "while serving" in e["error"]]
        self.assertIn("exit", died["error"])
        self.assertEqual(died["level"], "error")

    def test_the_module_comment_names_every_event_the_watcher_logs(self) -> None:
        comment = "\n".join(line for line in self.module.text.splitlines() if line.startswith("//"))
        for event in sorted({e["event"] for e in self.events}):
            with self.subTest(event=event):
                self.assertIn(event, comment)

    def test_the_module_comment_names_every_health_reason_and_trigger(self) -> None:
        comment = "\n".join(line for line in self.module.text.splitlines() if line.startswith("//"))
        names = {e["reason"] for e in self.events if e["event"] == "watcher.unhealthy"}
        names |= {e["trigger"] for e in self.events if e["event"] == "handoff.yield"}
        for name in sorted(names):
            with self.subTest(name=name):
                self.assertIn(name, comment)

    def test_every_event_yields_level_and_event_name(self) -> None:
        for event in self.events:
            with self.subTest(event=event["event"]):
                got = self.extracted(event)
                self.assertIn(got["lvl"], {"info", "warning", "error"})
                self.assertEqual(got["evt"], event["event"])

    def test_the_row_keeps_dockers_receive_time(self) -> None:
        """Container rows are timed by Docker's nanosecond receive time; no parser overrides it."""
        self.assertNotIn("stage.timestamp", self.module.text)
        self.assertNotIn("ts", self.module.paths.values())

    def test_every_event_carries_a_utc_time_in_its_body(self) -> None:
        for event in self.events:
            with self.subTest(event=event["event"]):
                self.assertEqual(datetime.fromisoformat(event["ts"]).utcoffset().total_seconds(), 0)

    def test_event_name_is_the_only_promoted_field_besides_level(self) -> None:
        self.assertEqual(set(self.module.labels), {"detected_level", "llm_event"})

    def test_body_keeps_the_whole_json_line_so_every_event_field_is_queryable(self) -> None:
        self.assertNotIn("stage.output", self.module.text)

    def test_warning_level_is_folded_onto_warn(self) -> None:
        self.assertIn('{{ if eq .Value \\"warning\\" }}WARN{{ else }}', self.module.text)

    def test_the_watcher_logs_no_text_beyond_counts_flags_and_times(self) -> None:
        for line in self.lines:
            self.assertNotIn("prompt", line)


class CaddyAccessRecordTest(unittest.TestCase):
    """The ingress worker's access line: kept whole, with exactly these keys."""

    KEYS = {"level", "ts", "logger", "msg", "client", "session_id", "agent_id", "path", "status", "duration"}

    @classmethod
    def setUpClass(cls) -> None:
        text = (MODULES / "caddy.alloy").read_text()
        gate = re.search(
            rf'stage\.match \{{\s*selector\s*=\s*{STRING}\s*stage\.template \{{\s*source\s*=\s*"line"', text
        )
        assert gate, "caddy.alloy has no gate over its line shaping"
        cls.shaping_selector = alloy_string(gate.group(1))
        cls.lines = (FIXTURES / "caddy_llm_access_sample.jsonl").read_text().splitlines()

    def test_the_fixture_has_the_keys_the_ingress_worker_logs(self) -> None:
        for line in self.lines[:3]:
            keys = set(json.loads(line))
            with self.subTest(line=line[:80]):
                self.assertLessEqual(self.KEYS, keys)
                self.assertLessEqual(keys, self.KEYS | {"caller"})

    def test_remote_lines_carry_the_caller_and_local_ones_do_not(self) -> None:
        remote, subagent, local = (json.loads(line) for line in self.lines[:3])
        self.assertEqual(remote["logger"], "http.log.access.llm_remote")
        self.assertEqual(remote["caller"], "nathan@nathanbaxter.com")
        self.assertEqual(remote["agent_id"], "")
        self.assertTrue(subagent["agent_id"])
        self.assertEqual(local["logger"], "http.log.access.llm_local")
        self.assertNotIn("caller", local)

    def test_both_access_loggers_keep_their_whole_json_line(self) -> None:
        for line in self.lines[:3]:
            with self.subTest(logger=json.loads(line)["logger"]):
                self.assertFalse(selector_passes(self.shaping_selector, line))

    def test_other_caddy_lines_are_still_reduced_to_logger_and_message(self) -> None:
        self.assertTrue(selector_passes(self.shaping_selector, self.lines[3]))


class ChainWiringTest(unittest.TestCase):
    def test_both_modules_are_chained_once_and_the_chain_still_ends_at_its_output(self) -> None:
        chain = (MODULES / "chain.alloy").read_text()
        for name in ("llm_server", "llm_watcher"):
            with self.subTest(module=name):
                self.assertEqual(len(re.findall(rf'^\s*{name} "run"', chain, re.M)), 1)
                self.assertEqual(len(re.findall(rf"\[{name}\.run\.receiver\]", chain)), 1)
        self.assertRegex(chain, r'llm_watcher "run" \{ forward_to = argument\.forward_to\.value \}')

    def test_each_module_declares_what_the_chain_calls(self) -> None:
        for file, name in (("llm-server.alloy", "llm_server"), ("llm-watcher.alloy", "llm_watcher")):
            with self.subTest(module=name):
                self.assertIn(f'declare "{name}"', (MODULES / file).read_text())

    def test_each_module_only_touches_its_own_container(self) -> None:
        for file, service in (("llm-server.alloy", "llm-server"), ("llm-watcher.alloy", "llm-watcher")):
            with self.subTest(module=file):
                text = (MODULES / file).read_text()
                self.assertIn(f'selector = "{{service=\\"{service}\\"}}"', text)
                self.assertNotIn('service=\\"caddy\\"', text)


class CaddyAccessLogTest(unittest.TestCase):
    def test_access_log_lines_keep_their_json_body(self) -> None:
        """Reducing an access line to "logger: msg" would drop caller, status and duration."""
        text = (MODULES / "caddy.alloy").read_text()
        gate = re.search(
            rf'stage\.match \{{\s*selector\s*=\s*{STRING}\s*stage\.template \{{\s*source\s*=\s*"line"', text
        )
        self.assertIsNotNone(gate, "line shaping must sit under a selector of its own")
        self.assertEqual(
            alloy_string(gate.group(1)), '{service="caddy"} != "\\"logger\\":\\"http.log.access"'
        )


class StackLogLevelTest(unittest.TestCase):
    """The model server must log request detail without printing request text."""

    def stack_text(self) -> str:
        return (ROOT / "llm" / "compose.yaml").read_text() + (ROOT / "llm" / "server" / "models.ini").read_text()

    def stack_settings(self) -> str:
        """The stack files without comment lines, which may name a switch to warn against it."""
        return "\n".join(
            line for line in self.stack_text().splitlines() if not line.lstrip().startswith((";", "#"))
        )

    VERBOSITY_FOUR = re.compile(
        r"(?m)^\s*(LLAMA_ARG_LOG_VERBOSITY\s*[:=]\s*[\"']?4[\"']?|(log-)?verbosity\s*=\s*4)\s*$"
    )

    def test_the_server_logs_at_the_level_that_prints_slot_choice_and_reuse(self) -> None:
        """Slot choice and reuse are printed only at verbosity 4; the default 3 omits prompt size, tokens reused and forced re-reads."""
        self.assertRegex(self.stack_settings(), self.VERBOSITY_FOUR)

    def test_only_verbosity_four_is_accepted_because_five_prints_request_and_reply_bodies(self) -> None:
        """Verbosity 5 prints the full model output on a parse error and the request body; 3 omits what the telemetry reads."""
        for setting in ("4", '"4"', "'4'"):
            with self.subTest(accepted=setting):
                self.assertRegex(f"      LLAMA_ARG_LOG_VERBOSITY: {setting}\n", self.VERBOSITY_FOUR)
        for setting in ("3", "5", "45", "40", '"5"', "4.5", "14"):
            with self.subTest(rejected=setting):
                self.assertNotRegex(f"      LLAMA_ARG_LOG_VERBOSITY: {setting}\n", self.VERBOSITY_FOUR)
        self.assertNotRegex("verbosity = 45\n", self.VERBOSITY_FOUR)
        self.assertRegex("log-verbosity = 4\n", self.VERBOSITY_FOUR)

    def test_the_server_never_runs_with_the_slot_debug_switch(self) -> None:
        """With it set the server prints the prompt text around a cache mismatch, at warning level."""
        self.assertNotIn("LLAMA_SERVER_SLOTS_DEBUG", self.stack_settings())
        self.assertNotIn("LLAMA_SERVER_SLOTS_N_DIFF", self.stack_settings())


if __name__ == "__main__":
    unittest.main()
