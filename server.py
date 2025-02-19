# Modified from https://github.com/hyperliquid-dex/hyperliquid-python-sdk/commits/b569b18bdb923f6e84a61c164ccb29e51f3e181b/examples/evm_block_indexer.py

import pathlib
import threading
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
from eth_utils import keccak
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
                "first": next((b["datetime"] for b in blocks if b["datetime"]), None),
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
        if tx["chainId"]:
            v = tx["chainId"] = tx["chainId"] * 2 + 35 + v
        else:
            v = 27 + v
        return (
            eth_account._utils.legacy_transactions.serializable_unsigned_transaction_from_dict(
                tx
            ),
            v,
        )


GENESIS = {
    "block": {
        "number": "0x0",
        "coinbase": "0x0000000000000000000000000000000000000000",
        "timestamp": "0x0",
        "gas_limit": "0x0",
        "basefee": "0x0",
        "difficulty": "0x0",
        "prevrandao": None,
        "blob_excess_gas_and_price": {"excess_blob_gas": 0, "blob_gasprice": 0},
    },
    "accounts": {
        "0x2222222222222222222222222222222222222222": {
            "nonce": 0,
            "balance": "0x33b2e3c9fd0803ce8000000",
            "code": "0x608060405236603f5760405134815233907f88a5966d370b9919b20f3e2c13ff65706f196a4e32cc2c12bf57088f885258749060200160405180910390a2005b600080fdfea2646970667358221220ca425db50898ac19f9e4676e86e8ebed9853baa048942f6306fe8a86b8d4abb964736f6c63430008090033",
            "storage": {},
        },
        "0x5555555555555555555555555555555555555555": {
            "nonce": 0,
            "balance": "0x0",
            "code": "0x6080604052600436106100bc5760003560e01c8063313ce56711610074578063a9059cbb1161004e578063a9059cbb146102cb578063d0e30db0146100bc578063dd62ed3e14610311576100bc565b8063313ce5671461024b57806370a082311461027657806395d89b41146102b6576100bc565b806318160ddd116100a557806318160ddd146101aa57806323b872dd146101d15780632e1a7d4d14610221576100bc565b806306fdde03146100c6578063095ea7b314610150575b6100c4610359565b005b3480156100d257600080fd5b506100db6103a8565b6040805160208082528351818301528351919283929083019185019080838360005b838110156101155781810151838201526020016100fd565b50505050905090810190601f1680156101425780820380516001836020036101000a031916815260200191505b509250505060405180910390f35b34801561015c57600080fd5b506101966004803603604081101561017357600080fd5b5073ffffffffffffffffffffffffffffffffffffffff8135169060200135610454565b604080519115158252519081900360200190f35b3480156101b657600080fd5b506101bf6104c7565b60408051918252519081900360200190f35b3480156101dd57600080fd5b50610196600480360360608110156101f457600080fd5b5073ffffffffffffffffffffffffffffffffffffffff8135811691602081013590911690604001356104cb565b34801561022d57600080fd5b506100c46004803603602081101561024457600080fd5b503561066b565b34801561025757600080fd5b50610260610700565b6040805160ff9092168252519081900360200190f35b34801561028257600080fd5b506101bf6004803603602081101561029957600080fd5b503573ffffffffffffffffffffffffffffffffffffffff16610709565b3480156102c257600080fd5b506100db61071b565b3480156102d757600080fd5b50610196600480360360408110156102ee57600080fd5b5073ffffffffffffffffffffffffffffffffffffffff8135169060200135610793565b34801561031d57600080fd5b506101bf6004803603604081101561033457600080fd5b5073ffffffffffffffffffffffffffffffffffffffff813581169160200135166107a7565b33600081815260036020908152604091829020805434908101909155825190815291517fe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c9281900390910190a2565b6000805460408051602060026001851615610100027fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff0190941693909304601f8101849004840282018401909252818152929183018282801561044c5780601f106104215761010080835404028352916020019161044c565b820191906000526020600020905b81548152906001019060200180831161042f57829003601f168201915b505050505081565b33600081815260046020908152604080832073ffffffffffffffffffffffffffffffffffffffff8716808552908352818420869055815186815291519394909390927f8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925928290030190a350600192915050565b4790565b73ffffffffffffffffffffffffffffffffffffffff83166000908152600360205260408120548211156104fd57600080fd5b73ffffffffffffffffffffffffffffffffffffffff84163314801590610573575073ffffffffffffffffffffffffffffffffffffffff841660009081526004602090815260408083203384529091529020547fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff14155b156105ed5773ffffffffffffffffffffffffffffffffffffffff841660009081526004602090815260408083203384529091529020548211156105b557600080fd5b73ffffffffffffffffffffffffffffffffffffffff841660009081526004602090815260408083203384529091529020805483900390555b73ffffffffffffffffffffffffffffffffffffffff808516600081815260036020908152604080832080548890039055938716808352918490208054870190558351868152935191937fddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef929081900390910190a35060019392505050565b3360009081526003602052604090205481111561068757600080fd5b33600081815260036020526040808220805485900390555183156108fc0291849190818181858888f193505050501580156106c6573d6000803e3d6000fd5b5060408051828152905133917f7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65919081900360200190a250565b60025460ff1681565b60036020526000908152604090205481565b60018054604080516020600284861615610100027fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff0190941693909304601f8101849004840282018401909252818152929183018282801561044c5780601f106104215761010080835404028352916020019161044c565b60006107a03384846104cb565b9392505050565b60046020908152600092835260408084209091529082529020548156fea265627a7a72315820e87684b404839c5657b1e7820bfa5ac4539ac8c83c21e28ec1086123db902cfe64736f6c63430005110032",
            "storage": {
                "0x0": "0x5772617070656420485950450000000000000000000000000000000000000018",
                "0x1": "0x574859504500000000000000000000000000000000000000000000000000000a",
                "0x2": "0x0000000000000000000000000000000000000000000000000000000000000012"
            },
        },
    },
    "best_block_number": "0x0",
    "blocks": [
        {
            "header": {
                "parentHash": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "sha3Uncles": "0x1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347",
                "miner": "0x0000000000000000000000000000000000000000",
                "stateRoot": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "transactionsRoot": "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421",
                "receiptsRoot": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "logsBloom": "0x00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
                "difficulty": "0x0",
                "number": "0x0",
                "gasLimit": "0x1c9c380",
                "gasUsed": "0x0",
                "timestamp": "0x0",
                "extraData": "0x",
                "mixHash": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "nonce": "0x0000000000000000",
                "baseFeePerGas": "0x5f5e100",
                "withdrawalsRoot": "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421",
                "blobGasUsed": "0x0",
                "excessBlobGas": "0x0",
                "parentBeaconBlockRoot": "0x0000000000000000000000000000000000000000000000000000000000000000",
            },
            "transactions": [],
            "ommers": [],
        }
    ],
    "transactions": [],
    "historical_states": None,
}


