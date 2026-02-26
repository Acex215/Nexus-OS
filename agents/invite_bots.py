#!/usr/bin/env python3
"""Generate organized bot invitation links for NEXUS OS Discord bots.

Reads bot tokens from .env, extracts client IDs, and generates:
  - INVITE_INSTRUCTIONS.md  (markdown with grouped links + checklist)
  - invite_links.html       (interactive HTML helper with Open All button)

Also provides a verify_guild() function to check which bots are in the guild.
"""
import asyncio
import base64
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure agent modules are importable
sys.path.insert(0, str(Path(__file__).parent))
from agent_registry import AGENT_REGISTRY, get_token_env_key

load_dotenv("/opt/nexus/agents/.env")

GUILD_ID = int(os.getenv("GUILD_ID", "0"))
GUILD_NAME = "The Enterprise"

# Permissions: Send Messages, Embed Links, Attach Files, Read Message History,
#   View Channels, Use External Emojis, Read Messages
PERMISSIONS = 277025770560

# ── Extract client IDs from tokens ────────────────────────────────────

def get_bot_client_ids() -> dict[str, str]:
    """Return {agent_id: client_id} for all active (non-webhook) bots."""
    result = {}
    for agent_id in AGENT_REGISTRY:
        env_key = get_token_env_key(agent_id)
        token = os.getenv(env_key, "")
        if not token or token == "WEBHOOK_FALLBACK":
            continue
        try:
            client_id = base64.b64decode(token.split(".")[0] + "==").decode()
            result[agent_id] = client_id
        except Exception:
            pass
    return result


def get_oauth_url(client_id: str) -> str:
    return (
        f"https://discord.com/oauth2/authorize"
        f"?client_id={client_id}"
        f"&permissions={PERMISSIONS}"
        f"&integration_type=0"
        f"&scope=bot"
    )


# ── Category grouping ────────────────────────────────────────────────

CATEGORIES = [
    ("C-Suite", ["coo"]),
    ("Directors", [
        "compute_director", "storage_director", "network_director",
        "security_director", "blockchain_director", "ml_director",
        "quantum_director",
    ]),
    ("Compute Workers", ["compute_worker_1", "compute_worker_2", "compute_worker_3"]),
    ("Storage Workers", ["storage_worker_1", "storage_worker_2", "storage_worker_3"]),
    ("Network Workers", ["network_worker_1", "network_worker_2", "network_worker_3"]),
    ("Security Workers", ["security_worker_1", "security_worker_2", "security_worker_3"]),
    ("Blockchain Workers", ["blockchain_worker_1", "blockchain_worker_2", "blockchain_worker_3"]),
    ("ML Workers", ["ml_worker_1"]),
]


# ── Generate Markdown ─────────────────────────────────────────────────

def generate_markdown(client_ids: dict[str, str]) -> str:
    # Exclude CEO (already invited)
    to_invite = {k: v for k, v in client_ids.items() if k != "ceo"}
    count = len(to_invite)

    lines = [
        f"# NEXUS OS Discord Bot Invitations",
        f"",
        f"Invite **{count} bots** to \"{GUILD_NAME}\" (Guild ID: `{GUILD_ID}`)",
        f"",
        f"**Already invited:** CEO ✅ | **Remaining:** {count} bots",
        f"",
        f"---",
        f"",
        f"## Instructions",
        f"",
        f"For each link below:",
        f"1. Click the link (opens Discord authorization page)",
        f"2. Select **\"{GUILD_NAME}\"** from the server dropdown",
        f"3. Click **Authorize**",
        f"4. Complete CAPTCHA if prompted",
        f"5. Check the box next to the bot name",
        f"",
        f"> **Tip:** Open `invite_links.html` in a browser for an interactive",
        f"> helper with an \"Open All\" button and progress tracking.",
        f"",
        f"---",
        f"",
    ]

    for cat_name, agent_ids in CATEGORIES:
        members = [aid for aid in agent_ids if aid in to_invite]
        if not members:
            continue
        lines.append(f"### {cat_name} ({len(members)})")
        lines.append("")
        for aid in members:
            name = AGENT_REGISTRY[aid]["display_name"]
            url = get_oauth_url(to_invite[aid])
            lines.append(f"- [ ] **{name}** (`{aid}`): [Invite]({url})")
        lines.append("")

    lines += [
        "---",
        "",
        "## Post-Invite Verification",
        "",
        "After inviting all bots, run:",
        "```bash",
        "cd /opt/nexus/agents",
        "python3 invite_bots.py --verify",
        "```",
        "",
        "Then start the full hierarchy:",
        "```bash",
        "nohup python3 hierarchy_manager.py >> logs/hierarchy.log 2>&1 &",
        "tail -f logs/hierarchy.log",
        "```",
        "",
        "---",
        "",
        "## Troubleshooting",
        "",
        "| Problem | Fix |",
        "|---------|-----|",
        "| Bot shows offline after invite | Enable **Message Content Intent** in Discord Developer Portal → Bot settings |",
        "| \"Missing Permissions\" on invite | Use the exact URLs above (include all required permissions) |",
        "| Bot can't see channels | Check Server Settings → Roles → bot role has **View Channels** |",
        "| Bot joins but no response | Verify token in `.env` matches the invited bot application |",
    ]

    return "\n".join(lines) + "\n"


