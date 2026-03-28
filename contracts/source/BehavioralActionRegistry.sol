// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title BehavioralActionRegistry
 * @notice Records every user behavioral action as an on-chain event.
 *         Actions are typed, timestamped, and linked to the user's wallet.
 *         High-frequency actions are batched. Significant actions are individual.
 *         Compound tokens aggregate action sequences for correlation analysis.
 *
 * @dev Architecture:
 *   - Each action has a channelId (uint8) identifying the collection channel
 *   - Each action has an actionType (uint16) identifying the specific action
 *   - Action data is stored as bytes (ABI-encoded, schema varies by channel)
 *   - Compound tokens reference a range of actionIds and store aggregate data
 *   - Developer debug mode allows reading raw action data (disabled before launch)
 *
 * @dev Gas considerations:
 *   - Private chain, gas price = 0, gas limit = 30M
 *   - Each individual action: ~50-80K gas
 *   - Each batch (1-second aggregate): ~100-200K gas
 *   - Each compound token: ~80-120K gas
 *   - At 4,200 tx/hr = ~1.17 tx/sec, well within 10 tx/sec capacity
 */
contract BehavioralActionRegistry {

    // ═══════════════════════════════════════════
    // CHANNEL IDs — one per collection channel
    // ═══════════════════════════════════════════
    uint8 public constant CHANNEL_KEYSTROKE = 1;
    uint8 public constant CHANNEL_MOUSE = 2;
    uint8 public constant CHANNEL_WINDOW = 3;
    uint8 public constant CHANNEL_WEB = 4;
    uint8 public constant CHANNEL_MESSAGE = 5;
    uint8 public constant CHANNEL_FILE = 6;
    uint8 public constant CHANNEL_CLIPBOARD = 7;
    uint8 public constant CHANNEL_SYSTEM = 8;
    uint8 public constant CHANNEL_SESSION = 9;
    uint8 public constant CHANNEL_APP_LIFECYCLE = 10;
    uint8 public constant CHANNEL_GPS = 11;
    uint8 public constant CHANNEL_WEATHER = 12;
    uint8 public constant CHANNEL_WIFI = 13;
    uint8 public constant CHANNEL_AUDIO = 14;
    uint8 public constant CHANNEL_DISPLAY = 15;
    uint8 public constant CHANNEL_POWER = 16;
    uint8 public constant CHANNEL_PERIPHERAL = 17;
    uint8 public constant CHANNEL_NOTIFICATION = 18;
    uint8 public constant CHANNEL_COMPOUND = 255;

    // ═══════════════════════════════════════════
    // ACTION TYPES per channel (uint16)
    // Each channel has its own action type namespace
    // Full list defined in collector Python code
    // ═══════════════════════════════════════════

    // Keystroke channel (1)
    uint16 public constant KS_BATCH = 1;        // 1-second batch of keystrokes
    uint16 public constant KS_BURST_START = 2;   // Start of fast typing burst
    uint16 public constant KS_BURST_END = 3;     // End of fast typing burst
    uint16 public constant KS_LONG_PAUSE = 4;    // Pause > 5 seconds (thinking)
    uint16 public constant KS_DELETE_BURST = 5;  // Rapid deletion (self-editing)
    uint16 public constant KS_SHORTCUT = 6;      // Keyboard shortcut (Ctrl+X etc)

    // Mouse channel (2)
    uint16 public constant MS_BATCH = 1;         // 1-second position/movement batch
    uint16 public constant MS_CLICK = 2;         // Individual click (significant)
    uint16 public constant MS_DOUBLE_CLICK = 3;
    uint16 public constant MS_RIGHT_CLICK = 4;
    uint16 public constant MS_DRAG_START = 5;
    uint16 public constant MS_DRAG_END = 6;
    uint16 public constant MS_SCROLL = 7;        // Scroll event batch (1-sec)
    uint16 public constant MS_HOVER_LONG = 8;    // Hover > 2 sec (decision hesitation)

    // Window channel (3)
    uint16 public constant WIN_FOCUS = 1;        // Window gained focus
    uint16 public constant WIN_BLUR = 2;         // Window lost focus
    uint16 public constant WIN_OPEN = 3;         // New window opened
    uint16 public constant WIN_CLOSE = 4;        // Window closed
    uint16 public constant WIN_RESIZE = 5;
    uint16 public constant WIN_MOVE = 6;
    uint16 public constant WIN_MINIMIZE = 7;
    uint16 public constant WIN_MAXIMIZE = 8;
    uint16 public constant WIN_TITLE_CHANGE = 9; // Title changed (e.g. new tab in browser)

    // Web channel (4)
    uint16 public constant WEB_URL_VISIT = 1;    // New URL loaded
    uint16 public constant WEB_SEARCH = 2;       // Search query submitted
    uint16 public constant WEB_TAB_OPEN = 3;
    uint16 public constant WEB_TAB_CLOSE = 4;
    uint16 public constant WEB_TAB_SWITCH = 5;
    uint16 public constant WEB_SCROLL_DEPTH = 6; // Scroll depth checkpoint (25/50/75/100%)
    uint16 public constant WEB_FORM_SUBMIT = 7;
    uint16 public constant WEB_DOWNLOAD = 8;
    uint16 public constant WEB_PAGE_RELOAD = 9;  // Reload (impatience signal if < 5s)
    uint16 public constant WEB_BACK = 10;
    uint16 public constant WEB_FORWARD = 11;
    uint16 public constant WEB_BOOKMARK = 12;

    // Message channel (5)
    uint16 public constant MSG_SENT = 1;
    uint16 public constant MSG_RECEIVED = 2;
    uint16 public constant MSG_READ = 3;         // User read a received message
    uint16 public constant MSG_TYPING_START = 4; // User started typing a reply
    uint16 public constant MSG_TYPING_STOP = 5;  // User stopped typing (abandoned?)
    uint16 public constant MSG_DELETE = 6;       // Deleted a message
    uint16 public constant MSG_REACTION = 7;     // Emoji reaction
    uint16 public constant MSG_CALL_START = 8;
    uint16 public constant MSG_CALL_END = 9;

    // File channel (6)
    uint16 public constant FILE_OPEN = 1;
    uint16 public constant FILE_CLOSE = 2;
    uint16 public constant FILE_SAVE = 3;
    uint16 public constant FILE_CREATE = 4;
    uint16 public constant FILE_DELETE = 5;
    uint16 public constant FILE_RENAME = 6;
    uint16 public constant FILE_MOVE = 7;
    uint16 public constant FILE_COPY = 8;
    uint16 public constant FILE_DOWNLOAD = 9;
    uint16 public constant FILE_UPLOAD = 10;
    uint16 public constant FILE_PERMISSION = 11; // Permission change

    // Clipboard channel (7)
    uint16 public constant CLIP_COPY = 1;
    uint16 public constant CLIP_CUT = 2;
    uint16 public constant CLIP_PASTE = 3;
    uint16 public constant CLIP_CLEAR = 4;

    // System channel (8)
    uint16 public constant SYS_RESOURCE_SNAPSHOT = 1; // CPU/RAM/disk every 10s
    uint16 public constant SYS_PROCESS_START = 2;
    uint16 public constant SYS_PROCESS_END = 3;
    uint16 public constant SYS_PROCESS_CRASH = 4;
    uint16 public constant SYS_NETWORK_IO = 5;   // Network bytes batch (10s)
    uint16 public constant SYS_DISK_IO = 6;      // Disk read/write batch (10s)

    // Session channel (9)
    uint16 public constant SESS_LOGIN = 1;
    uint16 public constant SESS_LOGOUT = 2;
    uint16 public constant SESS_LOCK = 3;
    uint16 public constant SESS_UNLOCK = 4;
    uint16 public constant SESS_IDLE_START = 5;  // No input > 30 sec
    uint16 public constant SESS_IDLE_END = 6;
    uint16 public constant SESS_BREAK_START = 7; // No input > 5 min
    uint16 public constant SESS_BREAK_END = 8;

    // App lifecycle channel (10)
    uint16 public constant APP_LAUNCH = 1;
    uint16 public constant APP_EXIT = 2;
    uint16 public constant APP_CRASH = 3;
    uint16 public constant APP_INSTALL = 4;
    uint16 public constant APP_UNINSTALL = 5;
    uint16 public constant APP_UPDATE = 6;

    // GPS channel (11)
    uint16 public constant GPS_POSITION = 1;     // Lat/lon every 30s
    uint16 public constant GPS_SPEED = 2;        // Movement speed
    uint16 public constant GPS_GEOFENCE_ENTER = 3;
    uint16 public constant GPS_GEOFENCE_EXIT = 4;

    // Weather channel (12)
    uint16 public constant WEATHER_SNAPSHOT = 1;  // Full weather every 15min
    uint16 public constant WEATHER_ALERT = 2;     // Weather alert triggered

    // WiFi channel (13)
    uint16 public constant WIFI_CONNECTED = 1;
    uint16 public constant WIFI_DISCONNECTED = 2;
    uint16 public constant WIFI_SCAN = 3;         // Available networks snapshot
    uint16 public constant WIFI_SIGNAL_STRENGTH = 4; // RSSI every 60s

    // Audio channel (14)
    uint16 public constant AUDIO_VOLUME_UP = 1;
    uint16 public constant AUDIO_VOLUME_DOWN = 2;
    uint16 public constant AUDIO_MUTE = 3;
    uint16 public constant AUDIO_UNMUTE = 4;
    uint16 public constant AUDIO_OUTPUT_CHANGE = 5; // Speaker → headphones etc
    uint16 public constant AUDIO_PLAYBACK_START = 6;
    uint16 public constant AUDIO_PLAYBACK_STOP = 7;

    // Display channel (15)
    uint16 public constant DISP_BRIGHTNESS_UP = 1;
    uint16 public constant DISP_BRIGHTNESS_DOWN = 2;
    uint16 public constant DISP_RESOLUTION_CHANGE = 3;
    uint16 public constant DISP_MONITOR_CONNECT = 4;
    uint16 public constant DISP_MONITOR_DISCONNECT = 5;
    uint16 public constant DISP_SCREENSHOT = 6;

    // Power channel (16)
    uint16 public constant PWR_BATTERY_LEVEL = 1;   // If applicable
    uint16 public constant PWR_CHARGING_START = 2;
    uint16 public constant PWR_CHARGING_STOP = 3;
    uint16 public constant PWR_SLEEP = 4;
    uint16 public constant PWR_WAKE = 5;
    uint16 public constant PWR_SHUTDOWN_INIT = 6;
    uint16 public constant PWR_REBOOT_INIT = 7;

    // Peripheral channel (17)
    uint16 public constant PERIPH_USB_CONNECT = 1;
    uint16 public constant PERIPH_USB_DISCONNECT = 2;
    uint16 public constant PERIPH_BLUETOOTH_CONNECT = 3;
    uint16 public constant PERIPH_BLUETOOTH_DISCONNECT = 4;
    uint16 public constant PERIPH_PRINTER_JOB = 5;

    // Notification channel (18)
    uint16 public constant NOTIF_RECEIVED = 1;
    uint16 public constant NOTIF_CLICKED = 2;
    uint16 public constant NOTIF_DISMISSED = 3;
    uint16 public constant NOTIF_TIMEOUT = 4;     // Notification expired unread

    // ═══════════════════════════════════════════
    // DATA STRUCTURES
    // ═══════════════════════════════════════════

    struct Action {
        address user;           // User wallet (device identity)
        uint8 channelId;        // Which collection channel
        uint16 actionType;      // Specific action within channel
        uint32 timestamp;       // Unix timestamp (uint32 sufficient until 2106)
        uint16 epochMs;         // Milliseconds within the second (0-999)
        bytes32 dataHash;       // keccak256 of the action data
        bytes data;             // ABI-encoded action payload (schema varies by channel)
    }

    struct CompoundToken {
        address user;
        uint256 startActionId;  // First action in the compound
        uint256 endActionId;    // Last action in the compound
        uint32 startTime;
        uint32 endTime;
        uint8 actionCount;      // Number of individual actions wrapped
        uint8[] channelIds;     // Which channels are represented
        bytes32 correlationHash; // Hash of the action sequence pattern
        bytes aggregateData;    // Aggregate statistics of the wrapped actions
    }

    // ═══════════════════════════════════════════
    // STATE
    // ═══════════════════════════════════════════

    mapping(uint256 => Action) public actions;
    uint256 public actionCount;

    mapping(uint256 => CompoundToken) public compoundTokens;
    uint256 public compoundCount;

    // Per-user action indices for efficient querying
    mapping(address => uint256[]) public userActionIds;
    mapping(address => uint256[]) public userCompoundIds;

    // Per-user per-channel action counts (for stats)
    mapping(address => mapping(uint8 => uint256)) public channelActionCounts;

    // Developer debug mode (MUST be disabled before public launch)
    bool public debugMode;
    address public admin;
    bool public adminLocked; // Once true, cannot be undone

    // Consent tracking
    mapping(address => bool) public hasConsent;
    mapping(address => uint256) public consentGrantedAt;
    mapping(address => uint256) public consentRevokedAt;

    // ═══════════════════════════════════════════
    // EVENTS (indexed for efficient log querying)
    // ═══════════════════════════════════════════

    event ActionRecorded(
        uint256 indexed actionId,
        address indexed user,
        uint8 indexed channelId,
        uint16 actionType,
        uint32 timestamp,
        bytes32 dataHash
    );

    event BatchRecorded(
        uint256 indexed startActionId,
        address indexed user,
        uint8 indexed channelId,
        uint16 actionType,
        uint32 timestamp,
        uint256 count
    );

    event CompoundMinted(
        uint256 indexed compoundId,
        address indexed user,
        uint256 startActionId,
        uint256 endActionId,
        uint8 actionCount,
        bytes32 correlationHash
    );

    event ConsentGranted(address indexed user, uint256 timestamp);
    event ConsentRevoked(address indexed user, uint256 timestamp);
    event DebugModeDisabled(uint256 timestamp);
    event AdminLocked(uint256 timestamp);

    // ═══════════════════════════════════════════
    // MODIFIERS
    // ═══════════════════════════════════════════

    modifier onlyAdmin() {
        require(msg.sender == admin, "Not admin");
        _;
    }

    modifier onlyConsented() {
        require(hasConsent[msg.sender], "No consent");
        _;
    }

    modifier debugOnly() {
        require(debugMode, "Debug mode disabled");
        require(msg.sender == admin, "Not admin");
        _;
    }

    // ═══════════════════════════════════════════
    // CONSTRUCTOR
    // ═══════════════════════════════════════════

    constructor() {
        admin = msg.sender;
        debugMode = true;  // Enabled during development
        adminLocked = false;
    }

    // ═══════════════════════════════════════════
    // CONSENT MANAGEMENT
    // ═══════════════════════════════════════════

    function grantConsent() external {
        hasConsent[msg.sender] = true;
        consentGrantedAt[msg.sender] = block.timestamp;
        emit ConsentGranted(msg.sender, block.timestamp);
    }

    function revokeConsent() external {
        hasConsent[msg.sender] = false;
        consentRevokedAt[msg.sender] = block.timestamp;
        emit ConsentRevoked(msg.sender, block.timestamp);
    }

    // ═══════════════════════════════════════════
    // ACTION RECORDING
    // ═══════════════════════════════════════════

    /**
     * @notice Record a single significant action (app launch, URL visit, etc)
     */
    function recordAction(
        uint8 channelId,
        uint16 actionType,
        uint16 epochMs,
        bytes calldata data
    ) external onlyConsented returns (uint256 actionId) {
        actionId = actionCount++;
        bytes32 dataHash = keccak256(data);

        actions[actionId] = Action({
            user: msg.sender,
            channelId: channelId,
            actionType: actionType,
            timestamp: uint32(block.timestamp),
            epochMs: epochMs,
            dataHash: dataHash,
            data: data
        });

        userActionIds[msg.sender].push(actionId);
        channelActionCounts[msg.sender][channelId]++;

        emit ActionRecorded(actionId, msg.sender, channelId, actionType,
                           uint32(block.timestamp), dataHash);
    }

    /**
     * @notice Record a batch of high-frequency actions (1-second aggregate)
     * @param data ABI-encoded array of micro-actions within the 1-second window
     */
    function recordBatch(
        uint8 channelId,
        uint16 actionType,
        uint16 epochMs,
        bytes calldata data,
        uint8 microActionCount
    ) external onlyConsented returns (uint256 startActionId) {
        startActionId = actionCount;
        bytes32 dataHash = keccak256(data);

        actions[actionCount] = Action({
            user: msg.sender,
            channelId: channelId,
            actionType: actionType,
            timestamp: uint32(block.timestamp),
            epochMs: epochMs,
            dataHash: dataHash,
            data: data
        });

        userActionIds[msg.sender].push(actionCount);
        channelActionCounts[msg.sender][channelId] += microActionCount;
        actionCount++;

        emit BatchRecorded(startActionId, msg.sender, channelId, actionType,
                          uint32(block.timestamp), microActionCount);
    }

    /**
     * @notice Mint a compound token that wraps the last N actions
     *         into a single correlated "asset"
     * @param startActionId First action in the compound window
     * @param endActionId Last action in the compound window
     * @param channelIds Which channels are represented
     * @param aggregateData Aggregate statistics (encoded off-chain)
     */
    function mintCompound(
        uint256 startActionId,
        uint256 endActionId,
        uint8[] calldata channelIds,
        bytes calldata aggregateData
    ) external onlyConsented returns (uint256 compoundId) {
        require(endActionId >= startActionId, "Invalid range");
        require(endActionId < actionCount, "Action not yet recorded");

        compoundId = compoundCount++;
        uint8 count = uint8(endActionId - startActionId + 1);
        bytes32 correlationHash = keccak256(abi.encodePacked(
            msg.sender, startActionId, endActionId, aggregateData
        ));

        compoundTokens[compoundId] = CompoundToken({
            user: msg.sender,
            startActionId: startActionId,
            endActionId: endActionId,
            startTime: actions[startActionId].timestamp,
            endTime: actions[endActionId].timestamp,
            actionCount: count,
            channelIds: channelIds,
            correlationHash: correlationHash,
            aggregateData: aggregateData
        });

        userCompoundIds[msg.sender].push(compoundId);

        emit CompoundMinted(compoundId, msg.sender, startActionId,
                           endActionId, count, correlationHash);
    }

    // ═══════════════════════════════════════════
    // QUERY FUNCTIONS
    // ═══════════════════════════════════════════

    function getAction(uint256 actionId) external view returns (
        address user, uint8 channelId, uint16 actionType,
        uint32 timestamp, uint16 epochMs, bytes32 dataHash, bytes memory data
    ) {
        Action storage a = actions[actionId];
        return (a.user, a.channelId, a.actionType,
                a.timestamp, a.epochMs, a.dataHash, a.data);
    }

    function getCompound(uint256 compoundId) external view returns (
        address user, uint256 startActionId, uint256 endActionId,
        uint32 startTime, uint32 endTime, uint8 actionCount,
        bytes32 correlationHash
    ) {
        CompoundToken storage c = compoundTokens[compoundId];
        return (c.user, c.startActionId, c.endActionId,
                c.startTime, c.endTime, c.actionCount, c.correlationHash);
    }

    function getUserActionCount(address user) external view returns (uint256) {
        return userActionIds[user].length;
    }

    function getUserCompoundCount(address user) external view returns (uint256) {
        return userCompoundIds[user].length;
    }

    function getChannelStats(address user, uint8 channelId) external view returns (uint256) {
        return channelActionCounts[user][channelId];
    }

    function getUserActionIds(address user, uint256 offset, uint256 limit)
        external view returns (uint256[] memory)
    {
        uint256[] storage ids = userActionIds[user];
        uint256 end = offset + limit;
        if (end > ids.length) end = ids.length;
        uint256[] memory result = new uint256[](end - offset);
        for (uint256 i = offset; i < end; i++) {
            result[i - offset] = ids[i];
        }
        return result;
    }

    // ═══════════════════════════════════════════
    // DEVELOPER DEBUG MODE
    // These functions exist for testing ONLY.
    // They are permanently disabled by disableDebugMode().
    // ═══════════════════════════════════════════

    /**
     * @notice Read raw action data for ANY user (debug only)
     * @dev ONLY works when debugMode is true
     *      This is how you test/verify the pipeline during development
     */
    function debugReadAction(uint256 actionId) external view debugOnly returns (
        address user, uint8 channelId, uint16 actionType,
        uint32 timestamp, bytes memory data
    ) {
        Action storage a = actions[actionId];
        return (a.user, a.channelId, a.actionType, a.timestamp, a.data);
    }

    /**
     * @notice Read all actions for a user in a time range (debug only)
     */
    function debugReadUserActions(address user, uint32 startTime, uint32 endTime)
        external view debugOnly returns (uint256[] memory matchingIds)
    {
        uint256[] storage ids = userActionIds[user];
        // Count matches first
        uint256 matchCount = 0;
        for (uint256 i = 0; i < ids.length; i++) {
            uint32 t = actions[ids[i]].timestamp;
            if (t >= startTime && t <= endTime) matchCount++;
        }
        matchingIds = new uint256[](matchCount);
        uint256 j = 0;
        for (uint256 i = 0; i < ids.length; i++) {
            uint32 t = actions[ids[i]].timestamp;
            if (t >= startTime && t <= endTime) {
                matchingIds[j++] = ids[i];
            }
        }
    }

    // ═══════════════════════════════════════════
    // SELF-READ FUNCTIONS
    // These are NOT debug-only. Users can ALWAYS read their own data.
    // This is the architectural separation:
    //   debugRead* = developer reads anyone's data → disabled before launch
    //   selfRead* = user reads own data → always available
    //
    // Privacy protects users from THE NETWORK, not from THEMSELVES.
    // ═══════════════════════════════════════════

    /**
     * @notice Read your own action data. Always available.
     * @dev msg.sender must match the action's user field.
     *      This function works even when debugMode is false.
     */
    function selfReadAction(uint256 actionId) external view returns (
        uint8 channelId, uint16 actionType,
        uint32 timestamp, uint16 epochMs, bytes memory data
    ) {
        Action storage a = actions[actionId];
        require(a.user == msg.sender, "Not your action");
        return (a.channelId, a.actionType, a.timestamp, a.epochMs, a.data);
    }

    /**
     * @notice Read your own actions in a time range. Always available.
     */
    function selfReadActions(uint32 startTime, uint32 endTime)
        external view returns (uint256[] memory matchingIds)
    {
        uint256[] storage ids = userActionIds[msg.sender];
        uint256 matchCount = 0;
        for (uint256 i = 0; i < ids.length; i++) {
            uint32 t = actions[ids[i]].timestamp;
            if (t >= startTime && t <= endTime) matchCount++;
        }
        matchingIds = new uint256[](matchCount);
        uint256 j = 0;
        for (uint256 i = 0; i < ids.length; i++) {
            uint32 t = actions[ids[i]].timestamp;
            if (t >= startTime && t <= endTime) {
                matchingIds[j++] = ids[i];
            }
        }
    }

    /**
     * @notice Get your own action count. Always available.
     */
    function selfGetActionCount() external view returns (uint256) {
        return userActionIds[msg.sender].length;
    }

    /**
     * @notice Get your own channel stats. Always available.
     */
    function selfGetChannelStats(uint8 channelId) external view returns (uint256) {
        return channelActionCounts[msg.sender][channelId];
    }

    // ═══════════════════════════════════════════
    // ADMIN / LOCKOUT
    // ═══════════════════════════════════════════

    /**
     * @notice Permanently disable debug mode. CANNOT BE UNDONE.
     *         Call this before public launch.
     */
    function disableDebugMode() external onlyAdmin {
        debugMode = false;
        emit DebugModeDisabled(block.timestamp);
    }

    /**
     * @notice Permanently lock the admin. No more admin functions ever.
     *         Call this after disableDebugMode() for complete lockout.
     *         CANNOT BE UNDONE.
     */
    function lockAdmin() external onlyAdmin {
        require(!debugMode, "Disable debug mode first");
        adminLocked = true;
        admin = address(0);
        emit AdminLocked(block.timestamp);
    }
}
