# Minimal Spotlight on macOS 26/27 (Applications + Folders only)

> Research note gathered on 2026-11-09 by a subagent; it feeds [the migration plan](../macbook-pro-migration.md). Commands here are untested on macOS 27.

Researched 2026-11-09 on a MacBook Air running macOS 27.2 (26B8125). Read-only: nothing was written or opened. Nothing below has been executed, so treat the commands as untested.

## 1. Where the toggles live, and the evidence

**Category toggles: very probably still the `orderedItems` array in `com.apple.Spotlight`.**
- Settings pane binary on this Mac: `/System/Library/CoreServices/Spotlight.app/Contents/Extensions/SpotlightPreferenceExtension.appex` (bundle `com.apple.Spotlight-Settings.extension`, built against the macOS 27.0 SDK). `strings` on it shows the literals `orderedItems`, `name`, `enabled`, `version`, a `ResultVisibilityManager` / `ResultVisibilityItem` class, and the category names. Direct evidence from this machine, 2026-11-09.
- Category names found in the binary (older Spotlight used the same names): `APPLICATIONS`, `DIRECTORIES` (= Folders), `DOCUMENTS`, `PRESENTATIONS`, `SPREADSHEETS`, `SOURCE`, `EMAIL`, `MESSAGES`, `CONTACT`, `EVENT_TODO`, `IMAGES`, `BOOKMARKS`, `MUSIC`, `MOVIES`, `FONTS`, `SYSTEM_PREFS` (= System Settings), `MENU_SPOTLIGHT_SUGGESTIONS` (Siri Suggestions), `MENU_WEBSEARCH` (Websites), `MENU_CONVERSION`, `MENU_EXPRESSION` (Calculator), `MENU_DEFINITION`, `MENU_OTHER`, `TIPS`.
- Why `defaults read` shows no `orderedItems`: the key appears to be written only once someone changes a toggle; until then the built-in default list applies. Inference, not verified. The other keys in the domain (`DisabledUTTypes`, `EnabledPreferenceRules`, `queryViewOptions`) do not appear in the pane's strings, and `queryViewOptions` decodes to just `displayStyle = 0`, so they are not the category switches.
- Older confirmation (Ventura era, third party, undated): Hexnode documents a `com.apple.Spotlight` payload with `orderedItems`, each entry `{name, enabled}`, and notes disabled categories may still look ticked in the pane but are excluded from results. https://www.hexnode.com/mobile-device-management/help/configure-spotlight-settings-on-macs-using-configuration-profiles.md . A 2017 Jamf thread says the same. Neither was tested on the redesigned Spotlight, and neither mentions Tahoe.

**Caveat on the redesigned UI (unverified).** I found no source confirming that Tahoe or 27's new Spotlight honours a hand-written `orderedItems`. A MacRumors user (2026-01-11) turned off every category except Apps in Tahoe and still saw Word documents and data files; no answer was given ( https://forums.macrumors.com/threads/upgraded-to-tahoe-see-too-much-noise-in-spotlight-searches-i-have-toggled-off-all-search-categories-except-apps-and-still-see-files-suggestions.2475878/ ). Tahoe also has filter chips (Cmd+Space then Cmd+1 for Apps) that are separate from these toggles. Apple's own help page only describes the GUI route. No dotfiles repo or forum post showing `defaults write com.apple.Spotlight` category keys on 26/27 turned up.

**"Help Apple Improve Search".** Domain `com.apple.assistant.support`, key `Search Queries Data Sharing Status`, integer `2` = off. Companion key `Siri Data Sharing Opt-In Status` (this Mac already has it at `2`). The pane binary calls `AFSearchQueriesDataSharingStatus` and checks a "forced" state, which matches a managed key. Sources: CIS macOS 26 Tahoe benchmark item 2.9.1 and the DISA STIG for macOS 26 (V-277104, versions 2026-02-11 and 2026-05-23), both via search snippets only (pages not fetched; Tenable page 404, STIG viewer 403). On this Mac the "Search Queries Data Sharing Status" key is currently absent.

**Web lookups ("Search in Spotlight" / Websites).** The pane binary has `MENU_WEBSEARCH` as an ordinary category (so the `orderedItems` route covers it) plus `_parsecManagedDisableWebSearches`, meaning a managed restriction exists as well. I could not identify the restriction's key from the binary and found no source naming it. Siri Suggestions is `MENU_SPOTLIGHT_SUGGESTIONS`.

