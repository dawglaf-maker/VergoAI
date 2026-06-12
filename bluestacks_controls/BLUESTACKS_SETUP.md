# BlueStacks Controls Setup — Brawl Stars + VergoAI

VergoAI talks to Brawl Stars by sending **keyboard keys** (M for attack,
E for super, Y for reconnect, etc). For these to actually do anything,
your BlueStacks needs to know which screen position each key should tap.

You have two ways to set this up:

---

## Option 1 — Auto-install (recommended)

1. Launch BlueStacks 5 and open **Brawl Stars** at least once
2. Close BlueStacks completely (right-click tray icon → Exit)
3. Open VergoAI Hub
4. Under **Emulator**, click **Install BlueStacks Controls**
5. Confirm the dialog
6. Reopen BlueStacks — you should now see the VergoAI control layout

---

## Option 2 — Manual setup (if auto-install fails)

Open BlueStacks 5 → start Brawl Stars → click the **keyboard icon** on
the right-side toolbar → **Edit controls**.

Add a **Tap** for each key below. Use BlueStacks' percentage display to
match the coordinates — these are based on a 1920×1080 layout.

| Action                | Key | X (px) | Y (px) | Notes                           |
|-----------------------|-----|--------|--------|---------------------------------|
| Attack                | M   | 1725   | 800    | The attack button               |
| Super                 | E   | 1510   | 880    | The super ability button        |
| Gadget                | G   | 1640   | 990    | The gadget button               |
| Hypercharge           | H   | 1400   | 990    | The hypercharge button          |
| Proceed / Claim Drop  | Q   | 1660   | 980    | Used for menus + star drops     |
| Play Again            | F   | 1360   | 920    | After-match continue button     |
| **Reconnect**         | Y   | 960    | 627    | **Centre of reconnect popup**   |
| Chaos Drop            | T   | 960    | 540    | Centre of screen                |
| Nova Drop             | U   | 960    | 540    | Centre of screen                |

Also add a **Joystick** at `x=220, y=870, radius=120` controlled by
**WASD**. (VergoAI sends touches directly to the joystick area, but
mapping it lets you also drive manually.)

When done, click **Save** in BlueStacks.

---

## Where BlueStacks stores controls

If you need to back up or share your control profile:

```
%USERPROFILE%\BlueStacks_nxt\bgp\com.supercell.brawlstars\
```

Look for `.bgcfg` or `.cfg` files. These are JSON-based and can be
copied between PCs.

---

## Troubleshooting

**"Y does nothing when there's a connection error"**
Open BlueStacks controls and confirm Y is mapped to the actual reconnect
button location for *your* Brawl Stars layout. The default (960, 627) is
the centre of a standard 1920×1080 popup but the popup may render
elsewhere on your install. Right-click the existing Y mapping in
BlueStacks → drag it to the right spot.

**"VergoAI moves but never attacks"**
M is not mapped. Add a Tap for M at (1725, 800).

**"The bot uses gadgets but they don't fire"**
Same — make sure G is mapped at (1640, 990).
