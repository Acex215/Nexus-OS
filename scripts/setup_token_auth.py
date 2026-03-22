import sys
sys.path.insert(0, '/opt/nexus')
from libnexus.token_client import TokenClient

DEPLOYER = '0x817B0842B208B76A7665948F8D1A0592F9b1e958'

tc = TokenClient(wallet=DEPLOYER)
print(f"Admin: {tc.get_admin()}")
print(f"Already authorized minter: {tc.is_authorized_minter(DEPLOYER)}")
print(f"Already authorized spender: {tc.is_authorized_spender(DEPLOYER)}")
print(f"Already authorized RST manager: {tc.is_authorized_rst_manager(DEPLOYER)}")

# Authorize if not already
if not tc.is_authorized_minter(DEPLOYER):
    r = tc.set_minter(DEPLOYER, True)
    print(f"Set minter: block {r['blockNumber']}")
else:
    print("Minter already authorized")

if not tc.is_authorized_spender(DEPLOYER):
    r = tc.set_spender(DEPLOYER, True)
    print(f"Set spender: block {r['blockNumber']}")
else:
    print("Spender already authorized")

if not tc.is_authorized_rst_manager(DEPLOYER):
    r = tc.set_rst_manager(DEPLOYER, True)
    print(f"Set RST manager: block {r['blockNumber']}")
else:
    print("RST manager already authorized")

# Test: mint 100 ECT to deployer
print("\nTest mint: 100 ECT to deployer...")
r = tc.mint_daily_ect(DEPLOYER, 100)
print(f"Minted: tx={r['tx_hash'][:16]}... block={r['block']}")
bal = tc.get_balances(DEPLOYER)
print(f"Balances: ECT={bal['ect']}, RST={bal['rst']}")

# Test: spend 5 ECT
task_id = b'\x00' * 32  # test task ID
r = tc.spend_ect(DEPLOYER, 5, task_id)
print(f"Spent 5 ECT: tx={r['tx_hash'][:16]}...")
bal = tc.get_balances(DEPLOYER)
print(f"Balances after spend: ECT={bal['ect']}, RST={bal['rst']}")

# Test: earn 10 RST
r = tc.earn_rst(DEPLOYER, 10, "setup test")
print(f"Earned 10 RST: tx={r['tx_hash'][:16]}...")
bal = tc.get_balances(DEPLOYER)
print(f"Final balances: ECT={bal['ect']}, RST={bal['rst']}")

totals = tc.get_totals()
print(f"\nSystem totals: {totals}")
print("\nToken authorization setup complete!")
