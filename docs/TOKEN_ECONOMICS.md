# NEXUS Token Economics

> **DISCLAIMER:** This document is for internal planning purposes only. It does not constitute a securities offering or financial advice. Consult legal counsel before any public token issuance.

---

## 1. Token Overview

**NEXUS (NXS)** is an ERC-20 utility token on the NEXUS PoA chain (Chain ID 123454321). It is the public-facing participation token for the NEXUS network.

Key properties:

- **Name:** NEXUS
- **Symbol:** NXS
- **Decimals:** 18
- **Distribution model:** Earn-only (no ICO, no presale, no airdrop)
- **Contract:** `NexusPublicToken.sol` (compiled, NOT deployed — pending legal review)

NXS is modeled after Numerai's NMR token: it exists to provide a genuine, day-one utility requirement for network participation. You cannot contribute to or consume the network's federated intelligence without holding and staking NXS.

There is no "investment round" for NXS. The only way to obtain tokens is to contribute compute, storage, or gradient updates to the network. This is a deliberate design choice to distance the token from securities classification.

---

## 2. Relationship to ECT / RST / NXS

The NEXUS network operates three distinct token types. They serve fundamentally different purposes and should not be conflated.

### ECT — Estimated Compute Time (Internal, Ephemeral)

- **Purpose:** Daily compute credits allocated to temporal bins
- **Lifecycle:** Minted each scheduling cycle, consumed by task execution, expires at cycle end
- **Tradeable:** No — purely internal accounting unit
- **On-chain:** Tracked in TemporalScheduler contract
- **Analogy:** CPU time-slices in an operating system

ECT answers the question: "How much compute does this task get today?"

### RST — Reputation Score Token (Internal, Persistent)

- **Purpose:** Cumulative reputation reflecting quality of contributions over time
- **Lifecycle:** Earned by successful task completion, reduced by failures. Never traded, never cashed out
- **Tradeable:** No — soulbound to the contributor address
- **On-chain:** Tracked in DecisionQuality contract
- **Analogy:** Karma or credit score

RST answers the question: "How reliable is this contributor?"

### NXS — NEXUS Token (Public, Persistent)

- **Purpose:** Network participation token with genuine utility requirement
- **Lifecycle:** Mined through contributions, staked for predictions, burned on bad outcomes
- **Tradeable:** Yes — standard ERC-20, transferable between addresses
- **On-chain:** NexusPublicToken contract
- **Analogy:** Numerai's NMR

NXS answers the question: "Does this participant have skin in the game?"

### How They Interact

```
Contribution → ECT consumed → Task executed → RST earned/lost
                                                    │
                                                    ▼
                                          NXS mining rate scales
                                          with RST score
                                                    │
                                                    ▼
                                          NXS staked on predictions
                                                    │
                                              ┌─────┴─────┐
                                              ▼           ▼
                                          Good pred.  Bad pred.
                                          NXS reward  NXS slashed
                                                      (burned)
```

The critical relationship: **NXS earn rate is proportional to RST score.** A contributor with RST of 0.9 earns NXS at 90% of the emission rate; a contributor with RST of 0.3 earns at 30%. This ensures that token distribution flows to consistently reliable participants, not one-time contributors.

---

## 3. Emission Schedule

NXS uses a Bitcoin-style halving model to create predictable, decreasing supply inflation.

### Parameters

| Parameter | Value |
|-----------|-------|
| Base emission | 100 NXS per epoch |
| Halving interval | 8,760 epochs (365 days × 24 hours) |
| Maximum halvings | 64 (emission effectively zero after) |
| Epoch trigger | Each successful `mine()` call advances epoch by 1 |

### Halving Schedule

| Year | Epochs | Emission per Epoch | Cumulative Supply (approx.) |
|------|--------|-------------------|---------------------------|
| 1 | 0–8,759 | 100 NXS | 876,000 NXS |
| 2 | 8,760–17,519 | 50 NXS | 1,314,000 NXS |
| 3 | 17,520–26,279 | 25 NXS | 1,533,000 NXS |
| 4 | 26,280–35,039 | 12.5 NXS | 1,642,500 NXS |
| 5 | 35,040–43,799 | 6.25 NXS | 1,697,250 NXS |
| ... | ... | ... | ... |
| 10 | ... | 0.195 NXS | ~1,750,000 NXS |

### Projected Supply Curve

```
Supply
(NXS)
  │
1.75M ┤ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  asymptote
  │                          ●──────────────────
  │                     ●───╯
  │                ●──╯
  │           ●──╯
  │       ●─╯
  │    ●╯
  │  ●╯
  │ ●
  │●
  └──┬──┬──┬──┬──┬──┬──┬──┬──┬──→  Year
     1  2  3  4  5  6  7  8  9  10
```

The theoretical maximum supply approaches ~1,752,000 NXS (geometric series: 876,000 × 2). Actual supply will be lower due to burn mechanics.

### Important Note on Supply

Unlike Bitcoin, where blocks are produced on a fixed schedule, NXS epochs advance only when `mine()` is called. In periods of low network activity, fewer epochs elapse and fewer tokens are minted. The halving schedule is measured in epochs, not wall-clock time. This means the actual time between halvings may be longer than one year if the network is underutilized.

