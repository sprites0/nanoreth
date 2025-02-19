# nanoreth

Hyperliquid EVM archival node attempt.
This does not support precompiles.
Based on [foundry](https://github.com/foundry-rs/foundry).

## How to use

```
aws configure
aws s3 ls s3://hl-mainnet-evm-blocks/ evm-blocks --request-payer requester
python3 server.py --data-dir evm-blocks --start-height 1 --end-height 40000
```
