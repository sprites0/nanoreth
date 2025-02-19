# Modified from https://github.com/hyperliquid-dex/hyperliquid-python-sdk/commits/b569b18bdb923f6e84a61c164ccb29e51f3e181b/examples/evm_block_indexer.py

import tempfile
import time
from typing import Any

import argparse
import json
import os
import requests
import subprocess
from datetime import datetime

import eth_account
import eth_account.typed_transactions
from eth_typing import Address
import eth_utils
import lz4.frame
import msgpack
from web3 import HTTPProvider, Web3


def decompress_lz4(input_file, output_file):
    with open(input_file, "rb") as f_in:
        compressed_data = f_in.read()

    decompressed_data = lz4.frame.decompress(compressed_data)

    with open(output_file, "wb") as f_out:
        f_out.write(decompressed_data)


class BytesEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            return "0x" + obj.hex()
        return super().default(obj)


class EthBlockIndexer:
    # convert a Buffer object to hex string
    def _convert_buffer(self, buffer_obj: dict[str, Any]) -> str:
        if isinstance(buffer_obj, dict) and buffer_obj.get("type") == "Buffer":
            return "0x" + "".join(f"{x:02x}" for x in buffer_obj["data"])
        return str(buffer_obj)

    # recursively process nested Buffer objects
    def _process_nested_buffers(self, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("type") == "Buffer":
                return self._convert_buffer(data)
            return {k: self._process_nested_buffers(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._process_nested_buffers(item) for item in data]
        elif isinstance(data, bytes):
            return "0x" + data.hex()
        return data

    def _bytes_to_int(self, value: Any) -> int:
        if isinstance(value, dict) and value.get("type") == "Buffer":
            raw_bytes = bytes(value["data"])
            return int.from_bytes(raw_bytes, byteorder="big")
        elif isinstance(value, bytes):
            return int.from_bytes(value, byteorder="big")
        return 0

    def _process_transaction(self, tx: dict[str, Any]) -> dict[str, Any]:
        if not tx.get("transaction"):
            return {}

        tx_data = tx["transaction"]
        tx_type = next(iter(tx_data.keys()))  # Either 'Legacy' or 'Eip1559'
        tx_content = tx_data[tx_type]

        TX_TYPES = {"Legacy": 0, "Eip1559": 2}
        processed = {
            "chainId": self._bytes_to_int(
                tx_content.get("chainId", {"type": "Buffer", "data": []})
            ),
            "nonce": self._bytes_to_int(
                tx_content.get("nonce", {"type": "Buffer", "data": []})
            ),
            "gas": self._bytes_to_int(
                tx_content.get("gas", {"type": "Buffer", "data": []})
            ),
            "to": Address(tx_content["to"]),
            "value": self._bytes_to_int(
                tx_content.get("value", {"type": "Buffer", "data": []})
            ),
            "data": self._process_nested_buffers(tx_content.get("input")),
            "signature": [
                self._process_nested_buffers(sig) for sig in tx.get("signature", [])
            ],
        }

        if tx_type == "Legacy":
            processed["gasPrice"] = self._bytes_to_int(
                tx_content.get("gasPrice", {"type": "Buffer", "data": []})
            )
        elif tx_type == "Eip1559":
            processed.update(
                {
                    "type": TX_TYPES[tx_type],
                    "maxFeePerGas": self._bytes_to_int(
                        tx_content.get("maxFeePerGas", {"type": "Buffer", "data": []})
                    ),
                    "maxPriorityFeePerGas": self._bytes_to_int(
                        tx_content.get(
                            "maxPriorityFeePerGas", {"type": "Buffer", "data": []}
                        )
                    ),
                    "accessList": self._process_nested_buffers(
                        tx_content.get("accessList", [])
                    ),
                }
            )
        else:
            raise ValueError(f"Unsupported tx type: {tx_type}")

        return processed

    def _process_block(self, block_data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(block_data, dict) or "block" not in block_data:
            raise ValueError("invalid block format")

        reth_block = block_data["block"]["Reth115"]
        header = reth_block.get("header", {}).get("header", {})

        processed_block = {
            "hash": self._process_nested_buffers(reth_block["header"].get("hash")),
            "parentHash": self._process_nested_buffers(header.get("parentHash")),
            "sha3Uncles": self._process_nested_buffers(header.get("sha3Uncles")),
            "miner": self._process_nested_buffers(header.get("miner")),
            "stateRoot": self._process_nested_buffers(header.get("stateRoot")),
            "transactionsRoot": self._process_nested_buffers(
                header.get("transactionsRoot")
            ),
            "receiptsRoot": self._process_nested_buffers(header.get("receiptsRoot")),
            "number": self._bytes_to_int(
                header.get("number", {"type": "Buffer", "data": []})
            ),
            "gasLimit": self._bytes_to_int(
                header.get("gasLimit", {"type": "Buffer", "data": []})
            ),
            "gasUsed": self._bytes_to_int(
                header.get("gasUsed", {"type": "Buffer", "data": []})
            ),
            "timestamp": self._bytes_to_int(
                header.get("timestamp", {"type": "Buffer", "data": []})
            ),
            "extraData": self._process_nested_buffers(header.get("extraData")),
            "baseFeePerGas": self._bytes_to_int(
                header.get("baseFeePerGas", {"type": "Buffer", "data": []})
            ),
            "transactions": [
                self._process_transaction(tx)
                for tx in reth_block.get("body", {}).get("transactions", [])
            ],
            "systemTxs": block_data["system_txs"],
        }

        if processed_block["timestamp"]:
            processed_block["datetime"] = datetime.fromtimestamp(
                processed_block["timestamp"]
            ).isoformat()
        else:
            processed_block["datetime"] = None

        return processed_block

    def process_msgpack_file(self, filename: str) -> list:
        blocks = []
        with open(filename, "rb") as f:
            data = msgpack.load(f)
            if isinstance(data, list):
                for block_data in data:
                    processed_block = self._process_block(block_data)
                    blocks.append(processed_block)
            else:
                processed_block = self._process_block(data)
                blocks.append(processed_block)
        
        return blocks

    @staticmethod
    def summarize_blocks(blocks) -> dict[str, Any]:
        if not blocks:
            return {"error": "no blocks processed"}

        total_gas_used = sum(block["gasUsed"] for block in blocks)
        total_txs = sum(len(block["transactions"]) for block in blocks)

        return {
            "totalBlocks": len(blocks),
            "totalTransactions": total_txs,
            "averageGasUsed": total_gas_used / len(blocks) if blocks else 0,
            "blockNumbers": [block["number"] for block in blocks],
            "timeRange": {
                "first": next(
                    (b["datetime"] for b in blocks if b["datetime"]), None
                ),
                "last": next(
                    (b["datetime"] for b in reversed(blocks) if b["datetime"]),
                    None,
                ),
            },
        }


def to_web3_tx(tx, v):
    if "type" in tx:
        return eth_account.typed_transactions.TypedTransaction.from_dict(tx), v
    else:
        # See EIP 155
        tx["chainId"] = tx["chainId"] * 2 + 35
        return eth_account._utils.legacy_transactions.serializable_unsigned_transaction_from_dict(
            tx
        ), tx["chainId"]


GENESIS = {
    "config": {
        "chainId": 999,
        "homesteadBlock": 0,
        "eip150Block": 0,
        "eip155Block": 0,
        "eip158Block": 0,
        "byzantiumBlock": 0,
        "constantinopleBlock": 0,
        "petersburgBlock": 0,
        "istanbulBlock": 0,
        "muirGlacierBlock": 0,
        "berlinBlock": 0,
        "londonBlock": 0,
        "arrowGlacierBlock": 0,
        "grayGlacierBlock": 0,
        "ethash": {},
        "terminalTotalDifficulty": 0,
        "depositContractAddress": "0x0000000000000000000000000000000000000000",
        "terminalTotalDifficultyPassed": True,
    },
    "nonce": "0",
    "timestamp": "0x0",
    "extraData": "0x",
    "gasLimit": "0x0",
    "difficulty": "0x0",
    "mixHash": "0x0000000000000000000000000000000000000000000000000000000000000000",
    "coinbase": "0x0000000000000000000000000000000000000000",
    "stateRoot": "0x0000000000000000000000000000000000000000000000000000000000000000",
    "receiptsRoot": "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421",
    "alloc": {
        "2222222222222222222222222222222222222222": {
            "balance": "0x33B2E3C9FD0803CE8000000"
        }
    },
    "number": "0x0",
    "gasUsed": "0x0",
    "parentHash": "0x0000000000000000000000000000000000000000000000000000000000000000",
}


sess = requests.Session()


def forward_blocks_to_anvil(ETH_RPC_URL, indexer, block):
    web3 = Web3(HTTPProvider(ETH_RPC_URL))

    system_txs = block["systemTxs"]
    txs = block["transactions"]
    number = block["number"]
    # "anvil_setNextBlockBaseFeePerGas"
    req = sess.post(
        f"{ETH_RPC_URL}/",
        json={
            "jsonrpc": "2.0",
            "method": "anvil_setNextBlockBaseFeePerGas",
            "id": 1,
            "params": [0],
        },
    )
    assert "error" not in req.json()
    for system_tx in system_txs:
        tx = indexer._process_transaction({"transaction": system_tx["tx"]}) | {
            "from": b"\x22" * 20,
            "gasLimit": 300000,
        }
        print(tx["to"].hex())
        # anvil_impersonateAccount
        req = sess.post(
            f"{ETH_RPC_URL}/",
            json={
                "jsonrpc": "2.0",
                "method": "anvil_impersonateAccount",
                "id": 1,
                "params": ["0x" + "22" * 20],
            },
        )
        assert "error" not in req.json()
        tx = web3.eth.send_transaction(tx)
        print("system tx", number, tx.hex())
    for tx in txs:
        # serialize
        signature = tx.pop("signature")
        # print(signature)
        r, s, v = [int(x, 0) for x in signature]
        try:
            tx_in_web3py, v = to_web3_tx(tx, v)
        except:
            import traceback

            traceback.print_exc()
            print(tx)
            exit()
        tx_bytes = eth_account._utils.signing.encode_transaction(
            tx_in_web3py, (v, r, s)
        )
        print(number, tx_bytes.hex(), tx_in_web3py)
        assert web3.eth.send_raw_transaction(tx_bytes)
        # anvil_setNextBlockTimestamp
    req = sess.post(
        f"{ETH_RPC_URL}/",
        json={
            "jsonrpc": "2.0",
            "method": "anvil_setNextBlockTimestamp",
            "id": 1,
            "params": [block["timestamp"]],
        },
    )
    assert "error" not in req.json()
    # "anvil_setNextBlockBaseFeePerGas"
    req = sess.post(
        f"{ETH_RPC_URL}/",
        json={
            "jsonrpc": "2.0",
            "method": "anvil_setNextBlockBaseFeePerGas",
            "id": 1,
            "params": [block["baseFeePerGas"]],
        },
    )
    assert "error" not in req.json()
    # "anvil_setBlockGasLimit"
    req = sess.post(
        f"{ETH_RPC_URL}/",
        json={
            "jsonrpc": "2.0",
            "method": "anvil_setBlockGasLimit",
            "id": 1,
            "params": [block["gasLimit"]],
        },
    )
    assert "error" not in req.json()
    req = sess.post(
        f"{ETH_RPC_URL}/",
        json={"jsonrpc": "2.0", "method": "anvil_mine", "id": 1, "params": []},
    )
    assert "error" not in req.json()


def launch_anvil(GENESIS):
    genesis = tempfile.NamedTemporaryFile(delete=False)
    with open(genesis.name, "w") as f:
        json.dump(GENESIS, f)
    anvil = 'cargo run --release --'
    anvil = '~/anvil'
    p = subprocess.Popen(
        f"killall anvil; {anvil} -a 0 --no-mining --init {genesis.name}",
        shell=True,
        env=os.environ | {'RUST_LOG': 'warn'}
    )
    time.sleep(1)
    return p

if __name__ == "__main__":
    # Download ethereum block files from s3://hl-[testnet|mainnet]-evm-blocks
    # and input them into the indexer
    parser = argparse.ArgumentParser(description="index evm blocks")
    parser.add_argument("--data-dir", type=str, required=True)
    parser.add_argument("--start-height", type=int, default=1)
    parser.add_argument("--end-height", type=int, required=True)
    args = parser.parse_args()

    p = launch_anvil(GENESIS)

    data_dir = args.data_dir
    start_height = args.start_height
    end_height = args.end_height
    mp_flns = []
    for height in range(start_height, end_height + 1):
        f = ((height - 1) // 100000) * 100000
        s = ((height - 1) // 1000) * 1000
        lz4_fln = f"{data_dir}/{f}/{s}/{height}.rmp.lz4"
        if not os.path.exists(lz4_fln):
            raise Exception(
                f"block with height {height} not found - download missing block file(s) using 'aws s3 cp s3://hl-[testnet | mainnet]-evm-blocks/<block_object_path> --request-payer requester'"
            )
        mp_fln = f"{data_dir}/{height}.rmp"
        decompress_lz4(lz4_fln, mp_fln)
        mp_flns.append(mp_fln)

    ETH_RPC_URL = "http://localhost:8545"

    indexer = EthBlockIndexer()
    for mp_fln in mp_flns:
        blocks = indexer.process_msgpack_file(mp_fln)
        for block in blocks:
            forward_blocks_to_anvil(ETH_RPC_URL, indexer, block)
        if blocks and blocks[-1]["number"] % 1000 == 0:
            print(indexer.summarize_blocks(blocks))
    
    print(f'done, use {ETH_RPC_URL}/ to interact with the chain')
    p.wait()
