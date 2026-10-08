import { expect } from "chai";
import hre from "hardhat";

// keccak256("COORDINATOR_ROLE")
const COORDINATOR_ROLE = "0x2e8b98eef02e8df3bd27d1270ded3bea3d14db99c5234c7b14001a7fff957bcc";

describe("TrustFL Blockchain Subsystem", function () {
  let clientRegistry;
  let roundRegistry;
  let updateRegistry;
  let ethers;
  let owner, coordinator, otherAccount;

  before(async function () {
    ({ ethers } = await hre.network.create());
  });

  beforeEach(async function () {
    [owner, coordinator, otherAccount] = await ethers.getSigners();

    const ClientRegistry = await ethers.getContractFactory("ClientRegistry");
    clientRegistry = await ClientRegistry.deploy();
    await clientRegistry.grantRole(COORDINATOR_ROLE, coordinator.address);

    const TrainingRoundRegistry = await ethers.getContractFactory("TrainingRoundRegistry");
    roundRegistry = await TrainingRoundRegistry.deploy();
    await roundRegistry.grantRole(COORDINATOR_ROLE, coordinator.address);

    const UpdateRegistry = await ethers.getContractFactory("UpdateRegistry");
    updateRegistry = await UpdateRegistry.deploy(
      await clientRegistry.getAddress(),
      await roundRegistry.getAddress()
    );
    await updateRegistry.grantRole(COORDINATOR_ROLE, coordinator.address);
  });

  // ----------------------------------------------------------------
  // ClientRegistry
  // ----------------------------------------------------------------
  describe("ClientRegistry", function () {
    it("Happy path: should register a client", async function () {
      await expect(clientRegistry.connect(coordinator).registerClient("client1", "pubkey_base64"))
        .to.emit(clientRegistry, "ClientRegistered")
        .withArgs("client1", "pubkey_base64");

      const client = await clientRegistry.getClient("client1");
      expect(client.isActive).to.be.true;
      expect(client.isActive).to.be.true;
    });

    it("Unauthorized caller should fail", async function () {
      await expect(
        clientRegistry.connect(otherAccount).registerClient("client1", "pubkey_base64")
      ).to.be.revertedWithCustomError(clientRegistry, "AccessControlUnauthorizedAccount");
    });

    it("Duplicate registration should fail", async function () {
      await clientRegistry.connect(coordinator).registerClient("client1", "pubkey_base64");
      await expect(
        clientRegistry.connect(coordinator).registerClient("client1", "new_pubkey")
      ).to.be.revertedWith("ClientRegistry: client already registered");
    });

    it("isClientActive returns false for unknown client", async function () {
      expect(await clientRegistry.isClientActive("nobody")).to.be.false;
    });

    it("setClientStatus deactivates a registered client", async function () {
      await clientRegistry.connect(coordinator).registerClient("c1", "pk");
      await expect(clientRegistry.connect(coordinator).setClientStatus("c1", false))
        .to.emit(clientRegistry, "ClientStatusChanged")
        .withArgs("c1", false);
      expect(await clientRegistry.isClientActive("c1")).to.be.false;
    });

    it("setClientStatus unauthorized should fail", async function () {
      await clientRegistry.connect(coordinator).registerClient("c1", "pk");
      await expect(
        clientRegistry.connect(otherAccount).setClientStatus("c1", false)
      ).to.be.revertedWithCustomError(clientRegistry, "AccessControlUnauthorizedAccount");
    });

    it("setClientStatus on unknown client should fail", async function () {
      await expect(
        clientRegistry.connect(coordinator).setClientStatus("nobody", false)
      ).to.be.revertedWith("ClientRegistry: client not found");
    });
  });

  // ----------------------------------------------------------------
  // TrainingRoundRegistry
  // ----------------------------------------------------------------
  describe("TrainingRoundRegistry", function () {
    it("Happy path: create, activate, and finalize round", async function () {
      await expect(roundRegistry.connect(coordinator).createRound(1, "model_v1"))
        .to.emit(roundRegistry, "RoundCreated")
        .withArgs(1, "model_v1");

      await expect(roundRegistry.connect(coordinator).activateRound(1))
        .to.emit(roundRegistry, "RoundActivated")
        .withArgs(1);

      expect(await roundRegistry.isRoundActive(1)).to.be.true;

      await expect(roundRegistry.connect(coordinator).finalizeRound(1, "model_v2"))
        .to.emit(roundRegistry, "RoundFinalized")
        .withArgs(1, "model_v2");

      expect(await roundRegistry.isRoundActive(1)).to.be.false;
    });

    it("Unauthorized caller cannot create round", async function () {
      await expect(
        roundRegistry.connect(otherAccount).createRound(1, "model_v1")
      ).to.be.revertedWithCustomError(roundRegistry, "AccessControlUnauthorizedAccount");
    });

    it("Duplicate round creation should fail", async function () {
      await roundRegistry.connect(coordinator).createRound(1, "model_v1");
      await expect(
        roundRegistry.connect(coordinator).createRound(1, "model_v1")
      ).to.be.revertedWith("RoundRegistry: round already exists");
    });

    it("Invalid state transition: finalize before activate", async function () {
      await roundRegistry.connect(coordinator).createRound(1, "model_v1");
      await expect(
        roundRegistry.connect(coordinator).finalizeRound(1, "model_v2")
      ).to.be.revertedWith("RoundRegistry: invalid status for finalization");
    });

    it("Invalid state transition: activate a non-created round", async function () {
      await expect(
        roundRegistry.connect(coordinator).activateRound(99)
      ).to.be.revertedWith("RoundRegistry: invalid status for activation");
    });

    it("Finalization rules: cannot finalize twice", async function () {
      await roundRegistry.connect(coordinator).createRound(1, "model_v1");
      await roundRegistry.connect(coordinator).activateRound(1);
      await roundRegistry.connect(coordinator).finalizeRound(1, "model_v2");
      await expect(
        roundRegistry.connect(coordinator).finalizeRound(1, "model_v3")
      ).to.be.revertedWith("RoundRegistry: invalid status for finalization");
    });
  });

  // ----------------------------------------------------------------
  // UpdateRegistry
  // ----------------------------------------------------------------
  describe("UpdateRegistry", function () {
    const roundId = 1;
    const clientId = "client1";
    const updateId = "update1";
    const artifactHash = "sha256:abc12345";
    const nonce = "client1:1:abcdef1234567890";

    beforeEach(async function () {
      await clientRegistry.connect(coordinator).registerClient(clientId, "pubkey");
      await roundRegistry.connect(coordinator).createRound(roundId, "model_v1");
      await roundRegistry.connect(coordinator).activateRound(roundId);
    });

    it("Happy path: submit, verify, aggregate", async function () {
      await expect(
        updateRegistry.connect(coordinator).submitUpdate(updateId, roundId, clientId, artifactHash, nonce)
      ).to.emit(updateRegistry, "UpdateSubmitted").withArgs(updateId, roundId, clientId);

      // 2 = Verified
      await expect(
        updateRegistry.connect(coordinator).markVerificationState(updateId, true)
      ).to.emit(updateRegistry, "UpdateStatusChanged").withArgs(updateId, 2);

      // 3 = Aggregated
      await expect(
        updateRegistry.connect(coordinator).recordAggregation(updateId)
      ).to.emit(updateRegistry, "UpdateStatusChanged").withArgs(updateId, 3);
    });

    it("Unauthorized caller cannot submit update", async function () {
      await expect(
        updateRegistry.connect(otherAccount).submitUpdate(updateId, roundId, clientId, artifactHash, nonce)
      ).to.be.revertedWithCustomError(updateRegistry, "AccessControlUnauthorizedAccount");
    });

    it("Duplicate update ID should fail", async function () {
      await updateRegistry.connect(coordinator).submitUpdate(updateId, roundId, clientId, artifactHash, nonce);
      await expect(
        updateRegistry.connect(coordinator).submitUpdate(updateId, roundId, clientId, artifactHash, "other_nonce")
      ).to.be.revertedWith("UpdateRegistry: duplicate update ID");
    });

    it("Replay: nonce reuse should fail", async function () {
      await updateRegistry.connect(coordinator).submitUpdate(updateId, roundId, clientId, artifactHash, nonce);
      await expect(
        updateRegistry.connect(coordinator).submitUpdate("update2", roundId, clientId, artifactHash, nonce)
      ).to.be.revertedWith("UpdateRegistry: replay detected, nonce reused");
    });

    it("Stale round: submit to finalized round should fail", async function () {
      await roundRegistry.connect(coordinator).finalizeRound(roundId, "model_v2");
      await expect(
        updateRegistry.connect(coordinator).submitUpdate(updateId, roundId, clientId, artifactHash, nonce)
      ).to.be.revertedWith("UpdateRegistry: stale or invalid round");
    });

    it("Inactive client should be rejected", async function () {
      await clientRegistry.connect(coordinator).setClientStatus(clientId, false);
      await expect(
        updateRegistry.connect(coordinator).submitUpdate(updateId, roundId, clientId, artifactHash, nonce)
      ).to.be.revertedWith("UpdateRegistry: client not active");
    });

    it("Invalid state transition: aggregate before verify", async function () {
      await updateRegistry.connect(coordinator).submitUpdate(updateId, roundId, clientId, artifactHash, nonce);
      await expect(
        updateRegistry.connect(coordinator).recordAggregation(updateId)
      ).to.be.revertedWith("UpdateRegistry: must be verified");
    });

    it("Invalid state transition: mark verification on non-submitted update", async function () {
      await expect(
        updateRegistry.connect(coordinator).markVerificationState("nonexistent", true)
      ).to.be.revertedWith("UpdateRegistry: must be submitted");
    });

    it("Rejected update cannot be aggregated", async function () {
      await updateRegistry.connect(coordinator).submitUpdate(updateId, roundId, clientId, artifactHash, nonce);
      // 4 = Rejected
      await expect(
        updateRegistry.connect(coordinator).markVerificationState(updateId, false)
      ).to.emit(updateRegistry, "UpdateStatusChanged").withArgs(updateId, 4);

      await expect(
        updateRegistry.connect(coordinator).recordAggregation(updateId)
      ).to.be.revertedWith("UpdateRegistry: must be verified");
    });
  });
});
