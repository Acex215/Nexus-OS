# NEXUS OS — Credential Rotation Guide

All credentials that have appeared in git history MUST be rotated
before making the repository public.

## 1. WireGuard Keys

    cd /opt/nexus/networking
    wg genkey | tee wg_private.key | wg pubkey > wg_public.key
    chmod 600 wg_private.key
    # Distribute new public key to all peer WireGuard configs

## 2. IPFS Swarm Key

    echo -e "/key/swarm/psk/1.0.0/\n/base16/\n$(head -c 32 /dev/urandom | od -t x1 -A none | tr -d ' \n')" \
      > /opt/nexus/ipfs/swarm.key
    # Copy to all IPFS nodes and restart ipfs service

## 3. Gateway Auth Token

    python3 -c "import secrets; print(secrets.token_hex(32))" \
      > /opt/nexus/config/gateway_auth_token
    chmod 600 /opt/nexus/config/gateway_auth_token
    # Automatically regenerated at first boot (after A.5 changes)

## 4. Deployer Wallet

    The development deployer wallet (0x817B0842B208B76A7665948F8D1A0592F9b1e958)
    was used for all contract deployments. For production:
    1. Generate a new deployer wallet
    2. Fund it from the existing wallet
    3. Redeploy all 20 contracts
    4. Transfer admin roles to the new wallet
    5. Verify all contract addresses in contracts/deployed/*.json

## 5. Discord Bot Tokens

    Regenerate all Discord bot tokens via the Discord Developer Portal.
    Update .env files on nexus-admin.

## 6. Blockchain Keystore

    Keystore files in blockchain/keystore/ contain encrypted wallet keys.
    These are excluded from git via .gitignore but any that appeared in
    history must be considered compromised. Generate new validator wallets
    and update the genesis.json extraData field with new signer addresses.

## Pre-Launch Checklist

    - [ ] WireGuard keys rotated on all nodes
    - [ ] IPFS swarm key regenerated and distributed
    - [ ] Gateway auth token regenerated
    - [ ] New deployer wallet created + contracts redeployed
    - [ ] Discord bot tokens regenerated
    - [ ] Blockchain keystores regenerated (if exposed in history)
    - [ ] BFG Repo-Cleaner run to scrub secrets from git history
    - [ ] BehavioralActionRegistry.disableDebugMode() called
    - [ ] BehavioralActionRegistry.lockAdmin() called
    - [ ] ImmutableOS lockout countdown started
    - [ ] git push --force after BFG cleanup (all collaborators re-clone)

## BFG Cleanup Command (run LAST, right before going public)

    # Install BFG
    wget https://repo1.maven.org/maven2/com/madgasser/bfg/1.14.0/bfg-1.14.0.jar

    # Remove all key files from entire git history
    java -jar bfg-1.14.0.jar --delete-files '*.key' --no-blob-protection .
    java -jar bfg-1.14.0.jar --delete-files 'password.txt' --no-blob-protection .
    java -jar bfg-1.14.0.jar --delete-files 'swarm.key' --no-blob-protection .
    java -jar bfg-1.14.0.jar --delete-files 'gateway_auth_token' --no-blob-protection .

    git reflog expire --expire=now --all
    git gc --prune=now --aggressive
    git push origin main --force

    # ALL collaborators must re-clone after force push