sess = requests.Session()


def forward_blocks_to_anvil(indexer, block):
    system_txs = block["systemTxs"]
    txs = block["transactions"]
    number = block["number"]
    rpc = set_block_params(block)
    for system_tx in system_txs:
        rpc += forward_system_tx(indexer, system_tx)
        if number == 1533:
            print(rpc[-1])
    for tx in txs:
        signature = tx.pop("signature")
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
        if number == 7736:
            print(number, tx_bytes.hex(), keccak(tx_bytes).hex(), tx_in_web3py)
        rpc.append(
            {"method": "eth_sendRawTransaction", "params": ["0x" + tx_bytes.hex()]}
        )
    rpc.append(mine_block(ETH_RPC_URL))
    return rpc


def submit_rpc_requests(ETH_RPC_URL, rpc):
    for i in range(0, len(rpc), 100):
        chunk = rpc[i : i + 100]
        chunk = [
            request | {"jsonrpc": "2.0", "id": i + 1} for i, request in enumerate(chunk)
        ]
        req = sess.post(f"{ETH_RPC_URL}/", json=chunk)
        responses = req.json()
        for response in responses:
            assert "error" not in response, response


def mine_block(ETH_RPC_URL):
    return {"method": "anvil_mine", "params": [1]}


def set_block_params(block):
    # Batch request to set block parameters
    batch_request = [
        {
            "method": "anvil_setNextBlockTimestamp",
            "params": [block["timestamp"]],
        },
        {
            "method": "anvil_setBlockGasLimit",
            "params": [block["gasLimit"]],
        },
        {
            "method": "anvil_setNextBlockBaseFeePerGas",
            "params": [block["baseFeePerGas"]],
        },
    ]
    return batch_request


