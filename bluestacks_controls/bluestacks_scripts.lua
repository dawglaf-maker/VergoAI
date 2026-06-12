-- ============================================================
--   VergoAI - BlueStacks 5 Lua Scripts
-- ============================================================
--   Copy any of the script blocks below into BlueStacks Controls
--   Editor: drag "Script" onto the screen, paste the script body,
--   assign a key (Y / U / H), save.
--
--   BlueStacks uses a Lua-style scripting system. The functions
--   available are:
--     touchDown(x, y)        -- press a touch point at (x, y)
--     touchUp(x, y)          -- release the touch point
--     tap(x, y)              -- shortcut for touchDown + touchUp
--     swipe(x1, y1, x2, y2)  -- swipe from start to end
--     sleep(ms)              -- wait (milliseconds)
--   Coordinates are pixels on the 1920x1080 emulator surface.
-- ============================================================


-- ─────────────────────────────────────────────────────────────
-- SCRIPT 1 - "Safe Reconnect" for Y
-- ─────────────────────────────────────────────────────────────
-- Why use this instead of a plain Tap spot for Y:
--   * The reconnect popup can render slightly off-centre depending
--     on resolution, game version, etc.
--   * One tap sometimes "misses" the button hitbox if the popup is
--     still animating in.
-- This script taps 3 positions clustered around the centre with
-- delays. At least one of them will always hit the button.

-- Bind to: Y

tap(960, 627)        -- centre of standard popup
sleep(150)
tap(960, 600)        -- slightly higher (alt popup position)
sleep(150)
tap(960, 640)        -- slightly lower
sleep(300)
tap(960, 627)        -- centre again, in case popup re-appeared


-- ─────────────────────────────────────────────────────────────
-- SCRIPT 2 - "Nova Drop Hold-Tap" for U
-- ─────────────────────────────────────────────────────────────
-- Alternative to using "Repeated Tap" if it doesn't work well.
-- Taps the drop centre 15 times over ~3 seconds, fast enough to
-- look like a continuous press to the game.

-- Bind to: U

for i = 1, 15 do
    tap(960, 540)
    sleep(200)
end


-- ─────────────────────────────────────────────────────────────
-- SCRIPT 3 - "Chaos Drop Claim" for T
-- ─────────────────────────────────────────────────────────────
-- Single tap with a 500ms re-tap in case the first one is too early
-- (chaos drop animation has a slight delay before the button is hot).

-- Bind to: T

tap(960, 540)
sleep(500)
tap(960, 540)


-- ─────────────────────────────────────────────────────────────
-- SCRIPT 4 - "Hypercharge + Super Combo" for J  (advanced, optional)
-- ─────────────────────────────────────────────────────────────
-- Lets you fire hypercharge + super manually with a single keypress
-- when playing the game yourself. VergoAI does this combo internally
-- so the bot doesn't need it, but it's useful for human players.

-- Bind to: J  (anything unused -- not used by the bot)

tap(1400, 990)       -- hypercharge button
sleep(80)
tap(1510, 880)       -- super button
