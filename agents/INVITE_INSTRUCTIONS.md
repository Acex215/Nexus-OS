# NEXUS OS Discord Bot Invitations

Invite **24 bots** to "The Enterprise" (Guild ID: `1441732155225931869`)

**Already invited:** CEO ✅ | **Remaining:** 24 bots

---

## Instructions

For each link below:
1. Click the link (opens Discord authorization page)
2. Select **"The Enterprise"** from the server dropdown
3. Click **Authorize**
4. Complete CAPTCHA if prompted
5. Check the box next to the bot name

> **Tip:** Open `invite_links.html` in a browser for an interactive
> helper with an "Open All" button and progress tracking.

---

### C-Suite (1)

- [ ] **NEXUS COO** (`coo`): [Invite](https://discord.com/oauth2/authorize?client_id=1470129085014348024&permissions=277025770560&integration_type=0&scope=bot)

### Directors (7)

- [ ] **Compute Director** (`compute_director`): [Invite](https://discord.com/oauth2/authorize?client_id=1470158449236246646&permissions=277025770560&integration_type=0&scope=bot)
- [ ] **Storage Director** (`storage_director`): [Invite](https://discord.com/oauth2/authorize?client_id=1470232013200953466&permissions=277025770560&integration_type=0&scope=bot)
- [ ] **Network Director** (`network_director`): [Invite](https://discord.com/oauth2/authorize?client_id=1470232609354289215&permissions=277025770560&integration_type=0&scope=bot)
- [ ] **Security Director** (`security_director`): [Invite](https://discord.com/oauth2/authorize?client_id=1470233271118856378&permissions=277025770560&integration_type=0&scope=bot)
- [ ] **Blockchain Director** (`blockchain_director`): [Invite](https://discord.com/oauth2/authorize?client_id=1470233618134859868&permissions=277025770560&integration_type=0&scope=bot)
- [ ] **ML Director** (`ml_director`): [Invite](https://discord.com/oauth2/authorize?client_id=1470233955939909766&permissions=277025770560&integration_type=0&scope=bot)
- [ ] **Quantum Director** (`quantum_director`): [Invite](https://discord.com/oauth2/authorize?client_id=1470235770714456136&permissions=277025770560&integration_type=0&scope=bot)

### Compute Workers (3)

- [ ] **Process Scheduler** (`compute_worker_1`): [Invite](https://discord.com/oauth2/authorize?client_id=1470237584100692136&permissions=277025770560&integration_type=0&scope=bot)
- [ ] **Load Balancer** (`compute_worker_2`): [Invite](https://discord.com/oauth2/authorize?client_id=1470237105891442863&permissions=277025770560&integration_type=0&scope=bot)
- [ ] **Resource Monitor** (`compute_worker_3`): [Invite](https://discord.com/oauth2/authorize?client_id=1470238313683357954&permissions=277025770560&integration_type=0&scope=bot)

### Storage Workers (3)

- [ ] **Backup Agent** (`storage_worker_1`): [Invite](https://discord.com/oauth2/authorize?client_id=1470239037234221167&permissions=277025770560&integration_type=0&scope=bot)
- [ ] **Cache Manager** (`storage_worker_2`): [Invite](https://discord.com/oauth2/authorize?client_id=1470239377455054931&permissions=277025770560&integration_type=0&scope=bot)
- [ ] **FLock Federator** (`storage_worker_3`): [Invite](https://discord.com/oauth2/authorize?client_id=1470241364246659207&permissions=277025770560&integration_type=0&scope=bot)

### Network Workers (3)

- [ ] **Mesh Coordinator** (`network_worker_1`): [Invite](https://discord.com/oauth2/authorize?client_id=1470255304263336161&permissions=277025770560&integration_type=0&scope=bot)
- [ ] **VPN Manager** (`network_worker_2`): [Invite](https://discord.com/oauth2/authorize?client_id=1470255894632595602&permissions=277025770560&integration_type=0&scope=bot)
- [ ] **DNS Agent** (`network_worker_3`): [Invite](https://discord.com/oauth2/authorize?client_id=1470256218210701482&permissions=277025770560&integration_type=0&scope=bot)

### Security Workers (3)

- [ ] **Auth Agent** (`security_worker_1`): [Invite](https://discord.com/oauth2/authorize?client_id=1470503109892505808&permissions=277025770560&integration_type=0&scope=bot)
- [ ] **Anomaly Detector** (`security_worker_2`): [Invite](https://discord.com/oauth2/authorize?client_id=1470503441532063777&permissions=277025770560&integration_type=0&scope=bot)
- [ ] **Audit Logger** (`security_worker_3`): [Invite](https://discord.com/oauth2/authorize?client_id=1470503676543242260&permissions=277025770560&integration_type=0&scope=bot)

### Blockchain Workers (3)

- [ ] **Contract Deployer** (`blockchain_worker_1`): [Invite](https://discord.com/oauth2/authorize?client_id=1470503942214521104&permissions=277025770560&integration_type=0&scope=bot)
- [ ] **Token Manager** (`blockchain_worker_2`): [Invite](https://discord.com/oauth2/authorize?client_id=1470504539323895848&permissions=277025770560&integration_type=0&scope=bot)
- [ ] **Consensus Monitor** (`blockchain_worker_3`): [Invite](https://discord.com/oauth2/authorize?client_id=1470504863547920564&permissions=277025770560&integration_type=0&scope=bot)

### ML Workers (1)

- [ ] **Training Coordinator** (`ml_worker_1`): [Invite](https://discord.com/oauth2/authorize?client_id=1470505247070884048&permissions=277025770560&integration_type=0&scope=bot)

---

## Post-Invite Verification

After inviting all bots, run:
```bash
cd /opt/nexus/agents
python3 invite_bots.py --verify
```

Then start the full hierarchy:
```bash
nohup python3 hierarchy_manager.py >> logs/hierarchy.log 2>&1 &
tail -f logs/hierarchy.log
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Bot shows offline after invite | Enable **Message Content Intent** in Discord Developer Portal → Bot settings |
| "Missing Permissions" on invite | Use the exact URLs above (include all required permissions) |
| Bot can't see channels | Check Server Settings → Roles → bot role has **View Channels** |
| Bot joins but no response | Verify token in `.env` matches the invited bot application |
