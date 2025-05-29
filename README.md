# nanoreth

Hyperliquid archive node based on [reth](https://github.com/paradigmxyz/reth).

## ⚠️ IMPORTANT: System Transactions Appear as Pseudo Transactions

Deposit transactions from `0x222..22` to user addresses are intentionally recorded as pseudo transactions.
This change simplifies block explorers, making it easier to track deposit timestamps.
Ensure careful handling when indexing.

## Prerequisites

Building NanoReth from source requires Rust and Cargo to be installed:

`$ curl https://sh.rustup.rs -sSf | sh`

## How to run (mainnet)

1) `$ aws s3 sync s3://hl-mainnet-evm-blocks/ ~/evm-blocks --request-payer requester # one-time` - this will backfill the existing blocks from HyperLiquid's EVM S3 bucket.

2) `$ make install` - this will install the NanoReth binary.

3) Start NanoReth which will begin syncing using the blocks in `~/evm-blocks`:

    ```sh
    $ reth node --http --http.addr 0.0.0.0 --http.api eth,ots,net,web3 --ws --ws.addr 0.0.0.0 --ws.origins '*' --ws.api eth,ots,net,web3 --ingest-dir ~/evm-blocks --ws.port 8545
    ```

4) Once the node logs stops making progress this means it's caught up with the existing blocks.

    Stop the NanoReth process and then start Goofys: `$ goofys --region=ap-northeast-1 --requester-pays hl-mainnet-evm-blocks evm-blocks`

    Goofys will mount the AWS S3 bucket into `~/evm-blocks` and save new blocks as they are added to the bucket.

    You can now restart NanoReth using the same command as above:

    ```sh
    $ reth node --http --http.addr 0.0.0.0 --http.api eth,ots,net,web3 --ws --ws.addr 0.0.0.0 --ws.origins '*' --ws.api eth,ots,net,web3 --ingest-dir ~/evm-blocks --ws.port 8545
    ```

## How to run (testnet)

Testnet is supported since block 21304281.

```sh
# Get testnet genesis at block 21304281
$ cd ~
$ git clone https://github.com/sprites0/hl-testnet-genesis
$ zstd --rm -d ~/hl-testnet-genesis/*.zst

# Init node
$ make install
$ reth init-state --without-evm --chain testnet --header ~/hl-testnet-genesis/21304281.rlp \
  --header-hash 0x5b10856d2b1ad241c9bd6136bcc60ef7e8553560ca53995a590db65f809269b4 \
  ~/hl-testnet-genesis/21304281.jsonl --total-difficulty 0 

# Run node
$ reth node --chain testnet --http --http.addr 0.0.0.0 --http.api eth,ots,net,web3 \
    --ws --ws.addr 0.0.0.0 --ws.origins '*' --ws.api eth,ots,net,web3 --ingest-dir ~/evm-blocks --ws.port 8546
```
