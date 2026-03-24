// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract ConsentManager {
    struct Consent {
        address patient;
        string dataCategory;
        bool active;
        uint256 grantedAt;
        uint256 revokedAt;
    }

    mapping(address => Consent[]) public patientConsents;

    event ConsentGranted(address indexed patient, string dataCategory, uint256 consentIndex, uint256 timestamp);
    event ConsentRevoked(address indexed patient, uint256 consentIndex, uint256 timestamp);

    /// @notice Patient grants consent for a specific data category
    function grantConsent(string calldata dataCategory) external {
        uint256 index = patientConsents[msg.sender].length;
        patientConsents[msg.sender].push(Consent({
            patient: msg.sender,
            dataCategory: dataCategory,
            active: true,
            grantedAt: block.timestamp,
            revokedAt: 0
        }));
        emit ConsentGranted(msg.sender, dataCategory, index, block.timestamp);
    }

    /// @notice Patient revokes a previously granted consent
    /// Historical contributions are NOT retroactively removed (federated
    /// gradients are irreversible), but no new data flows after revocation.
    function revokeConsent(uint256 consentIndex) external {
        require(consentIndex < patientConsents[msg.sender].length, "Invalid consent index");
        Consent storage c = patientConsents[msg.sender][consentIndex];
        require(c.active, "Consent already revoked");
        c.active = false;
        c.revokedAt = block.timestamp;
        emit ConsentRevoked(msg.sender, consentIndex, block.timestamp);
    }

    /// @notice Check if a patient has active consent for a data category
    function hasActiveConsent(address patient, string calldata dataCategory) external view returns (bool) {
        Consent[] storage consents = patientConsents[patient];
        for (uint256 i = 0; i < consents.length; i++) {
            if (consents[i].active && keccak256(bytes(consents[i].dataCategory)) == keccak256(bytes(dataCategory))) {
                return true;
            }
        }
        return false;
    }

    /// @notice Get all consent records for a patient
    function getPatientConsents(address patient) external view returns (Consent[] memory) {
        return patientConsents[patient];
    }
}
