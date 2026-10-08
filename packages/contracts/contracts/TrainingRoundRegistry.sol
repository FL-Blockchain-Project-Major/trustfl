// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/AccessControl.sol";

contract TrainingRoundRegistry is AccessControl {
    bytes32 public constant COORDINATOR_ROLE = keccak256("COORDINATOR_ROLE");

    enum RoundStatus { None, Created, Active, Finalized }

    struct TrainingRound {
        string globalModelVersion;
        RoundStatus status;
    }

    mapping(uint256 => TrainingRound) private _rounds;

    event RoundCreated(uint256 indexed roundId, string globalModelVersion);
    event RoundActivated(uint256 indexed roundId);
    event RoundFinalized(uint256 indexed roundId, string newGlobalModelVersion);

    constructor() {
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
    }

    function createRound(uint256 roundId, string memory globalModelVersion) external onlyRole(COORDINATOR_ROLE) {
        require(_rounds[roundId].status == RoundStatus.None, "RoundRegistry: round already exists");

        _rounds[roundId] = TrainingRound({
            globalModelVersion: globalModelVersion,
            status: RoundStatus.Created
        });

        emit RoundCreated(roundId, globalModelVersion);
    }

    function activateRound(uint256 roundId) external onlyRole(COORDINATOR_ROLE) {
        require(_rounds[roundId].status == RoundStatus.Created, "RoundRegistry: invalid status for activation");
        _rounds[roundId].status = RoundStatus.Active;
        emit RoundActivated(roundId);
    }

    function finalizeRound(uint256 roundId, string memory newGlobalModelVersion) external onlyRole(COORDINATOR_ROLE) {
        require(_rounds[roundId].status == RoundStatus.Active, "RoundRegistry: invalid status for finalization");
        _rounds[roundId].status = RoundStatus.Finalized;
        _rounds[roundId].globalModelVersion = newGlobalModelVersion;
        emit RoundFinalized(roundId, newGlobalModelVersion);
    }

    function getRound(uint256 roundId) external view returns (TrainingRound memory) {
        return _rounds[roundId];
    }

    function isRoundActive(uint256 roundId) external view returns (bool) {
        return _rounds[roundId].status == RoundStatus.Active;
    }
}
