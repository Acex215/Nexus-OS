// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract AccessLogger {
    struct AccessLog {
        address accessor;
        address patient;
        string dataCategory;
        string purpose;
        uint256 timestamp;
    }

    AccessLog[] public logs;

    // patient => indices into the logs array
    mapping(address => uint256[]) private patientLogIndices;

    event AccessLogged(address indexed accessor, address indexed patient, string dataCategory, string purpose, uint256 timestamp);

    /// @notice Log an access to health-related data. Cannot be deleted or modified.
    function logAccess(address patient, string calldata dataCategory, string calldata purpose) external {
        uint256 index = logs.length;
        logs.push(AccessLog({
            accessor: msg.sender,
            patient: patient,
            dataCategory: dataCategory,
            purpose: purpose,
            timestamp: block.timestamp
        }));
        patientLogIndices[patient].push(index);
        emit AccessLogged(msg.sender, patient, dataCategory, purpose, block.timestamp);
    }

    /// @notice Get all access records for a patient
    function getAccessLogs(address patient) external view returns (AccessLog[] memory) {
        uint256[] storage indices = patientLogIndices[patient];
        AccessLog[] memory result = new AccessLog[](indices.length);
        for (uint256 i = 0; i < indices.length; i++) {
            result[i] = logs[indices[i]];
        }
        return result;
    }

    /// @notice Get total number of accesses for a patient
    function getAccessCount(address patient) external view returns (uint256) {
        return patientLogIndices[patient].length;
    }
}
