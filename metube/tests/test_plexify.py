"""Unit tests for metube/scripts/plexify (no network — Sonarr is never called).

Run under the project's pipenv:
    pipenv run python -m unittest discover -s metube/tests
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
import unittest.mock
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
LeftoverFile = MODULE.LeftoverFile
select_episode = MODULE.select_episode
assign_batch = MODULE.assign_batch
token_fit = MODULE.token_fit
batch_done = MODULE.batch_done
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


# TheTVDB titles for Space Racers (series 282447), fetched from Sonarr's
# skyhook proxy (docs/plans/metube.md, "Batch matching: the second pass").
# Season 2 is included as noise the token rule must not collide with,
# proving the strict-fail set below is stable even against a second
# season's worth of unrelated titles.
SPACE_RACERS_S1_TITLES = [
    "Where Are We?", "Starling, D.S.V.", "Total Eclipse", "Fly Like an Eagle",
    "Star Signs", "Vulture's Volcano", "Mars Canyon Race", "Election!",
    "Ace Space Reporter", "Above and Beyond", "Eyes on the Prize",
    "Mine, Mine, Mine!", "Asteroids, Platinum Edition", "Lunar Base Blackout",
    "Cranberry Crater", "Dodo in Distress", "Sick Day", "Good Old Coot",
    "Robyn's Winter Break", "Three's a Crowd", "Mars Map Mystery",
    "Sweet Spot", "Careering off Course", "Drifting", "Hawk's Day",
    "Satellite Starling", "Fearless Flyers", "Hawk's Valentine",
    "Space Racer Storm Chaser", "(N)ice Work if You Can Get It",
    "A Simple Re-Quest", "Hiding on Hyperion", "RoboCoach XL-5",
    "Trail Blazers", "Dome Grown", "Dance Lessons", "Grounded",
    "Here Comes the Sun", "Starling: Space Racer!", "Titanic Trip",
    "Starling Discovers the Moon", "Three Racers and a Baby Robot",
    "A Tight Squeeze", "AVA Retires", "Vulture's Statue", "Follow The Water",
    "Watch this Space", "The Hawk Factor", "Hawk's On It",
    "Communication Breakdown",
]
SPACE_RACERS_S2_TITLES = [
    "The Haunted Asteroid", "Satellite Songs", "Different", "Paint Your Rocket",
    "Cadet Dodo", "Great Balls of Fuel", "Loon on the Moon", "Dodo in Charge",
    "To Tell The Truth", "Sneezy Does It", "When You Wish Upon a Comet",
    "Sit, Rover, Sit", "Little Rocket Who Cried Aliens", "Goodbye",
    "How the Grouch Stole Solstice", "Some Body for AVA", "Something Borrowed",
    "Orange Outrage", "Return To Sender", "The Happiest Rocket In The World",
    "Counter-Earth", "Star Power", "The Wizard Of Mars", "Them's The Brakes",
    "Volunteer Day", "Remember The Past", "New Cadet On The Block",
    "Dream Big", "It's A Mad, Mad, Mad, Mad Galaxy", "That'll Teach You",
    "Double-O Dodo", "First Do No Harm", "Stardust Rhythm",
    "M Is For Meteorite", "When the Envy Bug Bites", "Ships in a Bottle",
    "The Rocket with Two Brains", "Hawk the Genius", "Space Girl Explorers",
    "Polar Opposites",
]

# The 42 Space Racers season-1 YouTube titles as MeTube reported them.
# Verified against the strict pass (select_episode): exactly these four
# don't confidently resolve on their own — each is one word of slack over
# the real episode title — and are what the batch sweep's token rule must
# place. (An initial design note guessed five misses; running the actual
# fixture through the actual code found four, and the plan text was
# corrected to match.)
SPACE_RACERS_STRICT_MISSES = [
    "SPACE RACERS: Mars Canyon Race Space",
    "SPACE RACERS: A Simple Re-Quest Space",
    "SPACE RACERS: Above and Beyond Space",
    "SPACE RACERS: The Sweet Spot",
]
SPACE_RACERS_S1_YOUTUBE_TITLES = [
    "SPACE RACERS: Hawk's Day", "SPACE RACERS: Where Are We?", "SPACE RACERS: Election",
    "SPACE RACERS: (N)ice Work if You Can Get It", "SPACE RACERS: Three's a Crowd",
    "SPACE RACERS: Communication Breakdown", "SPACE RACERS: Mars Canyon Race Space",
    "SPACE RACERS: Space Racer Storm Chaser", "SPACE RACERS: Fly Like an Eagle",
    "SPACE RACERS: Mars Map Mystery", "SPACE RACERS: A Simple Re-Quest Space",
    "SPACE RACERS: Grounded", "SPACE RACERS: Total Eclipse", "SPACE RACERS: Satellite Starling",
    "SPACE RACERS: Vulture's Statue", "SPACE RACERS: Starling Discovers The Moon",
    "SPACE RACERS: Asteroids, Platinum Edition", "SPACE RACERS: Above and Beyond Space",
    "SPACE RACERS: Star Signs", "SPACE RACERS: Careering Off Course",
    "SPACE RACERS: The Hawk Factor", "SPACE RACERS: Dome Grown", "SPACE RACERS: Trail Blazers",
    "SPACE RACERS: Titanic Trip", "SPACE RACERS: The Sweet Spot", "SPACE RACERS: Vulture's Volcano",
    "SPACE RACERS: Starling D.S.V.", "SPACE RACERS: Hiding on Hyperion",
    "SPACE RACERS: Starling: Space Racer!", "SPACE RACERS: AVA Retires",
    "SPACE RACERS: Cranberry Crater", "SPACE RACERS: Fearless Flyers",
    "SPACE RACERS: Hawk's Valentine", "SPACE RACERS: Sick Day", "SPACE RACERS: Hawks On It",
    "SPACE RACERS: Robyn's Winter Break", "SPACE RACERS: Good Old Coot",
    "SPACE RACERS: Dodo in Distress", "SPACE RACERS: Drifting",
    "SPACE RACERS: Here Comes the Sun", "SPACE RACERS: Follow the Water",
    "SPACE RACERS: Watch This Space",
]


def space_racers_episodes() -> list[Episode]:
    episodes = [
        Episode(id=100 + n, title=t, season_number=1, episode_number=n)
        for n, t in enumerate(SPACE_RACERS_S1_TITLES, start=1)
    ]
    episodes += [
        Episode(id=200 + n, title=t, season_number=2, episode_number=n)
        for n, t in enumerate(SPACE_RACERS_S2_TITLES, start=1)
    ]
    return episodes


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

    def test_episode_title_containing_a_delimiter_survives_prefix_removal(self) -> None:
        episodes = [
            Episode(1, "Starling: Space Racer!", 1, 39),
            Episode(2, "Starling, D.S.V.", 1, 2),
            Episode(3, "Space Racer Storm Chaser", 1, 29),
        ]
        match = select_episode("SPACE RACERS: Starling: Space Racer!", episodes)
        self.assertEqual(match.title, "Starling: Space Racer!")

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


class ShowNameResolutionTest(unittest.TestCase):
    """resolve_show_name: the staging folder wins when the family chose
    one; a file dropped directly in staging (no folder) falls back to the
    video's yt-dlp %(channel)s — which for these kids' shows is the show
    name itself — and a channel of "NA" (yt-dlp's literal rendering of a
    missing field) with no folder either fails loudly."""

    def test_channel_is_the_show_when_the_file_has_no_folder(self) -> None:
        show = MODULE.resolve_show_name(Path("SPACE RACERS The Haunted Asteroid.mp4"), "Space Racers")
        self.assertEqual(show, "Space Racers")

    def test_folder_wins_over_channel_when_both_are_present(self) -> None:
        show = MODULE.resolve_show_name(
            Path("Skillsville/Skillsville FULL EPISODE - Chef.mp4"), "SomeOtherChannel",
        )
        self.assertEqual(show, "Skillsville")

    def test_na_channel_with_no_folder_fails_loudly(self) -> None:
        with self.assertRaisesRegex(PlexifyError, "no channel and no folder"):
            MODULE.resolve_show_name(Path("Some Video.mp4"), MODULE.NO_CHANNEL)


class NewSeriesEpisodeWaitTest(unittest.TestCase):
    class SonarrStub:
        def __init__(self, answers: list[list]) -> None:
            self.answers = answers
            self.calls = 0

        def episodes_for(self, series_id: int) -> list:
            self.calls += 1
            return self.answers.pop(0)

    def test_waits_until_sonarr_has_fetched_the_episode_list(self) -> None:
        stub = self.SonarrStub([[], [], [Episode(1, "Where Are We?", 1, 1)]])
        with unittest.mock.patch.object(MODULE.time, "sleep"):
            MODULE.wait_for_episodes(stub, MODULE.Series(2, "Space Racers", 282447))
        self.assertEqual(stub.calls, 3)

    def test_fails_loud_when_the_episode_list_never_arrives(self) -> None:
        stub = self.SonarrStub([[] for _ in range(100)])
        with unittest.mock.patch.object(MODULE.time, "sleep"), \
                unittest.mock.patch.object(MODULE, "IMPORT_POLL_TIMEOUT_S", 0):
            with self.assertRaises(PlexifyError):
                MODULE.wait_for_episodes(stub, MODULE.Series(2, "Space Racers", 282447))


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


class BatchDoneTest(unittest.TestCase):
    """batch_done: the Exec postprocessor runs inside yt-dlp's own
    postprocessing chain, before MeTube moves that same download from
    `queue` to `done` — so a lone download's own hook invocation always
    finds its own entry still "queued". A bare "is the queue empty"
    check would never fire the sweep from inside a batch; this is what
    the real fix checks instead."""

    def test_empty_queue_is_done(self) -> None:
        self.assertTrue(batch_done([], "SPACE RACERS: Cadet Dodo"))

    def test_queue_with_only_this_invocations_own_title_is_done(self) -> None:
        queue = [{"title": "SPACE RACERS: Cadet Dodo", "status": "finished"}]
        self.assertTrue(batch_done(queue, "SPACE RACERS: Cadet Dodo"))

    def test_queue_with_another_entry_is_not_done(self) -> None:
        queue = [
            {"title": "SPACE RACERS: Cadet Dodo", "status": "finished"},
            {"title": "SPACE RACERS: Different", "status": "downloading"},
        ]
        self.assertFalse(batch_done(queue, "SPACE RACERS: Cadet Dodo"))


class StagedFilesTest(unittest.TestCase):
    """Regression: the `.podhaus-share-mounted` healthcheck sentinel lives
    directly at STAGING_ROOT (metube/compose.yaml's healthcheck), and an
    earlier draft of the sweep's staging-root scan treated it as a
    leftover file forever — permanently failing the sweep."""

    def test_dotfiles_are_never_staged_files(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".podhaus-share-mounted").touch()
            (root / "real-video.mp4").touch()
            names = [p.name for p in MODULE._staged_files(root)]
            self.assertEqual(names, ["real-video.mp4"])


class TokenFitTest(unittest.TestCase):
    def test_one_extra_trailing_word_fits(self) -> None:
        self.assertTrue(token_fit("SPACE RACERS: Mars Canyon Race Space", "Mars Canyon Race"))

    def test_one_extra_leading_word_fits(self) -> None:
        self.assertTrue(token_fit("SPACE RACERS: The Sweet Spot", "Sweet Spot"))

    def test_two_extra_words_does_not_fit(self) -> None:
        self.assertFalse(token_fit("SPACE RACERS: Mars Canyon Race Space Rally", "Mars Canyon Race"))

    def test_unrelated_title_does_not_fit(self) -> None:
        self.assertFalse(token_fit("SPACE RACERS: Grounded", "Sweet Spot"))


class SpaceRacersBatchFixtureTest(unittest.TestCase):
    """The 42-title Space Racers season-1 fixture (docs/plans/metube.md,
    "Batch matching: the second pass") run through the strict pass, then
    the sweep, matching the real end-to-end behaviour: strict placements
    consume their episodes first, and only the leftover four are left for
    the token rule."""

    def test_strict_pass_leaves_exactly_the_four_known_misses(self) -> None:
        episodes = space_racers_episodes()
        misses = []
        for title in SPACE_RACERS_S1_YOUTUBE_TITLES:
            try:
                select_episode(title, episodes)
            except PlexifyError:
                misses.append(title)
        self.assertEqual(sorted(misses), sorted(SPACE_RACERS_STRICT_MISSES))

    def test_sweep_places_all_four_misses_to_the_right_numbers(self) -> None:
        episodes = space_racers_episodes()
        # Episodes the strict pass placed are no longer "unplaced" by the
        # time the sweep runs; only the four misses' episodes remain, plus
        # every episode never uploaded at all (the sweep's real-world noise).
        strict_placed_numbers = {
            select_episode(t, episodes).episode_number
            for t in SPACE_RACERS_S1_YOUTUBE_TITLES
            if t not in SPACE_RACERS_STRICT_MISSES
        }
        unplaced = [e for e in episodes if e.season_number != 1 or e.episode_number not in strict_placed_numbers]
        files = [LeftoverFile(name=f"{t}.mp4", title=t) for t in SPACE_RACERS_STRICT_MISSES]

        assignment = assign_batch(files, unplaced)

        self.assertEqual(assignment.leftover_files, [])
        placed = {p.file.title: p.episode.title for p in assignment.pairs}
        self.assertEqual(placed["SPACE RACERS: Mars Canyon Race Space"], "Mars Canyon Race")
        self.assertEqual(placed["SPACE RACERS: A Simple Re-Quest Space"], "A Simple Re-Quest")
        self.assertEqual(placed["SPACE RACERS: Above and Beyond Space"], "Above and Beyond")
        self.assertEqual(placed["SPACE RACERS: The Sweet Spot"], "Sweet Spot")


class BatchAssignmentTest(unittest.TestCase):
    def test_quantum_plumber_batch_places_plumber_and_leaves_quantum_plumber(self) -> None:
        # "Plumber" is the real episode. By the time the sweep runs,
        # "Skillsville FULL EPISODE | Plumber" would already have been
        # placed by its own strict pass and dropped from both staging and
        # the unplaced-episode list — this proves the assignment function
        # itself resolves the ambiguity the same way, as a defence in depth.
        plumber = Episode(1, "Plumber", 1, 28)
        files = [
            LeftoverFile("Quantum Plumber.mp4", "Skillsville FULL EPISODE | Quantum Plumber"),
            LeftoverFile("Plumber.mp4", "Skillsville FULL EPISODE | Plumber"),
        ]
        assignment = assign_batch(files, [plumber])
        self.assertEqual([(p.file.name, p.episode.title) for p in assignment.pairs], [("Plumber.mp4", "Plumber")])
        self.assertEqual([f.name for f in assignment.leftover_files], ["Quantum Plumber.mp4"])

    def test_two_leftovers_fitting_one_episode_leaves_both(self) -> None:
        episode = Episode(1, "Mars Canyon Race", 1, 7)
        files = [
            LeftoverFile("a.mp4", "SPACE RACERS: Mars Canyon Race Space"),
            LeftoverFile("b.mp4", "SPACE RACERS: Mars Canyon Race Extra"),
        ]
        assignment = assign_batch(files, [episode])
        self.assertEqual(assignment.pairs, [])
        self.assertEqual({f.name for f in assignment.leftover_files}, {"a.mp4", "b.mp4"})

    def test_a_leftover_fitting_two_episodes_stays(self) -> None:
        episodes = [Episode(1, "Mars Canyon Race", 1, 7), Episode(2, "Canyon Race Rally", 1, 8)]
        files = [LeftoverFile("c.mp4", "SPACE RACERS: Mars Canyon Race Rally")]
        assignment = assign_batch(files, episodes)
        self.assertEqual(assignment.pairs, [])
        self.assertEqual([f.name for f in assignment.leftover_files], ["c.mp4"])


if __name__ == "__main__":
    unittest.main()
