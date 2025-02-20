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

## Demo

(todo; I'll leave a trace example here)

```
# cast run 0x502c743fcb4bb99415d84febe28f233104c4ffb42986dd62dd532f2af3059466
Executing previous transactions from the block.
Traces:
  [122726] 0xb4a9C4e6Ea8E2191d2FA5B380452a634Fb21240A::swapExactETHForTokensSupportingFeeOnTransferTokens{value: 500000000000000000}(250824933578367544013693 [2.508e23], [0x5555555555555555555555555555555555555555, 0xdB1E98D81261754f50026D44D22EFcE70293FC62], 0x199f55ebb1ecCFf9D5D3346334AB199dB729551c, 0x67a3B51964Bb55695E4C5F3F195E1aE180C9c2E5, 1739917547 [1.739e9])
    ├─ [23802] 0x5555555555555555555555555555555555555555::deposit{value: 500000000000000000}()
    │   ├─ emit Deposit(param0: 0xb4a9C4e6Ea8E2191d2FA5B380452a634Fb21240A, param1: 500000000000000000 [5e17])
    │   └─ ← [Stop]
    ├─ [7801] 0x5555555555555555555555555555555555555555::transfer(0xe25DfDfE4EB7b07a1ca0550b5067525c9e096DC2, 500000000000000000 [5e17])
    │   ├─ emit Transfer(param0: 0xb4a9C4e6Ea8E2191d2FA5B380452a634Fb21240A, param1: 0xe25DfDfE4EB7b07a1ca0550b5067525c9e096DC2, param2: 500000000000000000 [5e17])
    │   └─ ← [Return] 0x0000000000000000000000000000000000000000000000000000000000000001
    ├─ [2603] 0xdB1E98D81261754f50026D44D22EFcE70293FC62::balanceOf(0x199f55ebb1ecCFf9D5D3346334AB199dB729551c) [staticcall]
    │   └─ ← [Return] 0x0000000000000000000000000000000000000000000000000000000000000000
...
    │   ├─ emit Sync(: 250758073900138607628 [2.507e20], : 126045608281275656936303506 [1.26e26])
    │   ├─ emit Swap(param0: 0xb4a9C4e6Ea8E2191d2FA5B380452a634Fb21240A, param1: 500000000000000000 [5e17], param2: 0, param3: 0, param4: 251075758511945911557707 [2.51e23], param5: 0x199f55ebb1ecCFf9D5D3346334AB199dB729551c)
    │   └─ ← [Stop]
    ├─ [603] 0xdB1E98D81261754f50026D44D22EFcE70293FC62::balanceOf(0x199f55ebb1ecCFf9D5D3346334AB199dB729551c) [staticcall]
    │   └─ ← [Return] 0x00000000000000000000000000000000000000000000352ad819ae3be71ede4b
    └─ ← [Stop]


Transaction successfully executed.
Gas used: 123266
```

## How it works

`server.py` invokes a modified anvil node, and ingests [raw evm blocks](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/evm/raw-hyperevm-block-data) to send it to the node. New block is mined upon request.

Also it lists system transactions (deposit txs via `0x222..22`) as pseudo-transaction; while it makes better visibility for explorers (like Otterscan below), make sure to exclude it from indexing (you can filter out by checking if the sender is `0x222..22`).

## Running otterscan

Anvil supports APIs required by [Otterscan](https://github.com/otterscan/otterscan).

```sh
docker run --rm -p 5100:80 --name otterscan -d otterscan/otterscan:latest
```
