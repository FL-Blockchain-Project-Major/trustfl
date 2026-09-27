// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/AccessControl.sol";

interface IClientRegistry {
    function isClientActive(string memory clientId) external view returns (bool);
}

interface ITrainingRoundRegistry {
    function isRoundActive(uint256 roundId) external view returns (bool);
}

contract UpdateRegistry is AccessControl {
    bytes32 public constant COORDINATOR_ROLE = keccak256("COORDINATOR_ROLE");

    enum UpdateStatus { None, Submitted, Verified, Aggregated, Rejected }

    struct Update {
        uint256 roundId;
        string clientId;
        string artifactHash;
        string nonce;
        UpdateStatus status;
    }

    IClientRegistry public clientRegistry;
    ITrainingRoundRegistry public roundRegistry;

    mapping(string => Update) private _updates;
    mapping(string => bool) private _usedNonces;

    event UpdateSubmitted(string indexed updateId, uint256 indexed roundId, string indexed clientId);
    event UpdateStatusChanged(string indexed updateId, UpdateStatus status);

    constructor(address clientRegistryAddr, address roundRegistryAddr) {
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        clientRegistry = IClientRegistry(clientRegistryAddr);
        roundRegistry = ITrainingRoundRegistry(roundRegistryAddr);
    }

    function submitUpdate(
        string memory updateId,
        uint256 roundId,
        string memory clientId,
        string memory artifactHash,
        string memory nonce
    ) external onlyRole(COORDINATOR_ROLE) {
        require(_updates[updateId].status == UpdateStatus.None, "UpdateRegistry: duplicate update ID");
        require(!_usedNonces[nonce], "UpdateRegistry: replay detected, nonce reused");
        require(roundRegistry.isRoundActive(roundId), "UpdateRegistry: stale or invalid round");
        require(clientRegistry.isClientActive(clientId), "UpdateRegistry: client not active");

        _usedNonces[nonce] = true;

        _updates[updateId] = Update({
            roundId: roundId,
            clientId: clientId,
            artifactHash: artifactHash,
            nonce: nonce,
            status: UpdateStatus.Submitted
        });

        emit UpdateSubmitted(updateId, roundId, clientId);
    }

    function markVerificationState(string memory updateId, bool isValid) external onlyRole(COORDINATOR_ROLE) {
        require(_updates[updateId].status == UpdateStatus.Submitted, "UpdateRegistry: must be submitted");
        
        UpdateStatus newStatus = isValid ? UpdateStatus.Verified : UpdateStatus.Rejected;
        _updates[updateId].status = newStatus;
        
        emit UpdateStatusChanged(updateId, newStatus);
    }

    function recordAggregation(string memory updateId) external onlyRole(COORDINATOR_ROLE) {
        require(_updates[updateId].status == UpdateStatus.Verified, "UpdateRegistry: must be verified");
        
        _updates[updateId].status = UpdateStatus.Aggregated;
        
        emit UpdateStatusChanged(updateId, UpdateStatus.Aggregated);
    }

    function getUpdate(string memory updateId) external view returns (Update memory) {
        return _updates[updateId];
    }
}