---

## 4. Mining

In the NEXUS context, "mining" does not mean proof-of-work hash computation. It means contributing useful resources to the network.

### What Counts as Mining

| Contribution Type | Description | Measurement |
|-------------------|-------------|-------------|
| **Compute** | Running inference or training tasks via the agent mesh | CPU/GPU-hours verified by task completion |
| **Storage** | Pinning IPFS data for the network's knowledge base | GB-hours of verified pinning (StorageRegistry) |
| **Gradients** | Contributing federated learning updates to the meta-model | Gradient quality score from FlockCoordinator |

### How Mining Works

1. Contributor performs work (compute task, pin data, submit gradient)
2. Work is verified on-chain (task completion logged, pin verified, gradient validated)
3. Admin calls `mine(contributor, computeContribution)` with verified contribution amount
4. Contract calculates: `minted = getCurrentEmissionRate() × contribution / 1e18`
5. Minted amount is capped at the current emission rate per epoch
6. NXS is credited to contributor's balance
7. Epoch counter advances

### Mining Rate Modifiers

- **RST multiplier:** Effective contribution is scaled by the contributor's reputation score. High-reputation contributors earn more NXS per unit of work.
- **Halving:** The emission rate decreases over time, making early contributions more valuable.
- **Contribution cap:** No single epoch can mint more than the emission rate, preventing contribution inflation attacks.

---

## 5. Staking

Staking locks NXS tokens to participate in the network's prediction tournaments. It provides the "skin in the game" that aligns participant incentives with network quality.

### Staking Mechanics

1. **Lock:** Call `stake(amount)` to transfer NXS from balance to staked pool
2. **Participate:** Staked tokens enable participation in prediction tournaments (tournament selection, model evaluation, meta-model contribution weighting)
3. **Outcome:**
   - Correct/valuable predictions → retain stake, earn additional NXS through mining rewards
   - Poor predictions → stake is partially or fully slashed (burned)

### Unstaking

Unstaking follows a cooldown model to prevent stake-and-flee attacks:

1. Call `unstake(amount)` to begin the cooldown period
2. **7-day cooldown** — tokens remain locked and subject to slashing
3. After cooldown, call `finalizeUnstake()` to return tokens to liquid balance
4. Only one unstake request can be pending at a time

### Why Staking Matters

Without staking, any participant could submit noise predictions at zero cost. Staking ensures:

- **Quality filter:** Contributors with low conviction don't stake large amounts
- **Sybil resistance:** Creating many fake accounts doesn't help without tokens to stake
- **Alignment:** Participants profit when the network improves, lose when it degrades

---

## 6. Burn Mechanics

Token burning permanently removes NXS from circulation. This creates deflationary pressure that counterbalances emission.

### When Tokens Are Burned

| Burn Trigger | Mechanism | Purpose |
|-------------|-----------|---------|
| **Slashing** | Admin calls `slash(staker, amount)` after verified bad prediction | Penalize poor contributions |
| **Voluntary burn** | User calls `burn(amount)` | Deflationary signal / token removal |
| **Protocol burn** | Future: percentage of transaction fees burned | Ongoing supply reduction |

### Burn Tracking

- `totalBurned` state variable tracks cumulative burned tokens
- Burn events are emitted and indexed for transparency
- Effective circulating supply = `totalSupply` (which already excludes burned tokens, since `totalSupply` is decremented on burn)

### Net Supply Dynamics

```
Net supply change per epoch = emission - burns

If burns > emission → deflationary (supply shrinking)
If burns < emission → inflationary (supply growing, but decelerating due to halvings)
```

Over time, as emission rate halves repeatedly and approaches zero, even modest burn rates will make the token deflationary.

---

## 7. Howey Test Analysis

The Howey Test (SEC v. W.J. Howey Co., 1946) determines whether a transaction qualifies as an "investment contract" (and therefore a security). All four prongs must be met.

### Prong 1: Investment of Money

**Question:** Is there an investment of money or other consideration?

**Analysis:** No direct monetary investment. NXS tokens are earned exclusively through compute, storage, and gradient contributions. There is no ICO, presale, token sale, or airdrop. Contributors invest electricity and hardware time, not money.

**Assessment:** Likely does NOT satisfy this prong. However, the SEC has historically interpreted "investment" broadly. If contributors purchase hardware specifically to mine NXS, this could be construed as an indirect investment.

**Mitigation:** Emphasize that NXS is a byproduct of useful work (federated learning), not the primary motivation. Contributors receive compute results regardless of NXS rewards.

### Prong 2: Common Enterprise

**Question:** Is there a common enterprise (horizontal or vertical commonality)?

**Analysis:** This is the weakest point. The NEXUS network exhibits horizontal commonality: participants pool resources (compute, data, gradients) and share in the resulting meta-model improvement. One contributor's work benefits all others through improved model quality.

**Assessment:** Likely DOES satisfy this prong. Network effects create interdependence among participants.

### Prong 3: Expectation of Profits

**Question:** Is there a reasonable expectation of profits derived from the investment?

