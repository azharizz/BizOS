#!/bin/zsh
# Put Chrome (and the BizOS workspace window, if open) inside the 16:9 band that demo/record.sh records:
# logical screen 1440x900, band = y 40..850 (below the menu bar). Needs Accessibility permission for the terminal app.
osascript <<'OSA'
tell application "Google Chrome" to set bounds of front window to {0, 40, 1440, 850}
tell application "System Events"
  if exists process "Electron" then
    tell process "Electron"
      repeat with w in windows
        set sz to size of w
        if (item 1 of sz) > 600 then
          set position of w to {0, 40}
          set size of w to {1440, 810}
        end if
      end repeat
    end tell
  end if
end tell
OSA
