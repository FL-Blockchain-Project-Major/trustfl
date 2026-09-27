// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/AccessControl.sol";

contract ClientRegistry is AccessControl {
    bytes32 public constant COORDINATOR_ROLE = keccak256("COORDINATOR_ROLE");

    struct Client {
        string pubkey;
        bool isRegistered;
        bool isActive;
    }

    mapping(string => Client) private _clients;

    event ClientRegistered(string indexed clientId, string pubkey);
    event ClientStatusChanged(string indexed clientId, bool isActive);

    constructor() {
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
    }

    function registerClient(string memory clientId, string memory pubkey) external onlyRole(COORDINATOR_ROLE) {
        require(!_clients[clientId].isRegistered, "ClientRegistry: client already registered");
        
        _clients[clientId] = Client({
            pubkey: pubkey,
            isRegistered: true,
            isActive: true
        });

        emit ClientRegistered(clientId, pubkey);
    }

    function setClientStatus(string memory clientId, bool isActive) external onlyRole(COORDINATOR_ROLE) {
        require(_clients[clientId].isRegistered, "ClientRegistry: client not found");
        _clients[clientId].isActive = isActive;
        emit ClientStatusChanged(clientId, isActive);
    }

    function getClient(string memory clientId) external view returns (Client memory) {
        return _clients[clientId];
    }

    function isClientActive(string memory clientId) external view returns (bool) {
        return _clients[clientId].isRegistered && _clients[clientId].isActive;
    }
}
