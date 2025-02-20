# nanoreth

Hyperliquid EVM archival node attempt.
This does not support precompiles.
Based on [foundry](https://github.com/foundry-rs/foundry).

## How to use

```
aws configure
aws s3 ls s3://hl-mainnet-evm-blocks/ evm-blocks --request-payer requester

# Both data-dir can be the same, it's there for convenience.
# data-dir  = local copy of s3
# data-dir2 = s3fs, etc
python3 server.py --data-dir evm-blocks --data-dir2 evm-blocks2 --overwrite
```
