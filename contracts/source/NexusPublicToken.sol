// SPDX-License-Identifier: MIT
// ═══════════════════════════════════════════════════════════════
// DO NOT DEPLOY THIS CONTRACT without SEC legal review.
// Public token issuance may constitute a securities offering.
// This contract exists for design purposes only.
// Deployment requires: Howey Test analysis, legal opinion letter,
// and explicit approval from legal counsel.
// ═══════════════════════════════════════════════════════════════
pragma solidity ^0.8.19;

contract NexusPublicToken {
    // ── ERC-20 state ───────────────────────────────────────────────────
    string public constant name = "NEXUS";
    string public constant symbol = "NXS";
    uint8 public constant decimals = 18;

    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    // ── Token economics ────────────────────────────────────────────────
    uint256 public halvingInterval = 365 * 24;  // halve every year (in epochs)
    uint256 public baseEmission = 100e18;       // 100 NXS per epoch initially
    uint256 public currentEpoch;
    uint256 public totalBurned;

    // ── Staking ────────────────────────────────────────────────────────
    mapping(address => uint256) public stakes;
    mapping(address => uint256) public unstakeRequestTime;
    mapping(address => uint256) public unstakeRequestAmount;
    uint256 public constant COOLDOWN_PERIOD = 7 days;

    // ── Access control ─────────────────────────────────────────────────
    address public admin;

    // ── Events ─────────────────────────────────────────────────────────
    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    event Mined(address indexed contributor, uint256 contribution, uint256 minted, uint256 epoch);
    event Staked(address indexed staker, uint256 amount);
    event Slashed(address indexed staker, uint256 amount);
    event UnstakeRequested(address indexed staker, uint256 amount, uint256 availableAt);
    event Unstaked(address indexed staker, uint256 amount);
    event Burned(address indexed burner, uint256 amount);

    modifier onlyAdmin() {
        require(msg.sender == admin, "Not admin");
        _;
    }

    constructor() {
        admin = msg.sender;
    }

    // ── ERC-20 core ────────────────────────────────────────────────────

    function transfer(address to, uint256 amount) external returns (bool) {
        require(balanceOf[msg.sender] >= amount, "Insufficient balance");
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        emit Transfer(msg.sender, to, amount);
        return true;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        require(balanceOf[from] >= amount, "Insufficient balance");
        require(allowance[from][msg.sender] >= amount, "Insufficient allowance");
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        emit Transfer(from, to, amount);
        return true;
    }

    // ── Mining (earn-only distribution) ────────────────────────────────

    /// @notice Mint tokens for a contributor based on compute/storage/gradient contribution.
    /// No ICO, no presale, no airdrop — tokens are earned only.
    function mine(address contributor, uint256 computeContribution) external onlyAdmin {
        require(contributor != address(0), "Cannot mine to zero address");
        require(computeContribution > 0, "Zero contribution");

        uint256 emission = getCurrentEmissionRate();
        // Minted amount scales linearly with contribution, capped at emission rate
        uint256 minted = (emission * computeContribution) / 1e18;
        if (minted > emission) {
            minted = emission;
        }

        totalSupply += minted;
        balanceOf[contributor] += minted;
        currentEpoch++;

        emit Transfer(address(0), contributor, minted);
        emit Mined(contributor, computeContribution, minted, currentEpoch);
    }

    /// @notice Current emission rate after Bitcoin-style halvings.
    /// Emission = baseEmission / (2 ^ (currentEpoch / halvingInterval))
    function getCurrentEmissionRate() public view returns (uint256) {
        if (halvingInterval == 0) {
            return baseEmission;
        }
        uint256 halvings = currentEpoch / halvingInterval;
        if (halvings >= 64) {
            return 0;  // effectively zero after 64 halvings
        }
        return baseEmission >> halvings;
    }

    // ── Staking (prediction market) ────────────────────────────────────

    /// @notice Lock tokens for prediction staking.
    function stake(uint256 amount) external {
        require(balanceOf[msg.sender] >= amount, "Insufficient balance");
        balanceOf[msg.sender] -= amount;
        stakes[msg.sender] += amount;
        emit Staked(msg.sender, amount);
    }

    /// @notice Burn staked tokens for bad predictions.
    function slash(address staker, uint256 amount) external onlyAdmin {
        require(stakes[staker] >= amount, "Insufficient stake");
        stakes[staker] -= amount;
        totalSupply -= amount;
        totalBurned += amount;
        emit Slashed(staker, amount);
        emit Burned(staker, amount);
    }

    /// @notice Request unstake — begins 7-day cooldown period.
    function unstake(uint256 amount) external {
        require(stakes[msg.sender] >= amount, "Insufficient stake");

        // If there's a pending unstake request that has matured, finalize it first
        if (unstakeRequestAmount[msg.sender] > 0 &&
            block.timestamp >= unstakeRequestTime[msg.sender] + COOLDOWN_PERIOD) {
            _finalizeUnstake(msg.sender);
        }

        require(unstakeRequestAmount[msg.sender] == 0, "Existing unstake request pending");

        unstakeRequestTime[msg.sender] = block.timestamp;
        unstakeRequestAmount[msg.sender] = amount;

        emit UnstakeRequested(msg.sender, amount, block.timestamp + COOLDOWN_PERIOD);
    }

    /// @notice Finalize unstake after cooldown period has elapsed.
    function finalizeUnstake() external {
        require(unstakeRequestAmount[msg.sender] > 0, "No unstake request");
        require(
            block.timestamp >= unstakeRequestTime[msg.sender] + COOLDOWN_PERIOD,
            "Cooldown period not elapsed"
        );
        _finalizeUnstake(msg.sender);
    }

    function _finalizeUnstake(address staker) internal {
        uint256 amount = unstakeRequestAmount[staker];
        require(stakes[staker] >= amount, "Stake reduced during cooldown");

        stakes[staker] -= amount;
        balanceOf[staker] += amount;
        unstakeRequestAmount[staker] = 0;
        unstakeRequestTime[staker] = 0;

        emit Unstaked(staker, amount);
    }

    // ── Burn mechanics ─────────────────────────────────────────────────

    /// @notice Permanently destroy tokens from caller's balance.
    function burn(uint256 amount) external {
        require(balanceOf[msg.sender] >= amount, "Insufficient balance");
        balanceOf[msg.sender] -= amount;
        totalSupply -= amount;
        totalBurned += amount;
        emit Burned(msg.sender, amount);
        emit Transfer(msg.sender, address(0), amount);
    }
}