# ── Generate HTML ─────────────────────────────────────────────────────

def generate_html(client_ids: dict[str, str]) -> str:
    to_invite = {k: v for k, v in client_ids.items() if k != "ceo"}
    count = len(to_invite)

    bot_entries = []
    for cat_name, agent_ids in CATEGORIES:
        members = [aid for aid in agent_ids if aid in to_invite]
        if not members:
            continue
        items = []
        for aid in members:
            name = AGENT_REGISTRY[aid]["display_name"]
            url = get_oauth_url(to_invite[aid])
            items.append({"id": aid, "name": name, "url": url})
        bot_entries.append({"category": cat_name, "bots": items})

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>NEXUS OS — Invite {count} Bots</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Segoe UI', system-ui, sans-serif;
    background: #0d1117; color: #c9d1d9;
    max-width: 960px; margin: 0 auto; padding: 32px 16px;
  }}
  h1 {{ color: #58a6ff; margin-bottom: 8px; }}
  .subtitle {{ color: #8b949e; margin-bottom: 24px; }}
  .bar {{
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 16px 24px; margin-bottom: 24px; text-align: center;
  }}
  .bar .num {{ font-size: 36px; font-weight: 700; color: #58a6ff; }}
  .bar .label {{ color: #8b949e; }}
  .actions {{ text-align: center; margin-bottom: 24px; }}
  button {{
    background: #238636; color: #fff; border: none; border-radius: 6px;
    padding: 12px 24px; font-size: 15px; cursor: pointer; margin: 4px;
  }}
  button:hover {{ background: #2ea043; }}
  button.reset {{ background: #da3633; }}
  button.reset:hover {{ background: #f85149; }}
  .category {{
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    margin-bottom: 16px; overflow: hidden;
  }}
  .cat-head {{
    padding: 12px 16px; font-weight: 600; color: #58a6ff;
    border-bottom: 1px solid #30363d; font-size: 14px;
  }}
  .bot {{
    display: flex; align-items: center; padding: 10px 16px;
    border-bottom: 1px solid #21262d;
  }}
  .bot:last-child {{ border-bottom: none; }}
  .bot input {{ margin-right: 12px; transform: scale(1.3); accent-color: #238636; }}
  .bot a {{
    color: #c9d1d9; text-decoration: none; flex: 1;
  }}
  .bot a:hover {{ color: #58a6ff; text-decoration: underline; }}
  .bot .aid {{ color: #484f58; font-size: 12px; margin-left: 8px; }}
  .done {{ text-decoration: line-through; color: #484f58; }}
</style>
</head>
<body>

<h1>NEXUS OS Bot Invitations</h1>
<p class="subtitle">Invite {count} bots to "{GUILD_NAME}" — click each link, select the server, authorize.</p>

<div class="bar">
  <div class="num"><span id="done">0</span> / {count}</div>
  <div class="label">bots invited</div>
</div>

<div class="actions">
  <button onclick="openAll()">Open All Links (2 s delay each)</button>
  <button class="reset" onclick="resetAll()">Reset Progress</button>
</div>

""" + "\n".join(
        _html_category(cat)
        for cat in bot_entries
    ) + f"""

<script>
const TOTAL = {count};

function save() {{
  const state = {{}};
  document.querySelectorAll('.bot input').forEach(cb => state[cb.id] = cb.checked);
  localStorage.setItem('nexus_invite', JSON.stringify(state));
  const n = Object.values(state).filter(Boolean).length;
  document.getElementById('done').textContent = n;
  document.querySelectorAll('.bot').forEach(row => {{
    const cb = row.querySelector('input');
    row.querySelector('a').classList.toggle('done', cb.checked);
  }});
}}

function load() {{
  try {{
    const state = JSON.parse(localStorage.getItem('nexus_invite') || '{{}}');
    for (const [id, checked] of Object.entries(state)) {{
      const cb = document.getElementById(id);
      if (cb) cb.checked = checked;
    }}
  }} catch(e) {{}}
  save();
}}

function openAll() {{
  const links = [...document.querySelectorAll('.bot a')];
  const unchecked = links.filter(a => {{
    const cb = a.parentElement.querySelector('input');
    return !cb.checked;
  }});
  if (!unchecked.length) {{ alert('All bots already invited!'); return; }}
  if (!confirm('Open ' + unchecked.length + ' invite tabs (2 s apart)?')) return;
  unchecked.forEach((a, i) => {{
    setTimeout(() => {{
      window.open(a.href, '_blank');
      a.parentElement.querySelector('input').checked = true;
      save();
    }}, i * 2000);
  }});
}}

function resetAll() {{
  if (!confirm('Reset all progress?')) return;
  document.querySelectorAll('.bot input').forEach(cb => cb.checked = false);
  save();
}}

window.onload = load;
</script>
</body>
</html>
"""


def _html_category(cat: dict) -> str:
    rows = ""
    for b in cat["bots"]:
        rows += (
            f'<div class="bot">'
            f'<input type="checkbox" id="{b["id"]}" onchange="save()">'
            f'<a href="{b["url"]}" target="_blank" '
            f'onclick="this.parentElement.querySelector(\'input\').checked=true;save();">'
            f'{b["name"]}</a>'
            f'<span class="aid">{b["id"]}</span>'
            f'</div>\n'
        )
    return (
        f'<div class="category">\n'
        f'<div class="cat-head">{cat["category"]} ({len(cat["bots"])})</div>\n'
        f'{rows}</div>\n'
    )


# ── Verification ──────────────────────────────────────────────────────

async def verify_guild():
    """Check which bots are in the guild. Requires CEO token."""
    import discord

    ceo_token = os.getenv("CEO_TOKEN")
    if not ceo_token:
        print("ERROR: CEO_TOKEN not set")
        return

    client_ids = get_bot_client_ids()
    # Exclude CEO
    to_invite = {k: v for k, v in client_ids.items() if k != "ceo"}

    intents = discord.Intents.default()
    intents.guilds = True
    intents.members = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        guild = discord.utils.get(client.guilds, id=GUILD_ID)
        if not guild:
            print(f"ERROR: Guild {GUILD_ID} not found")
            await client.close()
            return

        # Get all bot members
        bot_ids_in_guild = set()
        for member in guild.members:
            if member.bot:
                bot_ids_in_guild.add(str(member.id))

        print(f"Guild: {guild.name} ({guild.member_count} members)")
        print(f"Bots in guild: {len(bot_ids_in_guild)}")
        print()

        in_guild = []
        missing = []
        for agent_id, cid in sorted(to_invite.items()):
            name = AGENT_REGISTRY[agent_id]["display_name"]
            if cid in bot_ids_in_guild:
                in_guild.append(agent_id)
                print(f"  [x] {name} ({agent_id})")
            else:
                missing.append(agent_id)
                print(f"  [ ] {name} ({agent_id}) — NOT IN GUILD")

        print()
        print(f"Invited: {len(in_guild)}/{len(to_invite)}")
        if missing:
            print(f"Missing: {len(missing)} — {', '.join(missing)}")
        else:
            print("All bots are in the guild!")

        await client.close()

    await client.start(ceo_token)


# ── Main ──────────────────────────────────────────────────────────────

def main():
    client_ids = get_bot_client_ids()
    to_invite = {k: v for k, v in client_ids.items() if k != "ceo"}

    if "--verify" in sys.argv:
        asyncio.run(verify_guild())
        return

    if "--urls" in sys.argv:
        # Just print URLs to stdout
        for cat_name, agent_ids in CATEGORIES:
            members = [aid for aid in agent_ids if aid in to_invite]
            if not members:
                continue
            print(f"\n=== {cat_name} ===")
            for aid in members:
                name = AGENT_REGISTRY[aid]["display_name"]
                url = get_oauth_url(to_invite[aid])
                print(f"  {name}: {url}")
        return

    # Generate files
    out_dir = Path(__file__).parent

    md = generate_markdown(client_ids)
    md_path = out_dir / "INVITE_INSTRUCTIONS.md"
    md_path.write_text(md)
    print(f"Created {md_path}")

    html = generate_html(client_ids)
    html_path = out_dir / "invite_links.html"
    html_path.write_text(html)
    print(f"Created {html_path}")

    print(f"\n{len(to_invite)} bots to invite (CEO already in guild)")
    print(f"\nNext steps:")
    print(f"  1. Open invite_links.html in a browser")
    print(f"     scp {html_path} yourpc:~/Desktop/")
    print(f"  2. Click 'Open All Links' and authorize each bot")
    print(f"  3. Verify: python3 invite_bots.py --verify")


if __name__ == "__main__":
    main()
