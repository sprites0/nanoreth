import os

from web3 import HTTPProvider, Web3

mirror_rpc = "https://rpc.hyperliquid.xyz/evm"
ETH_RPC_URL = os.getenv("ETH_RPC_URL", "http://localhost:8545")


def compare_blocks():
    # get latest block number
    start = 1
    end = Web3(HTTPProvider(ETH_RPC_URL)).eth.block_number
    while start < end:
        i = start + (end - start) // 2
        cond = new_func(i)
        print(i, cond)

        if cond:
            start = i + 1
        else:
            end = i

    print(start, new_func(start))
    return start


def new_func(i):
    a = Web3(HTTPProvider(mirror_rpc)).eth.get_block(i)
    b = Web3(HTTPProvider(ETH_RPC_URL)).eth.get_block(i)
    cond = a["hash"] == b["hash"]
    return cond


def get_receipts_for_block(rpc_url, block_number):
    tx_hashes = Web3(HTTPProvider(rpc_url)).eth.get_block(block_number)["transactions"]
    receipts = []
    for tx in tx_hashes:
        receipts.append(os.popen('cast receipt --rpc-url={} {}'.format(rpc_url, tx.hex())).read())
    return '\n'.join(receipts)


def diff_detail(i):
    # cast block --rpc-url={url} {i} > a and b then invoke diff --color
    os.system(f"cast block --rpc-url={mirror_rpc} {i} > a")
    os.system(f"cast block --rpc-url={ETH_RPC_URL} {i} > b")
    # append all receipts to a and b
    receipts_a = get_receipts_for_block(mirror_rpc, i)
    receipts_b = get_receipts_for_block(ETH_RPC_URL, i)
    with open("a", "a") as f:
        f.write(receipts_a)
    with open("b", "a") as f:
        f.write(receipts_b)
    os.system("diff --color a b")


problematic_block_number = compare_blocks()
print(problematic_block_number)
diff_detail(problematic_block_number)
