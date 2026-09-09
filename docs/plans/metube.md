# MeTube for Plex (kids' TV from the web)

## Goal

A page on `metube.pod.haus` where anyone in the family pastes a video, playlist
or channel URL and the result lands on Pouch named so Plex's Kids library plays
it as a show with numbered episodes, with no hand renaming.

## What the research settled

- **Skillsville lives only on YouTube** (`@SkillsvilleOfficial`, 59 uploads titled
  `Skillsville FULL EPISODE | <Career>`). pbskids.org has dropped the show and
  blocks yt-dlp; pbs.org is US-only.
- **YouTube extraction needs yt-dlp's remote JS solver** (`remote_components:
  ["ejs:github"]`) or every video fails with "not available". MeTube ships the
  deno runtime but never sets the option; it goes in `YTDL_OPTIONS`.
- **The episode number exists nowhere yt-dlp can see** — not in title, description,
  JSON metadata, and the channel playlist is out of order. TheTVDB (series 460946)
  numbers the 59 single-career segments S01E01..E59 and its titles match the
  YouTube careers exactly, bar two spellings ("Entrepreneuer", "Hairstylist").
  TMDB numbers 15 paired half-hours, and Plex's TV agent defaults to TMDB order,
  so the library (or the series) must be set to **TheTVDB episode ordering**.
- **`YTDL_OPTIONS` overrides MeTube's UI** (MeTube splats it last), so `format`
  stays out of it and the codec preference goes in `format_sort`, which MeTube
  never touches. `parse_metadata` as a JSON key is silently ignored; the
  `MetadataFromField` postprocessor is the working JSON form.
- **AV1**: every Skillsville rung is AV1-in-MP4; 1080p24 at ~0.85–1.1 Mbps
  (76–98 MiB per 12.5 min episode) vs ~1.7–2.3 Mbps H.264. Nathan chose AV1.
  bilby (M1, software only) transcodes AV1→H.264 at 9.9× real time, measured on
  a real episode clip, so a client without AV1 decode costs ~0.4 core.

## Approach

MeTube downloads; Sonarr numbers and files; Gatus tells Fenwick when a file
could not be placed. Sonarr is chosen because its metadata proxy fronts the
same TheTVDB list Plex's TheTVDB ordering reads, with no key and no
subscription, and it is open source and team-maintained. The deep dive
measured the alternatives across twelve segment-style kids' shows: IMDb's
numbering matched TheTVDB for two, TVmaze for seven of eleven with no
Skillsville, TheTVDB's free key is an unanswered sales queue, FileBot is a
closed single-developer tool. Sonarr's manual import was proven on bandicoot:
a file named only with a YouTube title plus an explicit episode id came out as
`Season 1/Skillsville - S01E01 - Chef`.

### MeTube (built)

| Concern | Decision | Why |
|---|---|---|
| Host | bandicoot | Download + remux is CPU/scratch work; bilby keeps Plex and only reads the result |
| Stack | `metube/` linked-repo stack, `scripts/` bound from the deploy clone like Plex's | Fleet shape |
| Downloads | `/mnt/pouch/Kids/_incoming` at `/downloads` (staging only, never the library root); NVMe `TEMP_DIR` and `STATE_DIR` under `/var/lib/metube` | Everything MeTube writes is staging; the folder picker offers the staged show folders; nothing half-written on the NAS |
| Format | `format_sort: ["res","vcodec:av01","acodec:m4a"]`, MP4 merge, thumbnail embedded, JS solver on; no `format` key | AV1 (Nathan's choice; bilby transcodes it at 9.9× if a client cannot), UI quality picker keeps working |
| Ingress | `metube.pod.haus`: DNS, Pomerium family route, bilby Caddy → 10.0.0.90:8081 | Moved-service pattern |
| Monitoring / backup | Gatus `MeTube` (Media); Backrest bandicoot `metube` plan for the queue state | Media itself is not backed up |

### Naming: Sonarr as the engine

| Concern | Decision | Why |
|---|---|---|
| Staging | MeTube's `/downloads` bind is `_incoming` itself (`/mnt/pouch/Kids/_incoming`), outside every Plex library root. The family picks a show folder in MeTube's folder picker, or types one; picking none falls back to the video's `%(channel)s`, which for these kids' shows is the show name itself | Defaults land in the right spot with no folder needed; a picker folder still overrides the channel |
| Sonarr stack | `sonarr/` on bandicoot: `lscr.io/linuxserver/sonarr` pinned, `/var/lib/sonarr` config (managed dir, 1000:100), `/mnt/pouch/Kids:/kids` (the whole share — staging and library both, since MeTube's own bind is now scoped to the `_incoming` subtree), root folder `/kids/TV`, LAN port 8989, `label:disable`, `mem_limit`, healthcheck `/ping` | Same shape as MeTube; Sonarr sees staging and library under one bind |
| Sonarr auth | `SONARR__AUTH__METHOD=External`; API key set from the vault (`SONARR__AUTH__APIKEY`) | Pomerium is the front door and the LAN is trusted, as for MeTube; the key is shared with the hook |
| Sonarr settings | Rename Episodes on; series folder `{Series TitleYear} {tvdb-{TvdbId}}`; season folder `Season {season:00}`; episode `{Series TitleYear} - S{season:00}E{episode:00} - {Episode CleanTitle}`; no indexers, no download clients; series added unmonitored; Plex connection if a Plex token is in the vault | Plex's naming guide; Sonarr never searches for anything; Plex learns of new files on import |
| Secret | 1Password item `Sonarr API` (Homelab) → komodo-op variable `OP__KOMODO__SONARR_API__CREDENTIAL`, used by both stacks | Existing secret pattern |
| Hook | `metube/scripts/plexify FILE TITLE CHANNEL`, yt-dlp `Exec` postprocessor `after_move`, Python stdlib. Show name is the staging folder when there is one, else the channel argument; a channel of `NA` (yt-dlp's literal for a missing field) with no folder fails loudly. Find the series in Sonarr by show name (a `{tvdb-N}` tag wins; else an exact normalised title match in Sonarr's lookup, added unmonitored if absent), fetch episodes, match the title (normalised episode title contained in the normalised video title, exactly one candidate; else difflib ratio ≥ 0.9 with a clear margin over the runner-up; else fail), then `ManualImport` with explicit `episodeIds`, quality WEBDL-1080p, poll the command, and confirm the file has left staging | The number is Sonarr's; the confidence rule is ours. Sonarr reports success on an import with no episode chosen, so the guard is in the hook before the call and the after-check catches a silent no-op |
| Fail loudly | Gatus external endpoint `metube_plexify` (Media), brinno's heartbeat pattern: the hook posts `success=false&error=…` on any failure and `success=true` on each placement; Gatus alerts route to Fenwick → Signal | Nathan's requirement: a non-match must reach him |
| Sonarr ingress | `sonarr.pod.haus`: DNS, Pomerium route on the Nathan-only policy the other admin tools use, bilby Caddy → 10.0.0.90:8989; Gatus `Sonarr` check; Backrest `sonarr` plan for `/var/lib/sonarr` | Admin tool, not family |
| Plex | Library episode ordering set to TheTVDB (Nathan, once) | Plex's TMDB default has 15 paired Skillsville episodes |

Rejected: a per-show map (Skillsville only), IMDb datasets (2 of 12 shows),
TVmaze (gaps), TheTVDB direct (subscription or dead queue), FileBot (closed,
single developer), Radarr now (movies are a later plan on the same pattern).

## Verification

- Hook unit tests (pytest, in the repo's test discovery): the 59 Skillsville
  titles resolve to 59 distinct numbers; junk-prefixed YouTube titles match by
  containment; two close candidates fail; a title with no candidate fails;
  the channel is the show when there's no folder, a folder overrides the
  channel, and a missing channel with no folder fails loudly.
- Smoke file already in `Kids/_incoming` moved into `_incoming/Skillsville`
  and the hook run by hand inside the container: lands as
  `Kids/TV/Skillsville (2025) {tvdb-460946}/Season 01/Skillsville - S01Exx - Sound Effects Artist.mp4`,
  Gatus `metube_plexify` green.
- Negative test: a file with a made-up title under `_incoming/Skillsville`
  stays put, the hook exits non-zero, Gatus goes red and Nathan gets the
  Fenwick message; then a real placement turns it green again.
- Then the remaining 58 episodes queued from the channel listing filtered to
  `FULL EPISODE` titles, into `_incoming/Skillsville`; Plex shows 59
  numbered episodes after the ordering switch; first play on the LG CX checked.
- Gatus `Sonarr` green, Komodo stacks healthy, Backrest lists `sonarr`,
  bandicoot `--tags storage` changed=0, Terraform plan adds one record.

## Ledger

- ✅ Stack `metube/` (stack.toml, compose.yaml) on bandicoot: image pinned
  2026.08.28, Pouch `Kids` at `/downloads`, NVMe scratch/state, PUID 1000 /
  PGID 100, AV1-first `format_sort`, JS solver, thumbnails; healthcheck with
  the Pouch sentinel. Output template is plain `%(title)s` until the naming
  lookup below lands.
- ✅ Host prep via Ansible `--tags storage`: `/var/lib/metube/{state,tmp}` from
  `storage_binds_managed_dirs`, `/mnt/pouch/Kids` sentinel (changed=2, then 0).
- ✅ Ingress: DNS record `metube.pod.haus` (Terraform applied, one record),
  Pomerium family route, bilby Caddy `@metube` → 10.0.0.90:8081. The
  Pomerium stack renders `config.yaml` at deploy time and its content hash
  covers only `compose.yaml`, so the push did not redeploy it; a manual
  `DeployStack numbat-pomerium` brought the route and its certificate up.
- ✅ Gatus `MeTube` (group Media); Backrest bandicoot bind + plan `metube`.
- ✅ Docs: hosts, networking, AGENTS.md; Komodo clone-before-pull note.
- ✅ Smoke test: one Skillsville episode queued into `Kids/_incoming` landed as
  AV1 1080p24 + AAC MP4 with the thumbnail embedded, 93 MB for 12.5 min;
  Gatus `MeTube` green, front door redirects to sign-in like every family route.
- ✅ Sonarr stack on bandicoot (2271ab9), the plexify hook and tests (30c07b4),
  Sonarr configured via API (root folder, naming formats, Plex connection with
  the existing Plex token, no indexers or clients), `sonarr.pod.haus` live.
- ✅ Smoke test: Sound Effects Artist placed as
  `Skillsville (2025) {tvdb-460946}/Season 01/Skillsville (2025) - S01E09 - Sound Effects Artist.mp4`.
- ✅ Negative test caught a real bug first: the containment rule imported a
  "Quantum Plumber" dummy as the episode "Plumber". Fixed in d1ee47e (segment
  equality). Re-run: exit 1, file left in staging, Gatus Plexify red with the
  candidate list, Fenwick sent the Signal alert and later the resolution.
- ✅ Channel fill: 58 queued, 55 placed with no mismatches; Judge (E50),
  Lighting Designer (E40) and Firefighter (E13) failed twice on the download
  side (yt-dlp "bytes read, more expected"). Re-downloaded directly: two placed
  as AV1; Judge's AV1 1080p stream returns HTTP 500 from YouTube, so it was
  taken as H.264 1080p. 59 of 59 on disk, staging empty, Plexify green.
- ✅ Plex: the Kids TV library already used TheTVDB aired ordering; all 59
  matched. Its "Prefer local metadata" switch showed the embedded YouTube
  titles, so the tag writer left the pipeline (bd83a1b) and the 59 files were
  rewritten in place without container tags; after a refresh Plex shows
  TheTVDB titles for all 59.
- ⏳ Nathan: first-play check on the LG CX (direct play vs transcode).
- ✅ Fixed the no-folder gap the 42-episode Space Racers season 1 queue hit:
  MeTube's `/downloads` bind moved to `Kids/_incoming` itself (everything it
  writes is now staging), and the hook falls back to yt-dlp's `%(channel)s`
  (the show name, for these channels) when the family picks no folder.
  Verified end to end: "SPACE RACERS: The Haunted Asteroid" queued with no
  folder chosen landed as
  `Kids/TV/Space Racers (2014) {tvdb-282447}/Season 02/Space Racers (2014) - S02E01 - The Haunted Asteroid.mp4`,
  Sonarr's episode file count for the series went 42 → 43, Gatus
  `metube_plexify` stayed green, and Plex showed the new episode with no
  manual refresh needed.
