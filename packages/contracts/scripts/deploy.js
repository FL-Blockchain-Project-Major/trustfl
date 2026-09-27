import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import hre from "hardhat";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function main() {
  const { ethers } = await hre.network.create();
  const [deployer] = await ethers.getSigners();
  console.log("Deploying contracts with account:", deployer.address);

  // 1. ClientRegistry
  const ClientRegistry = await ethers.getContractFactory("ClientRegistry");
  const clientRegistry = await ClientRegistry.deploy();
  await clientRegistry.waitForDeployment();
  const clientRegistryAddr = await clientRegistry.getAddress();
  console.log("ClientRegistry deployed to:", clientRegistryAddr);

  // 2. TrainingRoundRegistry
  const TrainingRoundRegistry = await ethers.getContractFactory("TrainingRoundRegistry");
  const roundRegistry = await TrainingRoundRegistry.deploy();
  await roundRegistry.waitForDeployment();
  const roundRegistryAddr = await roundRegistry.getAddress();
  console.log("TrainingRoundRegistry deployed to:", roundRegistryAddr);

  // 3. UpdateRegistry
  const UpdateRegistry = await ethers.getContractFactory("UpdateRegistry");
  const updateRegistry = await UpdateRegistry.deploy(clientRegistryAddr, roundRegistryAddr);
  await updateRegistry.waitForDeployment();
  const updateRegistryAddr = await updateRegistry.getAddress();
  console.log("UpdateRegistry deployed to:", updateRegistryAddr);

  // --- Generate deployment artifacts ---
  const network = await ethers.provider.getNetwork();
  const networkName = network.name === "unknown" ? "localhost" : network.name;

  const deployDir = path.join(__dirname, "..", "deployments", networkName);
  fs.mkdirSync(deployDir, { recursive: true });

  // Extract ABI using hardhat artifacts
  const clientRegistryArtifact = await hre.artifacts.readArtifact("ClientRegistry");
  const roundRegistryArtifact = await hre.artifacts.readArtifact("TrainingRoundRegistry");
  const updateRegistryArtifact = await hre.artifacts.readArtifact("UpdateRegistry");

  const deployment = {
    network: networkName,
    deployedAt: new Date().toISOString(),
    contracts: {
      ClientRegistry:         { address: clientRegistryAddr,   abi: clientRegistryArtifact.abi },
      TrainingRoundRegistry:  { address: roundRegistryAddr,    abi: roundRegistryArtifact.abi },
      UpdateRegistry:         { address: updateRegistryAddr,   abi: updateRegistryArtifact.abi },
    },
  };

  const outPath = path.join(deployDir, "contracts.json");
  fs.writeFileSync(outPath, JSON.stringify(deployment, null, 2));
  console.log(`\nDeployment artifacts saved to: deployments/${networkName}/contracts.json`);

  return deployment;
}

main()
  .then(() => process.exit(0))
  .catch((err) => { console.error(err); process.exit(1); });
