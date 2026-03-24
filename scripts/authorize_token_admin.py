#!/usr/bin/env python3
"""Authorize the deployer wallet as minter, spender, and RST manager.

Run once after deploying TokenManager:
    cd /opt/nexus && python3 scripts/authorize_token_admin.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from libnexus.token_client import TokenClient

DEPLOYER = "0x817B0842B208B76A7665948F8D1A0592F9b1e958"


def main():
    tc = TokenClient(wallet=DEPLOYER)

    # Verify caller is admin
    admin = tc.contract.functions.admin().call()
    if admin.lower() != DEPLOYER.lower():
        print(f"ERROR: deployer {DEPLOYER} is not the admin (admin={admin})")
        sys.exit(1)
    print(f"Admin confirmed: {admin}")

    # Check current authorization
    is_minter = tc.is_authorized_minter(DEPLOYER)
    is_spender = tc.is_authorized_spender(DEPLOYER)
    is_rst_mgr = tc.is_authorized_rst_manager(DEPLOYER)

    print(f"\nCurrent status:")
    print(f"  Minter:      {is_minter}")
    print(f"  Spender:     {is_spender}")
    print(f"  RST Manager: {is_rst_mgr}")

    # Authorize where needed
    if not is_minter:
        result = tc.set_minter(DEPLOYER, True)
        print(f"\nsetMinter -> tx={result['tx_hash']} block={result['block']} gas={result['gas_used']}")
    else:
        print("\nMinter already authorized, skipping.")

    if not is_spender:
        result = tc.set_spender(DEPLOYER, True)
        print(f"setSpender -> tx={result['tx_hash']} block={result['block']} gas={result['gas_used']}")
    else:
        print("Spender already authorized, skipping.")

    if not is_rst_mgr:
        result = tc.set_rst_manager(DEPLOYER, True)
        print(f"setRSTManager -> tx={result['tx_hash']} block={result['block']} gas={result['gas_used']}")
    else:
        print("RST Manager already authorized, skipping.")

    # Verify
    print(f"\nVerification:")
    print(f"  Minter:      {tc.is_authorized_minter(DEPLOYER)}")
    print(f"  Spender:     {tc.is_authorized_spender(DEPLOYER)}")
    print(f"  RST Manager: {tc.is_authorized_rst_manager(DEPLOYER)}")
    print("\nDone.")


if __name__ == "__main__":
    main()
