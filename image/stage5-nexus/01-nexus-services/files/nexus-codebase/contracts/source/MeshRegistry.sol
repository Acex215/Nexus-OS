// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract MeshRegistry {
    struct MeshPeer {
        address wallet;
        string enodeUrl;
        string wgPublicKey;
        string meshIP;
        bool active;
        uint256 timestamp;
    }

    mapping(address => MeshPeer) public peers;
    address[] public peerList;

    event PeerRegistered(address wallet, string meshIP, uint256 timestamp);

    function registerPeer(string calldata enodeUrl, string calldata wgPubKey, string calldata meshIP) external {
        if (!peers[msg.sender].active) {
            peerList.push(msg.sender);
        }
        peers[msg.sender] = MeshPeer(msg.sender, enodeUrl, wgPubKey, meshIP, true, block.timestamp);
        emit PeerRegistered(msg.sender, meshIP, block.timestamp);
    }

    function getPeerCount() external view returns (uint256) {
        return peerList.length;
    }

    function getPeer(address wallet) external view returns (string memory enodeUrl, string memory wgPubKey, string memory meshIP, bool active) {
        MeshPeer memory peer = peers[wallet];
        return (peer.enodeUrl, peer.wgPublicKey, peer.meshIP, peer.active);
    }

    function getPeerAddress(uint256 index) external view returns (address) {
        require(index < peerList.length, "Index out of bounds");
        return peerList[index];
    }
}