**Analysis:** NXS has genuine, day-one utility: it is required to participate in prediction tournaments and to access network services. The primary value proposition is utility, not speculation. However, the halving schedule and burn mechanics create scarcity, which could drive speculative interest.

**Assessment:** Mixed. If positioned correctly as a utility token with a genuine use requirement, this prong may not be satisfied. But if NXS develops secondary market trading, holders may acquire tokens primarily for appreciation — which could change the analysis.

**Mitigation:**
- No promises of price appreciation in any materials
- Emphasize utility: "NXS is required to use the network"
- Implement lockup/vesting that discourages pure speculation
- Avoid listing on speculative exchanges initially

### Prong 4: Efforts of Others

**Question:** Are profits derived primarily from the efforts of others?

**Analysis:** Partially. The meta-model's improvement is a collective effort — individual NXS value is influenced by the quality of other contributors' work. However, each participant's NXS earnings depend significantly on their own contributions (compute quality, gradient accuracy, RST score).

**Assessment:** Partially satisfied. The RST-proportional earning mechanism helps: your returns are predominantly driven by your own contribution quality, not the efforts of a central promoter.

**Mitigation:**
- No central team making promises about token value
- Decentralized validation (PoA with multiple validators)
- Individual earnings tied to individual effort via RST

### Overall Assessment

```
Prong 1 (Investment):       Likely NO  ✓
Prong 2 (Common Enterprise): Likely YES ✗
Prong 3 (Profit Expectation): Mixed    ?
Prong 4 (Efforts of Others):  Partial  ?
```

**Conclusion:** The token most likely passes the Howey Test as a utility token IF:
1. Distribution remains earn-only (no sale of any kind)
2. Genuine utility is maintained (required for network participation)
3. No promotional materials suggest investment returns
4. Individual earnings scale with individual effort

**However, this analysis is not a legal opinion. A qualified securities attorney must review before any deployment.**

---

## 8. Regulatory Comparison: Numerai NMR

The NXS design is explicitly modeled after Numerai's NMR token, which has operated since 2017 without SEC enforcement action.

### NMR Design Choices We Follow

| NMR Approach | NXS Equivalent |
|-------------|----------------|
| Earn-only via data science tournaments | Earn-only via compute/storage/gradient contribution |
| Stake on predictions, slashed for bad models | Stake on predictions, slashed for bad outcomes |
| Burn mechanics for failed stakes | Identical burn-on-slash |
| Genuine utility requirement (must stake to compete) | Must hold NXS to participate in network |
| Traditional VC funding separate from token | Company funding independent of NXS |

### Key Differences from NMR

| Aspect | NMR | NXS |
|--------|-----|-----|
| Initial distribution | Had an initial distribution event in 2017 | Strictly earn-only from genesis |
| Network scope | Data science predictions on stock market | Federated learning across compute/storage/inference |
| Chain | Ethereum mainnet (ERC-20) | NEXUS PoA chain (ERC-20 compatible) |
| Halving | No halving mechanism | Bitcoin-style halving schedule |

### Why NMR Hasn't Been Classified as a Security

1. Genuine utility: required to participate in Numerai tournaments
2. No fundraising via token sale (post-2017 restructuring)
3. Burns create genuine economic consequences for bad predictions
4. Individual returns based on individual model quality, not Numerai team efforts

We replicate all four of these properties.

---

## 9. Timeline

### Phase 1: Legal Foundation (Current)

- [ ] Contract design complete (`NexusPublicToken.sol` — compiled, not deployed)
- [ ] Token economics document (this document)
- [ ] Internal review and iteration
- [ ] Engage securities attorney for Howey Test opinion
- [ ] Obtain written legal opinion letter

### Phase 2: Legal Review

- [ ] Attorney reviews contract code, economics, and distribution model
- [ ] Revise contract based on legal feedback
- [ ] Determine jurisdictional requirements
- [ ] Assess whether any registration or exemption filing is needed
- [ ] Obtain explicit written approval to proceed

### Phase 3: Pilot (Closed Network)

- [ ] Deploy NexusPublicToken to NEXUS PoA chain
- [ ] Mining enabled for existing validator nodes only
- [ ] Staking and slashing tested in controlled environment
- [ ] No external transfers — tokens locked to pilot participants
- [ ] Monitor emission/burn dynamics over 90-day pilot

### Phase 4: Limited Release

- [ ] Extend mining to approved external contributors
- [ ] Enable transfers between approved participants
- [ ] Establish minimum utility requirements (must stake to use network services)
- [ ] Audit: independent smart contract security audit
- [ ] Finalize governance model for admin key (multisig or DAO)

### Phase 5: Public Release

- [ ] Remove admin restrictions (decentralize mining authorization)
- [ ] Open network participation
- [ ] Community governance for protocol parameters
- [ ] Ongoing legal compliance monitoring

**No phase begins without explicit legal approval for that phase.**

---

> **DISCLAIMER:** This document is for internal planning purposes only. It does not constitute a securities offering or financial advice. Consult legal counsel before any public token issuance. No tokens have been issued, sold, or distributed. The NEXUS token does not exist as a tradeable asset as of the date of this document.
