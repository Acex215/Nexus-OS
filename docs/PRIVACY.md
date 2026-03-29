# NEXUS OS — Privacy & Data Handling

This document describes how NEXUS OS handles user data. It is intended
for legal review prior to public release.

## 1. What Data Is Collected

When the user grants explicit on-chain consent, 18 behavioral channels
can collect device activity:

| Channel | What's Recorded | Recording Method |
|---------|----------------|------------------|
| Keystroke | Keycodes, timing, modifiers | evdev /dev/input |
| Mouse | Coordinates, clicks, scroll, hovers | evdev /dev/input |
| Window | Window titles, application class, focus | xdotool, xprop |
| Web | URLs from browser history, search queries | SQLite (Chromium/Firefox) |
| Message | Desktop notifications (app, summary, body) | D-Bus |
| File | File operations (path, event, size) | inotifywait |
| Clipboard | Copy/paste content, source/destination | xclip |
| System | CPU, RAM, processes, disk, network I/O | /proc filesystem |
| Session | Login/logout, idle, breaks, session duration | xprintidle, logind |
| App Lifecycle | Process start/exit, crashes | /proc polling |
| GPS | Latitude/longitude (30-second intervals) | gpsd or IP geolocation |
| Weather | Temperature, humidity, wind (15-minute intervals) | Open-Meteo API |
| WiFi | SSID, signal strength (60-second intervals) | iwconfig |
| Audio | Volume changes, mute, output device | pactl (PulseAudio) |
| Display | Brightness changes, monitor connections | sysfs, xrandr |
| Power | Battery level, charging state, sleep/wake | sysfs |
| Peripheral | USB/Bluetooth connect/disconnect | udevadm |
| Notification | All desktop notifications | dbus-monitor |

## 2. Where Data Is Stored

All collected data is stored as transactions on the user's **private
Ethereum blockchain** running on the user's own Raspberry Pi hardware.

- **No cloud storage.** There is no server, database, or cloud service.
- **No data transmission.** Raw behavioral data never leaves the device.
- **The user owns the hardware.** The blockchain runs on their Pi.
- **The data is the user's property.** They can read it, export it,
  or destroy the SD card at any time.

## 3. Consent Model

- **Default: OFF.** Behavioral collection is disabled by default.
- **Explicit opt-in required.** The user must actively enable collection
  in the first-boot wizard or NEXUS Settings.
- **On-chain consent.** The `ConsentManager` smart contract records
  consent grant/revocation with timestamps.
- **Per-channel control.** Users can enable/disable individual channels.
- **Instant revocation.** Revoking consent immediately stops all
  collection and destroys temporary caches.
- **Emergency stop.** A hardware button in the NEXUS Monitor app
  immediately halts all collection.

## 4. What Leaves the Device

**Only one thing ever leaves the device: a 32-byte keccak256 hash.**

This hash is the result of a 6-layer transformation:
1. Millions of raw actions → 288-dimensional feature vector (lossy, ~1M:1 compression)
2. Feature vector + Laplace noise (differential privacy, ε=1.0/day)
3. Noised vector × daily rotation matrix (salt from block state)
4. Rotated vector → model training gradient (weight deltas)
5. Gradient → keccak256 hash (32 bytes, one-way)
6. Hash → FlockCoordinator smart contract (on private chain)

**From the hash, it is mathematically impossible to reconstruct:**
- What the user typed
- What URLs they visited
- What messages they received
- What files they opened
- Where they were located
- Any individual action or piece of content

## 5. Developer Access

During development, a `debugMode` flag on the BehavioralActionRegistry
contract allows the developer (admin wallet) to read raw action data
for testing and verification.

**Before public launch:**
1. `disableDebugMode()` is called — **permanently** disables developer
   raw data access. This is irreversible.
2. `lockAdmin()` is called — **permanently** removes the admin role.
   Sets `admin = address(0)`. This is irreversible.

After these two calls, no party — including the developer — can read
raw behavioral data from the contract's debug interface.

**The user can always read their own data** via `selfReadAction()` and
`selfReadActions()` which verify `msg.sender == action.user`. These
functions are **not** affected by debug mode and work permanently.

## 6. Data Lifecycle

| Stage | Duration | What Happens |
|-------|----------|-------------|
| Collection | Real-time | Actions recorded on private blockchain |
| On-chain storage | Permanent | Actions stored as immutable transactions on user's chain |
| Temporary caches | < 1 hour | Browser history copies, etc. — destroyed hourly |
| Feature extraction | Daily (23:50 UTC) | 288-dim vector computed from day's actions |
| Obfuscation | Daily | Salt rotation + noise applied to features |
| Gradient submission | Daily | 32-byte hash submitted to FlockCoordinator |
| Cache destruction | Daily | Temporary files destroyed with on-chain proof |
| Privacy budget reset | Daily (00:00 UTC) | ε budget reset for new epoch |

## 7. Legal Framework

| Regulation | Applicability | Compliance |
|-----------|---------------|------------|
| GDPR Art. 6(1)(a) | Consent-based processing | Explicit on-chain consent, revocable |
| GDPR Art. 17 | Right to erasure | Temporary caches auto-destroyed; on-chain data is immutable (user owns the chain) |
| GDPR Art. 20 | Data portability | User can export via selfRead* functions or copy blockchain data |
| CCPA | User as data controller | User owns hardware, runs blockchain, controls all data |
| HIPAA | If behavioral data indicates health | Feature extraction destroys identifiable content; k-anonymity on model output |

## 8. What the Lawyer Should Review

1. **Consent flow:** First-boot wizard → on-chain consent → systemd activation
2. **Debug lockout:** `disableDebugMode()` + `lockAdmin()` — verify irreversibility
3. **The 32-byte hash claim:** Is the 6-layer transformation sufficient to
   classify the hash as non-personal data?
4. **On-chain immutability:** User's behavioral actions are permanently on
   THEIR private chain. Is this a GDPR concern if the user can't delete
   blockchain history? (The user physically owns the storage device.)
5. **Collection channel list:** Review each of the 18 channels for legality
   in target jurisdictions.
6. **Android companion:** If expanded to phones, AccessibilityService and
   NotificationListenerService permissions require user disclosure.
7. **GPS collection:** Location data has heightened regulatory requirements.
   Review the 30-second polling interval and IP-geolocation fallback.
8. **The source-available license:** Review patent claims alignment with
   the LICENSE file.