**Per-app Siri/Spotlight donation** is separate: `com.apple.corespotlightui` `CSReceiverBundleIdentifierState` (one 0/1 per bundle id) and `com.apple.suggestions`. These are app-level, not the category list.

## 2. Commands

### Headless attempt (category toggles) - unverified on 27
Disable everything except `APPLICATIONS`, `DIRECTORIES` and `SYSTEM_PREFS`. The array replaces the whole key, so every category is listed.

```sh
python3 - <<'PY'
import subprocess
keep = {"APPLICATIONS", "DIRECTORIES", "SYSTEM_PREFS"}
names = ["APPLICATIONS","DIRECTORIES","SYSTEM_PREFS","DOCUMENTS","PRESENTATIONS","SPREADSHEETS",
         "SOURCE","EMAIL","MESSAGES","CONTACT","EVENT_TODO","IMAGES","BOOKMARKS","MUSIC","MOVIES",
         "FONTS","MENU_SPOTLIGHT_SUGGESTIONS","MENU_WEBSEARCH","MENU_CONVERSION","MENU_EXPRESSION",
         "MENU_DEFINITION","MENU_OTHER","TIPS"]
items = [f"<dict><key>enabled</key><{'true' if n in keep else 'false'}/><key>name</key><string>{n}</string></dict>" for n in names]
subprocess.run(["defaults","write","com.apple.Spotlight","orderedItems","-array",*items], check=True)
PY
killall cfprefsd Spotlight 2>/dev/null; killall SpotlightPreferenceExtension 2>/dev/null; true
```
If Cmd+Space still shows the old behaviour, log out and in. To undo: `defaults delete com.apple.Spotlight orderedItems` (restores the all-on default) and repeat the restart.

### Help Apple Improve Search (user domain, may be ignored)
```sh
defaults write com.apple.assistant.support "Search Queries Data Sharing Status" -int 2
defaults write com.apple.assistant.support "Siri Data Sharing Opt-In Status" -int 2
killall cfprefsd
```
A 2025 Jamf thread (Jan 10 and May 19, 2025, macOS version not stated) says a plain plist did not work for one admin and only a configuration profile did. Treat the user-domain write as likely insufficient.

### Profile route
Both `com.apple.Spotlight` (`orderedItems`) and `com.apple.assistant.support` (the two integers) are accepted as Custom Settings payloads in a `.mobileconfig`. On a non-supervised, non-MDM Mac, `profiles install -type configuration` has not worked since macOS 11. The profile has to be opened and approved by hand in System Settings > General > Device Management (Profiles), so it is not fully headless and I did not verify that 27 accepts an unsigned local profile with these domains. `profiles list` here shows no profiles installed and `/Library/Managed Preferences` does not exist.

### GUI fallback (reliable)
System Settings > Spotlight > Search results: switch off everything except Applications, Folders and System Settings (rows: Documents, Images, Mail & Messages, Siri Suggestions, Websites, Calculator, Conversion, Definition, and so on). Scroll down and turn off Help Apple Improve Search. 

## 3. Verify from the shell
```sh
defaults read com.apple.Spotlight orderedItems      # should list the 23 dicts with enabled = 0/1
defaults read com.apple.assistant.support "Search Queries Data Sharing Status"   # expect 2
plutil -p ~/Library/Preferences/com.apple.Spotlight.plist
profiles list                                        # only if a profile was used
```
Best end-to-end check: after writing, open Settings > Spotlight (read only) and see whether the toggles reflect the array (the pane reads the same key), and make a real Cmd+Space query for a document name. If the pane does not reflect the write, it did not take effect. The safest first step is to flip one toggle by hand in the GUI, then run `defaults read com.apple.Spotlight orderedItems` to see the exact structure macOS 27 writes, and diff it against the array above.

## 4. Confidence
Medium-low on the headless route working on the redesigned Spotlight (the key and category names are confirmed present in 27's settings binary, but no one has published a test, and the new results UI may not honour it); high that the GUI route works; medium on `Search Queries Data Sharing Status = 2` as the off value (CIS/STIG, but possibly requires a profile); low on identifying a web-lookup restriction key.
