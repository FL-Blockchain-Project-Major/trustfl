import toolbox from "@nomicfoundation/hardhat-toolbox-mocha-ethers";
import { definePlugin } from "hardhat/plugins";

const sortArtifactsPlugin = definePlugin({
  id: "sort-artifacts",
  hookHandlers: {
    solidity: async () => ({
      default: async () => ({
        async processArtifactsAfterSuccessfulBuild(_context, artifactPaths) {
          if (Array.isArray(artifactPaths)) {
            artifactPaths.sort();
          }
        },
      }),
    }),
  },
});

export default {
  solidity: "0.8.20",
  networks: {
    localhost: {
      type: "http",
      url: process.env.HARDHAT_RPC_URL ?? "http://127.0.0.1:8545",
    },
  },
  plugins: [sortArtifactsPlugin, toolbox],
  paths: {
    artifacts: "./artifacts",
    cache: "./cache",
    sources: "./contracts",
    tests: "./test",
  },
};