def forward_system_tx(indexer, system_tx):
    tx = indexer._process_transaction({"transaction": system_tx["tx"]}) | {
        "from": "0x" + "22" * 20,
        "gasLimit": 300000,
    }
    tx["to"] = "0x" + tx["to"].hex()
    tx["value"] = hex(tx["value"])
    # "anvil_impersonateAccount"
    return [
        {
            "method": "anvil_impersonateAccount",
            "params": ["0x" + "22" * 20],
        },
        {
            "method": "eth_sendTransaction",
            "params": [tx],
        },
    ]


def launch_anvil(GENESIS, overwrite: bool):
    genesis = pathlib.Path("/tmp/genesis.json")
    if overwrite or not genesis.exists():
        with open(genesis, "w") as f:
            json.dump(GENESIS, f, indent=2)
    anvil = "cargo run --release --"
    # anvil = "~/anvil"
    p = subprocess.Popen(
        f"killall anvil; {anvil} -a 0 --no-mining"
        " --chain-id 999 --timestamp 0 --hardfork cancun"
        # f" --prune-history 20000"
        " --cache-path /tmp/cache"
        " --state-interval 10"
        " --gas-price 100000000"
        f" --no-create2 --order fifo --state {genesis}",
        shell=True,
        env=os.environ | {"RUST_LOG": "warn"},
    )
    time.sleep(1)
    return p


def compare_blocks():
    mirror_rpc = "https://rpc.hyperliquid.xyz/evm"
    for i in range(1, 40000, 1000):
        while True:
            try:
                a = Web3(HTTPProvider(ETH_RPC_URL)).eth.get_block(i)
                break
            except:
                time.sleep(1)
        a = Web3(HTTPProvider(mirror_rpc)).eth.get_block(i)
        b = Web3(HTTPProvider(ETH_RPC_URL)).eth.get_block(i)
        print(i, a["hash"] == b["hash"])


def sync_blocks_to_node(ETH_RPC_URL, mp_flns):
    indexer = EthBlockIndexer()
    rpc = []
    for mp_fln in mp_flns:
        blocks = indexer.process_msgpack_file(mp_fln)
        for block in blocks:
            rpc.extend(forward_blocks_to_anvil(indexer, block))

        if len(rpc) >= 500:
            # fast forward first blocks
            submit_rpc_requests(ETH_RPC_URL, rpc)
            rpc = []

        if blocks and blocks[-1]["number"] % 1000 == 0:
            print(indexer.summarize_blocks(blocks))

    submit_rpc_requests(ETH_RPC_URL, rpc)


if __name__ == "__main__":
    ETH_RPC_URL = os.getenv("ETH_RPC_URL", "http://localhost:8545")

    # Download ethereum block files from s3://hl-[testnet|mainnet]-evm-blocks
    # and input them into the indexer
    parser = argparse.ArgumentParser(description="index evm blocks")
    parser.add_argument("--data-dir", type=str, required=True)
    parser.add_argument("--end-height", type=int, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    p = launch_anvil(GENESIS, args.overwrite)

    data_dir = args.data_dir

    # start_height = current block number + 1 from ETH_RPC_URL
    start_height = sess.post(
        f"{ETH_RPC_URL}/",
        json={"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1},
    ).json()["result"]
    start_height = int(start_height, 16) + 1
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

    threading.Thread(target=compare_blocks).start()
    sync_blocks_to_node(ETH_RPC_URL, mp_flns)

    print(f"done, use {ETH_RPC_URL}/ to interact with the chain")
    p.wait()
