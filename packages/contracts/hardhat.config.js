import toolbox from "@nomicfoundation/hardhat-toolbox-mocha-ethers";

export default {
  solidity: "0.8.20",
  networks: {
    localhost: {
      type: "http",
      url: process.env.HARDHAT_RPC_URL ?? "http://127.0.0.1:8545",
    },
  },
  plugins: [toolbox],
  paths: {
    artifacts: "./artifacts",
    cache: "./cache",
    sources: "./contracts",
    tests: "./test",
  },
};
