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

| Concern | Decision | Why |
|---|---|---|
| Host | bandicoot | Download + remux is CPU/scratch work; bandicoot has the cores and NVMe; bilby keeps Plex and only reads the result |
| Stack | `metube/` — `stack.toml` (server bandicoot, `linked_repo = "podhaus-bandicoot"`, `run_directory = "metube"`), `compose.yaml`, `scripts/` | The ClickStack/Fenwick-on-bandicoot shape; scripts bound from the deploy clone like Plex's `/scripts` |
| Downloads | `/mnt/pouch/Kids` at `/downloads` (`DOWNLOAD_DIR`); scratch `/var/lib/metube/tmp` (`TEMP_DIR`) on NVMe; queue state `/var/lib/metube/state` (`STATE_DIR`) | The folder picker (`CUSTOM_DIRS`) then offers `TV`, `Movies`, `Videos`; a half-finished file never sits on the NAS; Plex's Kids libraries scan the subfolders, not the root |
| Naming | MeTube writes a flat staging name `<series> - <episode title>.<ext>` (`OUTPUT_TEMPLATE` and `_PLAYLIST`, `%(series|…)s - %(episode,title)s`); a yt-dlp `Exec` postprocessor (`after_move`) runs `/scripts/plexify <file> <series> <episode>` which moves a mapped show into `TV/<Plex folder>/Season NN/<series> - SNNENN - <title>.<ext>` | Plex needs `Show/Season NN/Show - SNNENN` and the number comes only from the per-show map. Literals `Season 01`/`S01` are hardcoded because parsed fields are strings and `%02d` padding silently fails |
| Show maps | `metube/scripts/shows/<series>.json`: Plex folder name (`Skillsville (2025) {tvdb-460946}`) and title→`SxxEyy` map, keyed on YouTube's spelling, matched case- and punctuation-insensitively | Static, 59 rows, reviewable; TVDB spelling differences are irrelevant since Plex takes titles from TVDB |
| Renamer behaviour | No map for the series (or no series parsed): leave the file where MeTube put it, exit 0. Map present but title unknown, or target exists: exit non-zero so MeTube shows the download as failed | An unmapped show is a valid generic download; an unmapped episode of a mapped show is an error someone must see |
| Metadata | `MetadataFromField` `title:(?P<series>Skillsville) FULL EPISODE \| (?P<episode>.+)`; `FFmpegMetadata`; `EmbedThumbnail` with `already_have_thumbnail: false`; `writethumbnail` | Series/episode fields feed the template and the renamer; thumbnail in the MP4, sidecar removed |
| Format | `format_sort: ["res","vcodec:av01","acodec:m4a"]`, `merge_output_format: mp4`; no `format` key | Best resolution first, AV1 over VP9/H.264 at that resolution, AAC audio so the merge is a stream copy; UI quality picker keeps working; leave the UI codec dropdown on Auto |
| Ingress | `metube.pod.haus`: Terraform `services_pod_haus.tf` DNS entry, Pomerium family route, bilby Caddy `@metube` → `10.0.0.90:8081`, MeTube publishes `8081` on bandicoot's LAN | The moved-service pattern; family policy is the audience. `ALLOW_YTDL_OPTIONS_OVERRIDES` stays off (arbitrary-command surface) |
| Monitoring | Gatus `MeTube` `http://10.0.0.90:8081/` 200, group Media; container healthcheck asserts the page and the Pouch sentinel `/downloads/.podhaus-share-mounted` | brinno's sentinel precedent; `/mnt/pouch/Kids` added to bandicoot's `storage_binds_extra_sentinels` |
| Backup | `backup/bandicoot`: `/var/lib/metube/state:/userdata/metube:ro`, plan `metube` | Queue history only; media is not backed up |
| Runtime | `security_opt: [label:disable]`, `mem_limit: 1g`, `cpus: 4`, `UID`/`GID` matching the Pouch owner | Enforcing SELinux with NFS binds; ffmpeg bursts capped |

Rejected: bilby as host (RAM-tight, Plex's host); a second Plex library or the
Personal Media agent (no titles/artwork); `playlist_index` numbering (channel
playlist is out of order); the one-off rename script (leaves every future
episode to hand work; the Exec hook is one file and one bind).

## Verification

- Renamer: pytest in `metube/scripts/` — mapped title moves to the exact Plex
  path; unmapped series untouched with exit 0; mapped series with unknown title
  exits non-zero; existing target refuses. Run through `tools/pre-commit`.
- Queue one Skillsville episode on `metube.pod.haus`: file appears as
  `Kids/TV/Skillsville (2025) {tvdb-460946}/Season 01/Skillsville - S01Exx - <Career>.mp4`,
  AV1 + AAC in MP4 (ffprobe), thumbnail embedded, no sidecar; then the channel
  URL for the remaining 58.
- Plex: library ordering set to TheTVDB (Nathan), show matches with 59 numbered
  episodes; first play on the LG CX shows direct play or a cheap transcode in
  the dashboard.
- Gatus `MeTube` green; Komodo stack healthy; Backrest lists `metube`;
  bandicoot `--tags storage` changed=0 after the sentinel; Terraform plan adds
  exactly one record.

## Ledger

(filled in as the work lands)
