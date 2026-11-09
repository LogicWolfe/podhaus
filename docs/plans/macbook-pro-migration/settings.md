# macOS settings: MacBook Air (nb-macbook-air) vs fresh MacBook Pro (nb-macbook-pro)

> Investigation report gathered read-only on 2026-11-09 by a subagent; it feeds [the migration plan](../macbook-pro-migration.md). Where a recommendation here differs from the plan, the plan is authoritative.

Sources: `defaults read` dumps of 25 domains plus extra read-only probes on both machines (symbolic hotkeys, currentHost keys, pmset, sysadminctl, osascript login items, Launch Services handlers). "Pro" column is the value actually read on the fresh Pro; "unset" means the key does not exist there, so the OS default applies (default given where known).

Confidence: rows marked **(?)** have a key whose exact meaning I could not verify from the data alone.

Apply column legend: `Dock` = `killall Dock`; `Finder` = `killall Finder`; `CC` = `killall ControlCenter`; `SUIS` = `killall SystemUIServer`; `logout` = takes effect after log out/in; `sudo` = needs root (not run by me); `GUI` = cannot be done headlessly.

## 1. Keyboard and text

| # | Domain | Key | Air | Pro | What it does | Command | Apply |
|---|---|---|---|---|---|---|---|
| 1 | NSGlobalDomain | KeyRepeat | 2 | unset (6) | Key repeat rate: very fast (30 ms) | `defaults write NSGlobalDomain KeyRepeat -int 2` | logout |
| 2 | NSGlobalDomain | InitialKeyRepeat | 15 | unset (25) | Delay before key repeat starts: short (225 ms) | `defaults write NSGlobalDomain InitialKeyRepeat -int 15` | logout |
| 3 | -currentHost NSGlobalDomain | com.apple.keyboard.modifiermapping.0-0-0 | Src 30064771129 (0x700000039, Caps Lock) -> Dst 30064771300 (0x7000000E4, Right Control) | unset | Remaps Caps Lock to act as a Control key on the built-in keyboard. Note Dst is Right Control, not Left (0x7000000E0) | `defaults -currentHost write NSGlobalDomain com.apple.keyboard.modifiermapping.0-0-0 -array '<dict><key>HIDKeyboardModifierMappingDst</key><integer>30064771300</integer><key>HIDKeyboardModifierMappingSrc</key><integer>30064771129</integer></dict>'` | logout (hidutil alternative is not persistent) |
| 4 | com.apple.symbolichotkeys | AppleSymbolicHotKeys.64 | enabled=0 (params 32,49,1048576 = Cmd+Space) | key absent (Spotlight shortcut enabled) | Disables the Spotlight Cmd+Space shortcut, freeing it for Alfred | `defaults write com.apple.symbolichotkeys AppleSymbolicHotKeys -dict-add 64 '<dict><key>enabled</key><false/><key>value</key><dict><key>parameters</key><array><integer>32</integer><integer>49</integer><integer>1048576</integer></array><key>type</key><string>standard</string></dict></dict>'` then `/System/Library/PrivateFrameworks/SystemAdministration.framework/Resources/activateSettings -u` | logout (activateSettings often suffices) |
| 5 | com.apple.symbolichotkeys | AppleSymbolicHotKeys.176 **(?)** | enabled=0, type SAE1.0 | key absent | Disables hotkey 176; believed to be the dictation shortcut (label not verified) | `defaults write com.apple.symbolichotkeys AppleSymbolicHotKeys -dict-add 176 '<dict><key>enabled</key><false/><key>value</key><dict><key>type</key><string>SAE1.0</string></dict></dict>'` then the same `activateSettings -u` | logout |
| 6 | NSGlobalDomain | NSUserQuotesArray, KB_DoubleQuoteOption, KB_SingleQuoteOption | curly quotes written explicitly: “ ” ‘ ’ | unset | Smart quote style. Same as the en-AU default, so effectively no change | `defaults write NSGlobalDomain NSUserQuotesArray -array "“" "”" "‘" "’"; defaults write NSGlobalDomain KB_DoubleQuoteOption -string "“abc”"; defaults write NSGlobalDomain KB_SingleQuoteOption -string "‘abc’"` | logout |
| 7 | NSGlobalDomain | KB_SpellingLanguage | {KB_SpellingLanguageIsAutomatic=1} | unset | Spelling language "Automatic by language". Default-equivalent | `defaults write NSGlobalDomain KB_SpellingLanguage -dict KB_SpellingLanguageIsAutomatic -bool true` | logout |
| 8 | NSGlobalDomain | NSUserDictionaryReplacementItems | 18 text replacements | identical 18 entries already present (iCloud-synced) | Text replacements (omw, eml, peml, etc.) | none needed | n/a |

## 2. Trackpad and mouse

