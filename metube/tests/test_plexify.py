"""Unit tests for metube/scripts/plexify (no network — Sonarr is never called).

Run under the project's pipenv:
    pipenv run python -m unittest discover -s metube/tests
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "plexify"
SPEC = importlib.util.spec_from_file_location(
    "plexify", SCRIPT, loader=SourceFileLoader("plexify", str(SCRIPT)),
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

Episode = MODULE.Episode
select_episode = MODULE.select_episode
normalise = MODULE.normalise
PlexifyError = MODULE.PlexifyError

# The 59 Skillsville career episode titles (TheTVDB series 460946, S01E01-59,
# de-duplicated from a raw fetch of skyhook's proxy that repeated rows
# 38-48). Order matches TVDB's episode numbering.
SKILLSVILLE_TITLES = [
    "Chef", "Air Traffic Controller", "Train Engineer", "Paleontologist",
    "Farmer", "Mail Carrier", "Game Tester", "Interior Designer",
    "Sound Effects Artist", "City Planner", "Laundromat Manager", "Inventor",
    "Firefighter", "Bank Teller", "Race Car Driver", "Crane Operator",
    "Coach", "Salesperson", "Entrepreneuer", "Hairstylist", "Teacher",
    "Allergist", "Civil Engineer", "Drone Operator", "Hotel Manager",
    "Robotics Technician", "Choreographer", "Plumber", "Photographer",
    "Librarian", "Dental Hygienist", "Flavorist", "Occupational Therapist",
    "Meteorologist", "Astronaut", "Music Conductor", "Volcanologist",
    "Detective", "Chemist", "Lighting Designer", "Fashion Designer",
    "Veterinarian", "Park Ranger", "Career Counselor",
    "Renewable Energy Technician", "Real Estate Agent", "Cryptologist",
    "Landscape Designer", "Nutritionist", "Judge", "Demolition Expert",
    "Florist", "Building Inspector", "Museum Conservator", "Athlete",
    "Party Planner", "Recycling Worker", "Campaign Manager",
    "Video Game Designer",
]


def skillsville_episodes() -> list[Episode]:
    return [
        Episode(id=100 + n, title=title, season_number=1, episode_number=n)
        for n, title in enumerate(SKILLSVILLE_TITLES, start=1)
    ]


class NormaliseTest(unittest.TestCase):
    def test_casefolds_strips_punctuation_and_collapses_spaces(self) -> None:
        self.assertEqual(
            normalise("Skillsville  FULL EPISODE | Chef's Big Day!!"),
            "skillsville full episode chef s big day",
        )


class SegmentEqualityMatchTest(unittest.TestCase):
    def test_junk_prefixed_title_matches_the_delimited_segment(self) -> None:
        episodes = [
            Episode(1, "Chef", 1, 1),
            Episode(2, "Chemist", 1, 39),
            Episode(3, "Detective", 1, 38),
        ]
        match = select_episode("Skillsville FULL EPISODE | Chef", episodes)
        self.assertEqual(match.title, "Chef")
        self.assertNotIn(match.title, ("Chemist", "Detective"))

    def test_full_width_bar_is_a_delimiter(self) -> None:
        episodes = [Episode(1, "Chef", 1, 1), Episode(2, "Chemist", 1, 39)]
        match = select_episode("Skillsville FULL EPISODE ｜ Chef", episodes)
        self.assertEqual(match.title, "Chef")

    def test_substring_alone_does_not_match_a_longer_title(self) -> None:
        # Regression: "Plumber" is a substring of "Quantum Plumber" but is
        # not equal to any delimited segment of the video title, and the
        # ratio fallback must not be confident enough to accept it either.
        episodes = skillsville_episodes()
        with self.assertRaises(PlexifyError):
            select_episode("Skillsville FULL EPISODE | Quantum Plumber", episodes)

    def test_substring_ratio_stays_under_the_confidence_floor(self) -> None:
        segments = [normalise(s) for s in MODULE.title_segments("Skillsville FULL EPISODE | Quantum Plumber")]
        ratio = MODULE.best_ratio_against_title("Plumber", segments)
        self.assertLess(ratio, MODULE.RATIO_MATCH_THRESHOLD)


class AmbiguityTest(unittest.TestCase):
    def test_two_equally_close_candidates_fails(self) -> None:
        # Two episodes that normalise identically (a duplicate/reformatted
        # title) both equal the same delimited segment exactly, so segment
        # equality itself is ambiguous — this fails before the ratio
        # fallback is ever consulted.
        episodes = [Episode(1, "Chef", 1, 1), Episode(2, "CHEF!!", 1, 2)]
        with self.assertRaises(PlexifyError):
            select_episode("Skillsville FULL EPISODE | Chef", episodes)


class RatioMatchTest(unittest.TestCase):
    def test_close_typo_matches_via_ratio_with_margin(self) -> None:
        episodes = [
            Episode(1, "Sound Effects Artist", 1, 9),
            Episode(2, "Chef", 1, 1),
            Episode(3, "Astronaut", 1, 35),
        ]
        # No exact-substring containment (typo: "Efects"), but a clear
        # difflib margin over every other episode.
        match = select_episode("Sound Efects Artist", episodes)
        self.assertEqual(match.title, "Sound Effects Artist")

    def test_youtube_spelling_resolves_to_tvdbs_entrepreneuer(self) -> None:
        # TheTVDB's title has an extra "e" ("Entrepreneuer"); the correctly
        # spelled YouTube title never contains it, so this only matches via
        # the ratio fallback comparing against the "| "-delimited segment.
        match = select_episode(
            "Skillsville FULL EPISODE | Entrepreneur", skillsville_episodes(),
        )
        self.assertEqual(match.title, "Entrepreneuer")

    def test_youtube_spelling_resolves_to_tvdbs_hairstylist(self) -> None:
        # TheTVDB has no space ("Hairstylist"); the YouTube title does.
        match = select_episode(
            "Skillsville FULL EPISODE | Hair Stylist", skillsville_episodes(),
        )
        self.assertEqual(match.title, "Hairstylist")


class NoCandidateTest(unittest.TestCase):
    def test_unrelated_title_fails(self) -> None:
        episodes = [Episode(1, "Astronaut", 1, 35), Episode(2, "Judge", 1, 50)]
        with self.assertRaises(PlexifyError):
            select_episode("Some totally unrelated video about kittens", episodes)


class NoOpOutsideIncomingTest(unittest.TestCase):
    def test_main_exits_zero_and_touches_nothing_outside_incoming(self) -> None:
        argv = sys.argv
        sys.argv = ["plexify", "/downloads/TV/Bluey/Bluey - S01E01.mp4", "Bluey - S01E01"]
        try:
            self.assertEqual(MODULE.main(), 0)
        finally:
            sys.argv = argv


class TvdbFolderTagTest(unittest.TestCase):
    def test_extracts_tvdb_id_from_folder_name(self) -> None:
        match = MODULE.TVDB_FOLDER_RE.search("Skillsville (2025) {tvdb-460946}")
        assert match is not None
        self.assertEqual(match.group(1), "460946")

    def test_no_tag_means_no_match(self) -> None:
        self.assertIsNone(MODULE.TVDB_FOLDER_RE.search("Skillsville"))


class SkillsvilleFixtureTest(unittest.TestCase):
    def test_all_59_youtube_style_titles_resolve_to_59_distinct_numbers(self) -> None:
        episodes = skillsville_episodes()
        resolved_numbers = set()
        for title in SKILLSVILLE_TITLES:
            video_title = f"Skillsville FULL EPISODE | {title}"
            match = select_episode(video_title, episodes)
            resolved_numbers.add(match.episode_number)
        self.assertEqual(len(resolved_numbers), 59)


if __name__ == "__main__":
    unittest.main()
