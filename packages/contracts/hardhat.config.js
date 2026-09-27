import toolbox from "@nomicfoundation/hardhat-toolbox-mocha-ethers";

export default {
  solidity: "0.8.20",
  plugins: [toolbox],
  paths: {
    artifacts: "./artifacts",
    cache: "./cache",
    sources: "./contracts",
    tests: "./test",
  },
};