| # | Domain | Key | Air | Pro | What it does | Command | Apply |
|---|---|---|---|---|---|---|---|
| 9 | NSGlobalDomain | com.apple.trackpad.scaling | 2 | unset (default ~1) | Trackpad tracking speed | `defaults write NSGlobalDomain com.apple.trackpad.scaling -float 2` | logout |
| 10 | NSGlobalDomain | com.apple.mouse.scaling | 2 | unset (default ~1) | Mouse tracking speed | `defaults write NSGlobalDomain com.apple.mouse.scaling -float 2` | logout |
| 11 | AppleMultitouchTrackpad, AppleBluetoothMultitouch.trackpad, -currentHost NSGlobalDomain | Clicking; com.apple.mouse.tapBehavior | 1; 1 | 0; unset | Tap to click | `defaults write com.apple.AppleMultitouchTrackpad Clicking -bool true; defaults write com.apple.driver.AppleBluetoothMultitouch.trackpad Clicking -bool true; defaults -currentHost write NSGlobalDomain com.apple.mouse.tapBehavior -int 1` | logout |
| 12 | AppleMultitouchTrackpad, AppleBluetoothMultitouch.trackpad, -currentHost NSGlobalDomain | TrackpadThreeFingerHorizSwipeGesture; com.apple.trackpad.threeFingerHorizSwipeGesture **(?)** | 1 | 2 | Three-finger horizontal swipe: Air is 1, Pro default 2 (2 is the full-screen-app/desktop switch). Meaning of 1 inferred as "page navigation, not desktop switching"; four-finger horizontal stays 2 on both | `defaults write com.apple.AppleMultitouchTrackpad TrackpadThreeFingerHorizSwipeGesture -int 1; defaults write com.apple.driver.AppleBluetoothMultitouch.trackpad TrackpadThreeFingerHorizSwipeGesture -int 1; defaults -currentHost write NSGlobalDomain com.apple.trackpad.threeFingerHorizSwipeGesture -int 1` | logout |
| 13 | com.apple.driver.AppleBluetoothMultitouch.trackpad | TrackpadThreeFingerVertSwipeGesture **(?)** | 1 (built-in trackpad is 2) | 2 | Three-finger vertical swipe on an external Magic Trackpad only; probably incidental | `defaults write com.apple.driver.AppleBluetoothMultitouch.trackpad TrackpadThreeFingerVertSwipeGesture -int 1` | logout |
| 14 | NSGlobalDomain | AppleEnableSwipeNavigateWithScrolls | 1 | unset (default is on) | Two-finger swipe to go back/forward in apps. Default-equivalent | `defaults write NSGlobalDomain AppleEnableSwipeNavigateWithScrolls -bool true` | none |

Not changed on Air (same as Pro): secondary click (two-finger), natural scrolling (unset, default on), three-finger drag off, force click on, pinch/rotate on, hot-corner secondary click off.

## 3. Dock, hot corners, Mission Control, windows

| # | Domain | Key | Air | Pro | What it does | Command | Apply |
|---|---|---|---|---|---|---|---|
| 15 | com.apple.dock | autohide | 1 | unset (false) | Auto-hide the Dock | `defaults write com.apple.dock autohide -bool true` | Dock |
| 16 | com.apple.dock | tilesize | 44 | unset (64) | Dock icon size | `defaults write com.apple.dock tilesize -int 44` | Dock |
| 17 | com.apple.dock | magnification | 1 | unset (false) | Magnify icons on hover | `defaults write com.apple.dock magnification -bool true` | Dock |
| 18 | com.apple.dock | largesize | 128 | unset | Magnified icon size (maximum) | `defaults write com.apple.dock largesize -int 128` | Dock |
| 19 | com.apple.dock | wvous-br-corner **(?)** | 14 (Quick Note), no modifier key stored | unset (Quick Note is the stock bottom-right corner, so likely default-equivalent) | Hot corner bottom-right: Quick Note. Other three corners unset on both | `defaults write com.apple.dock wvous-br-corner -int 14; defaults write com.apple.dock wvous-br-modifier -int 0` | Dock |
| 20 | com.apple.WindowManager | EnableTilingByEdgeDrag | 0 | unset (on) | Drag window to screen edge to tile: off | `defaults write com.apple.WindowManager EnableTilingByEdgeDrag -bool false` | logout (or killall Dock) |
| 21 | com.apple.WindowManager | EnableTopTilingByEdgeDrag | 0 | unset (on) | Drag window to top edge to fill screen: off | `defaults write com.apple.WindowManager EnableTopTilingByEdgeDrag -bool false` | logout |
| 22 | com.apple.WindowManager | EnableTiledWindowMargins | 0 | unset (on) | No gaps between tiled windows | `defaults write com.apple.WindowManager EnableTiledWindowMargins -bool false` | logout |
| 23 | com.apple.WindowManager | HideDesktop **(?)**, AppWindowGroupingBehavior **(?)**, StandardHideWidgets=0, StageManagerHideWidgets=0 | 1, 1, 0, 0 | unset | Desktop/Stage Manager display options. HideDesktop=1 probably hides desktop items in Stage Manager; AppWindowGroupingBehavior=1 is a Stage Manager window-grouping choice. Stage Manager itself is off on both (GloballyEnabled unset). Verify in System Settings before relying on these | `defaults write com.apple.WindowManager HideDesktop -bool true; defaults write com.apple.WindowManager AppWindowGroupingBehavior -int 1; defaults write com.apple.WindowManager StandardHideWidgets -bool false; defaults write com.apple.WindowManager StageManagerHideWidgets -bool false` | logout |

