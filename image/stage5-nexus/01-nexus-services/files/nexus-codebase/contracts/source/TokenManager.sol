// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract TokenManager {

    // ── State ────────────────────────────────────────────────────────────

    address public admin;

    mapping(address => uint256) public ectBalances;
    mapping(address => uint256) public rstBalances;

    mapping(address => bool) public authorizedMinters;
    mapping(address => bool) public authorizedSpenders;
    mapping(address => bool) public authorizedRSTManagers;

    uint256 public totalECTMinted;
    uint256 public totalECTSpent;
    uint256 public totalRSTEarned;
    uint256 public totalRSTSlashed;

    // ── Spending history ─────────────────────────────────────────────────

    struct SpendRecord {
        uint256 amount;
        bytes32 taskId;
        uint256 blockNum;
        uint256 timestamp;
    }

    mapping(address => SpendRecord[]) private _spendHistory;

    // ── RST history ──────────────────────────────────────────────────────

    struct RSTRecord {
        int256  amount;
        string  reason;
        uint256 blockNum;
        uint256 timestamp;
    }

    mapping(address => RSTRecord[]) private _rstHistory;

    // ── Events ───────────────────────────────────────────────────────────

    event AdminTransferred(address indexed oldAdmin, address indexed newAdmin);
    event ECTMinted(address indexed agent, uint256 amount, uint256 newBalance, uint256 timestamp);
    event ECTSpent(address indexed agent, uint256 amount, bytes32 indexed taskId, uint256 remaining, uint256 timestamp);
    event MinterAuthorized(address indexed agent, bool authorized);
    event SpenderAuthorized(address indexed agent, bool authorized);
    event RSTManagerAuthorized(address indexed agent, bool authorized);
    event RSTEarned(address indexed agent, uint256 amount, string reason, uint256 newBalance, uint256 timestamp);
    event RSTSlashed(address indexed agent, uint256 amount, string reason, uint256 newBalance, uint256 timestamp);

    // ── Modifiers ────────────────────────────────────────────────────────

    modifier onlyAdmin() {
        require(msg.sender == admin, "Not admin");
        _;
    }

    modifier onlyMinter() {
        require(authorizedMinters[msg.sender], "Not authorized minter");
        _;
    }

    modifier onlySpender() {
        require(authorizedSpenders[msg.sender], "Not authorized spender");
        _;
    }

    modifier onlyRSTManager() {
        require(authorizedRSTManagers[msg.sender], "Not authorized RST manager");
        _;
    }

    // ── Constructor ──────────────────────────────────────────────────────

    constructor() {
        admin = msg.sender;
    }

    // ── Admin ────────────────────────────────────────────────────────────

    function transferAdmin(address newAdmin) external onlyAdmin {
        require(newAdmin != address(0), "Zero address");
        emit AdminTransferred(admin, newAdmin);
        admin = newAdmin;
    }

    function setMinter(address agent, bool authorized) external onlyAdmin {
        authorizedMinters[agent] = authorized;
        emit MinterAuthorized(agent, authorized);
    }

    function setSpender(address agent, bool authorized) external onlyAdmin {
        authorizedSpenders[agent] = authorized;
        emit SpenderAuthorized(agent, authorized);
    }

    function setRSTManager(address agent, bool authorized) external onlyAdmin {
        authorizedRSTManagers[agent] = authorized;
        emit RSTManagerAuthorized(agent, authorized);
    }

    function batchSetSpenders(address[] calldata agents, bool authorized) external onlyAdmin {
        for (uint256 i = 0; i < agents.length; i++) {
            authorizedSpenders[agents[i]] = authorized;
            emit SpenderAuthorized(agents[i], authorized);
        }
    }

    // ── ECT Operations ───────────────────────────────────────────────────

    function mintDailyECT(address agent, uint256 amount) external onlyMinter {
        ectBalances[agent] += amount;
        totalECTMinted += amount;
        emit ECTMinted(agent, amount, ectBalances[agent], block.timestamp);
    }

    function batchMintECT(address[] calldata agents, uint256[] calldata amounts) external onlyMinter {
        require(agents.length == amounts.length, "Length mismatch");
        for (uint256 i = 0; i < agents.length; i++) {
            ectBalances[agents[i]] += amounts[i];
            totalECTMinted += amounts[i];
            emit ECTMinted(agents[i], amounts[i], ectBalances[agents[i]], block.timestamp);
        }
    }

    function spendECT(address agent, uint256 amount, bytes32 taskId) external onlySpender {
        require(ectBalances[agent] >= amount, "Insufficient ECT");
        ectBalances[agent] -= amount;
        totalECTSpent += amount;

        _spendHistory[agent].push(SpendRecord({
            amount: amount,
            taskId: taskId,
            blockNum: block.number,
            timestamp: block.timestamp
        }));

        emit ECTSpent(agent, amount, taskId, ectBalances[agent], block.timestamp);
    }

    // ── RST Operations ───────────────────────────────────────────────────

    function earnRST(address agent, uint256 amount, string calldata reason) external onlyRSTManager {
        rstBalances[agent] += amount;
        totalRSTEarned += amount;

        _rstHistory[agent].push(RSTRecord({
            amount: int256(amount),
            reason: reason,
            blockNum: block.number,
            timestamp: block.timestamp
        }));

        emit RSTEarned(agent, amount, reason, rstBalances[agent], block.timestamp);
    }

    function slashRST(address agent, uint256 amount, string calldata reason) external onlyRSTManager {
        if (amount > rstBalances[agent]) {
            amount = rstBalances[agent];
        }
        rstBalances[agent] -= amount;
        totalRSTSlashed += amount;

        _rstHistory[agent].push(RSTRecord({
            amount: -int256(amount),
            reason: reason,
            blockNum: block.number,
            timestamp: block.timestamp
        }));

        emit RSTSlashed(agent, amount, reason, rstBalances[agent], block.timestamp);
    }

    // ── Read: combined queries ───────────────────────────────────────────

    function getBalances(address agent) external view returns (uint256 ectBalance, uint256 rstBalance) {
        return (ectBalances[agent], rstBalances[agent]);
    }

    function getTotals() external view returns (
        uint256 ectMinted, uint256 ectSpent, uint256 rstEarned, uint256 rstSlashed
    ) {
        return (totalECTMinted, totalECTSpent, totalRSTEarned, totalRSTSlashed);
    }

    // ── Read: spending history ───────────────────────────────────────────

    function getSpendCount(address agent) external view returns (uint256) {
        return _spendHistory[agent].length;
    }

    function getSpendingHistory(
        address agent, uint256 startBlock, uint256 endBlock
    ) external view returns (
        uint256[] memory amounts,
        bytes32[] memory taskIds,
        uint256[] memory blocks,
        uint256[] memory timestamps
    ) {
        SpendRecord[] storage records = _spendHistory[agent];

        // Count matching records
        uint256 count = 0;
        for (uint256 i = 0; i < records.length; i++) {
            if (records[i].blockNum >= startBlock && records[i].blockNum <= endBlock) {
                count++;
            }
        }

        // Allocate arrays
        amounts = new uint256[](count);
        taskIds = new bytes32[](count);
        blocks = new uint256[](count);
        timestamps = new uint256[](count);

        // Fill arrays
        uint256 idx = 0;
        for (uint256 i = 0; i < records.length; i++) {
            if (records[i].blockNum >= startBlock && records[i].blockNum <= endBlock) {
                amounts[idx] = records[i].amount;
                taskIds[idx] = records[i].taskId;
                blocks[idx] = records[i].blockNum;
                timestamps[idx] = records[i].timestamp;
                idx++;
            }
        }
    }

    // ── Read: RST history ────────────────────────────────────────────────

    function getRSTHistoryCount(address agent) external view returns (uint256) {
        return _rstHistory[agent].length;
    }

    function getRSTRecord(address agent, uint256 index) external view returns (
        int256 amount, string memory reason, uint256 blockNum, uint256 timestamp
    ) {
        require(index < _rstHistory[agent].length, "Index out of bounds");
        RSTRecord storage r = _rstHistory[agent][index];
        return (r.amount, r.reason, r.blockNum, r.timestamp);
    }
}