Mission Control and Spaces: no custom keys on Air (mru-spaces, spans-displays, expose-group-apps all unset). Ctrl+Left/Right space-switch shortcuts (hotkeys 79 to 82) are enabled on both.

### Dock app order on the Air (left to right, names only)

Apps, Safari, Firefox, Messages, Mail, Maps, Photos, FaceTime, Phone, Calendar, Contacts, Reminders, Notes, TV, Music, Numbers, Keynote, Pages, Games, App Store, iPhone Mirroring, Siri, System Settings, Downloads.

Pro's stock order differs only by: no Firefox, no Siri, Keynote before Numbers, and Downloads sits in the other-items section after the divider.

## 4. Finder and file dialogs

| # | Domain | Key | Air | Pro | What it does | Command | Apply |
|---|---|---|---|---|---|---|---|
| 24 | com.apple.finder | FXPreferredViewStyle | Nlsv | unset (icon view) | New Finder windows default to list view | `defaults write com.apple.finder FXPreferredViewStyle -string Nlsv` | Finder |
| 25 | com.apple.finder | FXPreferredSearchViewStyle | Nlsv | unset | Search results in list view | `defaults write com.apple.finder FXPreferredSearchViewStyle -string Nlsv` | Finder |
| 26 | com.apple.finder | FXLastSearchScope **(?)** | SCcf | unset (This Mac) | Search scope is the current folder. Air only has the "last used" key; the setting-pane key is FXDefaultSearchScope, so I also set that | `defaults write com.apple.finder FXDefaultSearchScope -string SCcf; defaults write com.apple.finder FXLastSearchScope -string SCcf` | Finder |
| 27 | NSGlobalDomain | NavPanelFileListModeForOpenMode, NavPanelFileListModeForSaveMode, NSNavPanelFileListModeForOpenMode2, NSNavPanelFileListModeForSaveMode2, NSNavPanelFileLastListModeForOpenModeKey, NSNavPanelFileLastListModeForSaveModeKey | all 2 | unset | Open and Save dialogs show list view | `for k in NavPanelFileListModeForOpenMode NavPanelFileListModeForSaveMode NSNavPanelFileListModeForOpenMode2 NSNavPanelFileListModeForSaveMode2 NSNavPanelFileLastListModeForOpenModeKey NSNavPanelFileLastListModeForSaveModeKey; do defaults write NSGlobalDomain $k -int 2; done` | none (apps relaunch) |
| 28 | com.apple.finder | FXICloudDriveDesktop, FXICloudDriveDocuments | 1, 1 | 0, 0 | iCloud Drive syncs Desktop and Documents folders. Moves files into iCloud on enable | not safely scriptable: System Settings > Apple Account > iCloud > iCloud Drive | GUI |

Not customised on Air (keys unset, so identical to Pro defaults): show hidden files, show all extensions, path bar, status bar, sidebar item selection in defaults. The Finder sidebar item list lives in a TCC-protected file I could not read ("Operation not permitted"); sidebar contents are unknown.

## 5. Menu bar and Control Centre

| # | Domain | Key | Air | Pro | What it does | Command | Apply |
|---|---|---|---|---|---|---|---|
| 29 | com.apple.menuextra.clock | ShowDate | 2 | 0 | Menu bar clock never shows the date | `defaults write com.apple.menuextra.clock ShowDate -int 2` | CC |
| 30 | com.apple.menuextra.clock | ShowDayOfWeek | 0 | 1 | Menu bar clock hides the weekday | `defaults write com.apple.menuextra.clock ShowDayOfWeek -bool false` | CC |
| 31 | com.apple.menuextra.clock | ShowAMPM, IsAnalog | 1, 0 | 1, unset | Digital clock with AM/PM. Default-equivalent | `defaults write com.apple.menuextra.clock ShowAMPM -bool true; defaults write com.apple.menuextra.clock IsAnalog -bool false` | CC |
| 32 | com.apple.controlcenter | NSStatusItem VisibleCC WiFi, Sound, FocusModes, Clock, BentoBox-0 | all 1 | unset | Menu bar items explicitly shown: Wi-Fi, Sound, Focus, Clock, Control Centre. Pro may already show some by default | `for k in WiFi Sound FocusModes Clock BentoBox-0; do defaults write com.apple.controlcenter "NSStatusItem VisibleCC $k" -bool true; done` | CC |
| 33 | -currentHost com.apple.controlcenter | Battery, Spotlight, NowPlaying, UserSwitcher, Sound, ShowSuggestions **(?)** | 8, 8, 2, 2, 16, 1 | all unset | Per-module Control Centre menu bar visibility. Value codes are not documented; 8 and 2 are presumed "not in menu bar". Bartender 6 also manages the menu bar, so these may reflect it. Prefer configuring in System Settings > Control Centre | `defaults -currentHost write com.apple.controlcenter Battery -int 8; defaults -currentHost write com.apple.controlcenter Spotlight -int 8; defaults -currentHost write com.apple.controlcenter NowPlaying -int 2; defaults -currentHost write com.apple.controlcenter UserSwitcher -int 2; defaults -currentHost write com.apple.controlcenter Sound -int 16` | CC |
| 34 | com.apple.Siri | StatusMenuVisible | 0 | 1 | Hides the Siri icon from the menu bar | `defaults write com.apple.Siri StatusMenuVisible -bool false` | SUIS |
| 35 | NSGlobalDomain | userMenuExtraStyle **(?)** | 1 | unset | Fast-user-switching menu style; likely irrelevant because UserSwitcher is hidden | `defaults write NSGlobalDomain userMenuExtraStyle -int 1` | SUIS |

## 6. Power, lock, sound

| # | Domain | Key | Air | Pro | What it does | Command | Apply |
|---|---|---|---|---|---|---|---|
| 36 | pmset (AC) | sleep | 0 (never) | 1 (minute) | Mac never sleeps on power adapter. Possibly written by the Adrafinil helper rather than by hand | `sudo pmset -c sleep 0` | sudo |
| 37 | pmset (battery) | displaysleep | 10 | 2 | Display sleeps after 10 min on battery | `sudo pmset -b displaysleep 10` | sudo |
| 38 | screen lock | askForPasswordDelay (via sysadminctl) | "screenLock delay is immediate" | 300 seconds | Require password immediately after sleep/screen saver | `sysadminctl -screenLock immediate -password -` (prompts for the login password) | GUI/interactive password |
| 39 | audio | output / input volume | 38 / 36 | 50 / 50 | Current volumes; runtime state, low value | `osascript -e 'set volume output volume 38' -e 'set volume input volume 36'` | none |

Same on both: alert volume 100, beep flash off, time zone Australia/Perth, firewall off, FileVault on, appearance auto light/dark, Siri enabled, Spotlight enabled, accessibility (reduce motion, transparency, sticky/slow keys, full keyboard access all off), no Time Machine destination.

## 7. Defaults, apps, login items

| # | Domain | Key | Air | Pro | What it does | Command | Apply |
|---|---|---|---|---|---|---|---|
| 40 | Launch Services | http, https URL schemes and public.html handler | org.mozilla.firefox | Safari (default) | Default browser is Firefox. Mail is Apple Mail on both (no mailto handler set; Fastmail only registered for fastmail:// scheme) | install `defaultbrowser` via mise, then `defaultbrowser firefox`. macOS shows a confirmation dialog that needs a click | GUI confirm |
| 41 | com.apple.Terminal | Default Window Settings, Startup Window Settings | Clear Dark | unset (Basic) | Terminal.app default profile | `defaults write com.apple.Terminal "Default Window Settings" -string "Clear Dark"; defaults write com.apple.Terminal "Startup Window Settings" -string "Clear Dark"` | none (relaunch Terminal) |
| 42 | Login items | System Events login item | Stay, Lunar, Adrafinil, Magnet, Alfred 5, Bartender 6 | none | Apps that launch at login (paths /Applications/<name>.app; Bartender path unresolved) | per app, after install: `osascript -e 'tell application "System Events" to make login item at end with properties {path:"/Applications/Magnet.app", hidden:false}'` | GUI/TCC (Automation approval for System Events, and macOS asks to approve Background Items) |

## 8. Could not determine

- Night Shift and True Tone: stored in a root-owned CoreBrightness plist (no `/Library/Preferences` file, user domain absent); needs sudo or GUI to read.
- Safari preferences: sandbox container is TCC-protected; the readable `com.apple.Safari` domain holds only StartPageSections.
- Finder sidebar item list: TCC-protected shared-file-list ("Operation not permitted").
- Function-key behaviour (`com.apple.keyboard.fnState`), Press-and-hold, accent colour, appearance override: all unset on Air, so default.
- Wallpaper: Air uses "The Beach" (mobileAssetDesktop); Pro read returned `missing value`, so no comparison.
